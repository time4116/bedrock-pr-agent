# Bedrock PR Agent

A GitHub App that automatically reviews pull requests using Claude Sonnet 4.6 (claude-sonnet-4-6) via AWS Bedrock. Deployed on AWS — it reviews PRs on this repo automatically.

Built on Bedrock AgentCore Runtime with a LangGraph StateGraph, it validates whether the diff matches what the author said they did and optionally validates Terraform plans. Responds to every `pull_request` event and posts a structured comment within minutes.

## Architecture

```
GitHub PR Event
      │
      ▼
API Gateway ──► Webhook Lambda  (validates HMAC signature, filters repos, <1s response)
                      │
                      ▼ SQS
               Worker Lambda   (triggers AgentCore Runtime)
                      │
                      ▼
            AgentCore Runtime  (containerized LangGraph agent — no Lambda timeout)
            ┌──────────────────────────────────────┐
            │  Node 1: fetch_diff                  │
            │  Node 2: validate_terraform (optional)│
            │  Node 3: analyze_and_comment         │
            └──────────────────────────────────────┘
                      │
                      ▼
              GitHub PR Comment
```

**Why this architecture?**

- **Async SQS queue** — Webhook returns `202 Accepted` in <1s. GitHub has a 10s delivery timeout; Claude analysis takes minutes.
- **AgentCore container runtime** — No Lambda timeout limits (15-min Lambda max is hit on large diffs). Container also eliminates dependency packaging issues.
- **Single GitHub secret** — All credentials (App ID, webhook secret, private key) stored in AWS Secrets Manager with automatic caching.

## What the Agent Does

On every `pull_request` event (`opened`, `synchronize`, `edited`):

1. **Fetches the PR diff** — unified diff of all changed files, truncated at token limits with smart prioritization
2. **Validates Terraform plans** *(optional, per-repo)* — downloads GitHub Actions log archive for the PR's head SHA, parses Terraform plan output, flags resource deletions and `must be replaced` operations
3. **Posts a structured comment** — creates or updates a single bot comment (identified by HTML marker) with findings formatted via Markdown templates

The analysis question is: **does the code diff match what the PR description says it does?** No external ticket system required.

## Setup

See [SETUP.md](SETUP.md) for the full end-to-end guide: GitHub App creation, Secrets Manager, Bedrock model access, CDK deploy, and webhook configuration. Once deployed and installed on your repos, any new PR triggers an automatic review comment.

## Configuration

All configuration is via environment variables. See `.env.example` for the full list.

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_SECRET_NAME` | `github-pr-agent/github` | Secrets Manager secret with `app_id`, `webhook_secret`, `private_key` |
| `BEDROCK_MODEL_ID` | *(required)* | Bedrock model ID or inference profile ARN. For GitHub Actions deploys, store this as a repository secret. |
| `ALLOWED_REPOS` | *(empty = all)* | Comma-separated `owner/repo` filter |
| `TERRAFORM_VALIDATION_REPOS` | *(empty)* | Repos that get Terraform plan analysis |
| `STAGE` | `dev` | Deployment stage; used to namespace all AWS resource names |

## Terraform Plan Validation

For repos listed in `TERRAFORM_VALIDATION_REPOS`, the agent:

1. Finds the most recent completed GitHub Actions run for the PR's head SHA
2. Downloads the log archive (ZIP)
3. Parses `Terraform will perform the following actions:` sections
4. Flags resource deletions (`will be destroyed`) and forced replacements (`must be replaced`)

This catches stagnant branches that would accidentally destroy infrastructure.

## Prompts & Templates

The agent prompt lives in `prompts/`:

- `pr-review.md` — system prompt sent to Claude with the diff, PR metadata, and template injected at runtime

Output comment structure lives in `templates/`:

- `pr-comment-with-terraform.md` — includes Terraform validation section
- `pr-comment-without-terraform.md` — standard review

Both use `{PLACEHOLDER}` tokens filled via `.replace()` — edit them directly to change how reviews look or what Claude is asked to do.

## Deployment

Single command deploys everything — AgentCore Runtime (Docker image → ECR), Lambda functions, SQS queue, and API Gateway:

```bash
cd deploy
pip install -r requirements.txt
cdk deploy --all
```

See `deploy/` for the full CDK app (`app.py`, `stacks/agentcore_stack.py`, `stacks/lambda_stack.py`).

> **Note:** CDK requires Node.js for the CLI (`npm install -g aws-cdk`). The `aws_bedrock_agentcore_alpha` module is alpha — pin the CDK version in `deploy/requirements.txt` to avoid API changes between upgrades.

## Roadmap

### CI failure analysis
The agent currently fetches GitHub Actions logs to validate Terraform plans — the log download and parsing infrastructure (`github_client.get_actions_runs_for_sha`, `download_run_logs`, `extract_log_text`) is already in place. The next step is generalizing this to non-Terraform failures: detect failed workflow steps, extract relevant error lines, and include a root cause summary in the PR comment. No new GitHub API surface needed — it's a new node in the LangGraph graph consuming the same log pipeline.

---

## Troubleshooting

> **Tip:** Check the GitHub App's **Advanced → Recent Deliveries** page first — it shows exactly what GitHub sent and what response it got back, which narrows down whether the issue is at the webhook, Lambda, or AgentCore layer.

### Duplicate comments
**Symptom:** Bot posts the same comment multiple times.

**Root cause:** Worker Lambda `boto3` read timeout (60s default) is shorter than AgentCore processing time (5–10 min). SQS message becomes visible again → new Lambda invocation → second comment.

**Fix applied:** `boto3` read timeout increased to 900s, idempotent create-or-update in `github_commenter` (HTML marker identifies the bot comment), Worker Lambda timeout 15 min, SQS visibility timeout 20 min.

### No comment posted
1. Check CloudWatch logs: webhook Lambda → worker Lambda → AgentCore runtime
2. Verify repo is in `ALLOWED_REPOS`
3. Check GitHub webhook delivery logs in App settings
4. Verify `ALLOWED_REPOS` uses `owner/repo` format (e.g. `time4116/bedrock-pr-agent`)
5. If the worker logs `Resource not accessible by integration` while creating an issue comment, verify the GitHub App has **Issues: read & write** and that the installation owner approved the updated permissions. Top-level PR timeline comments use GitHub's issue comments API.

