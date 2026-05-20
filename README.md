# GitHub PR Agent

An AI-powered GitHub App that automatically reviews pull requests by analyzing code changes against the PR's own description. Built on AWS Bedrock AgentCore Runtime with a LangGraph StateGraph (Claude Sonnet 4 via Bedrock), it validates whether the diff matches what the author said they did, checks organization policies, and optionally validates Terraform plans—all without manual intervention.

The app responds to every `pull_request` event and leaves a structured, actionable comment within minutes.

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
            │  Node 2: check_policy      (optional)│
            │  Node 3: validate_terraform (optional)│
            │  Node 4: analyze_and_comment         │
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
2. **Checks organization policies** *(optional)* — loads policy docs from `policies/` directory, surfaces violations and recommendations
3. **Validates Terraform plans** *(optional, per-repo)* — downloads GitHub Actions log archive for the PR's head SHA, parses Terraform plan output, flags resource deletions and `must be replaced` operations
4. **Posts a structured comment** — creates or updates a single bot comment (identified by HTML marker) with findings formatted via Markdown templates

The analysis question is: **does the code diff match what the PR description says it does?** No external ticket system required.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
npm install -g aws-cdk          # CDK CLI requires Node.js

# 2. Configure environment
cp .env.example .env            # Edit with your values

# 3. Deploy everything (AgentCore Runtime + Lambda + SQS + API Gateway)
cd deploy
pip install -r requirements.txt
export AWS_ACCOUNT=123456789012
export AWS_REGION=us-east-1
export STAGE=dev
export GITHUB_SECRET_NAME=github-pr-agent/github
export BEDROCK_MODEL_ID=<your-bedrock-inference-profile-arn>
export ALLOWED_REPOS=your-org/your-repo
cdk deploy --all
```

## Configuration

All configuration is via environment variables. See `.env.example` for the full list.

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_SECRET_NAME` | `github-pr-agent/github` | Secrets Manager secret with `app_id`, `webhook_secret`, `private_key` |
| `BEDROCK_MODEL_ID` | — | Bedrock inference profile ARN (Claude Sonnet 4 recommended) |
| `ALLOWED_REPOS` | *(empty = all)* | Comma-separated `owner/repo` filter |
| `TERRAFORM_VALIDATION_REPOS` | *(empty)* | Repos that get Terraform plan analysis |
| `ORG_POLICY_CHECK_ENABLED` | `false` | Enable policy checking from `policies/` directory |
| `STAGE` | `dev` | Deployment stage; used to namespace all AWS resource names |

## Organization Policy Checking

Add policy documents as `.md` files to the `policies/` directory. The agent reads all docs and surfaces relevant sections in the PR comment.

See `policies/IMPLEMENTATION.md` for the planned upgrade to vector-based retrieval (Bedrock Titan Embeddings + cosine similarity).

## Terraform Plan Validation

For repos listed in `TERRAFORM_VALIDATION_REPOS`, the agent:

1. Finds the most recent completed GitHub Actions run for the PR's head SHA
2. Downloads the log archive (ZIP)
3. Parses `Terraform will perform the following actions:` sections
4. Flags resource deletions (`will be destroyed`) and forced replacements (`must be replaced`)

This catches stagnant branches that would accidentally destroy infrastructure.

## PR Comment Templates

Comments are rendered from Markdown templates in `templates/`:

- `pr-comment-with-terraform.md` — includes Terraform validation section
- `pr-comment-without-terraform.md` — standard review (policy check + code analysis)

The agent fills in template placeholders based on its findings.

## Deployment

Single command deploys everything — AgentCore Runtime (Docker image → ECR), Lambda functions, SQS queue, and API Gateway:

```bash
cd deploy
pip install -r requirements.txt
cdk deploy --all
```

See `deploy/` for the full CDK app (`app.py`, `stacks/agentcore_stack.py`, `stacks/lambda_stack.py`).

> **Note:** CDK requires Node.js for the CLI (`npm install -g aws-cdk`). The `aws_bedrock_agentcore_alpha` module is alpha — pin the CDK version in `deploy/requirements.txt` to avoid API changes between upgrades.

## Troubleshooting

### Duplicate comments
**Symptom:** Bot posts the same comment multiple times.

**Root cause:** Worker Lambda `boto3` read timeout (60s default) is shorter than AgentCore processing time (5–10 min). SQS message becomes visible again → new Lambda invocation → second comment.

**Fix applied:** `boto3` read timeout increased to 900s, idempotent create-or-update in `github_commenter` (HTML marker identifies the bot comment), Worker Lambda timeout 15 min, SQS visibility timeout 20 min.

### No comment posted
1. Check CloudWatch logs: webhook Lambda → worker Lambda → AgentCore runtime
2. Verify repo is in `ALLOWED_REPOS`
3. Check GitHub webhook delivery logs in App settings
