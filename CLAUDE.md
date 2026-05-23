# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Linting and formatting
```bash
black --check .
flake8 .
mypy src/
```
Fix formatting: `black .`

### Deploy
```bash
cd deploy
pip install -r requirements.txt
cdk deploy --all
```
Deploys both stacks in dependency order. CDK requires Node.js (`npm install -g aws-cdk`). The `aws_bedrock_agentcore_alpha` module is pinned — do not upgrade without testing.

## Architecture

```
GitHub PR Event
      │
      ▼
API Gateway → Webhook Lambda  (HMAC validation, repo filter, rate limit → SQS)
                    │ SQS
                    ▼
             Worker Lambda    (thin: unpacks SQS, invokes AgentCore)
                    │
                    ▼
          AgentCore Runtime   (containerized LangGraph graph — no timeout)
          ┌─────────────────────────────────────────┐
          │  fetch_diff → [validate_terraform] →    │
          │  analyze_and_comment                    │
          └─────────────────────────────────────────┘
                    │
                    ▼
            GitHub PR Comment
```

**Two-stack CDK deploy:**
- `AgentCoreStack` (`deploy/stacks/agentcore_stack.py`) — builds the Docker image, pushes to ECR, and creates the AgentCore Runtime. `BEDROCK_MODEL_ID` is supplied from environment/GitHub Secrets.
- `LambdaStack` (`deploy/stacks/lambda_stack.py`) — API Gateway, Webhook Lambda, Worker Lambda, SQS queue, S3 rate-limit bucket. Receives the AgentCore ARN and configured Bedrock model ID from `AgentCoreStack`/config.

**AgentCore entrypoint:** `pr_agent.py` (root). The LangGraph business logic lives in `src/agent/graph.py`.

## LangGraph Graph (`src/agent/graph.py`)

The graph is built by `build_graph()` → `StateGraph(PRReviewState)`. Node execution order:

1. `fetch_diff` — always runs; fetches the unified diff via GitHub API (raw `vnd.github.v3.diff`), truncates at 400 KB (first 160 KB + last 160 KB).
2. `validate_terraform` — only for repos in `TERRAFORM_VALIDATION_REPOS`; downloads GitHub Actions log archive for the PR's head SHA and parses Terraform plan output.
3. `analyze_and_comment` — calls Bedrock (`ChatBedrockConverse`), fills `{PLACEHOLDER}` tokens in the selected template, posts or updates the bot comment.
4. `handle_error` — terminal error node; posts a minimal error comment to the PR.

Routing between nodes is conditional (see `_route_after_*` functions). An `error` key in state redirects any node to `handle_error`.

## State (`src/agent/state.py`)

`PRReviewState` is a `TypedDict` that flows through the graph. Key fields: `installation_id`, `owner`, `repo`, `pr_number`, `pr_title`, `pr_body`, `head_sha`, `pr_diff`, `diff_stats`, `terraform_results`, `analysis`, `comment_posted`, `error`.

## Authentication

`src/utils/secrets.py:get_github_credentials()` checks for `GITHUB_TOKEN` first — if set, Secrets Manager is skipped entirely and the PAT is used directly. In production, it reads `app_id`, `webhook_secret`, `private_key` from the Secrets Manager secret named by `GITHUB_SECRET_NAME`.

## Templates and Prompts

- `prompts/pr-review.md` — system prompt; placeholders `{REPO}`, `{PR_NUMBER}`, `{PR_TITLE}`, `{PR_BODY}`, `{DIFF}`, `{TERRAFORM_CONTEXT}`, `{REVIEW_TEMPLATE}`.
- `templates/pr-comment-with-terraform.md` / `pr-comment-without-terraform.md` — output comment structure; placeholders `{FILES_CHANGED}`, `{ADDITIONS}`, `{DELETIONS}`, `{TRUNCATION_NOTE}`, plus analytical placeholders Claude fills.

All substitution is plain `.replace()` — no templating engine.

## Rate Limiting

Tracked in S3 (`RATE_LIMIT_BUCKET`, per-repo JSON files keyed by ISO week). The limit is controlled by `WEEKLY_REVIEW_LIMIT` (default 2). The webhook Lambda checks this before enqueuing; requests over the limit get `202` with a message and are silently dropped.

## Idempotent Comments

`src/services/github_client.py:create_or_update_comment` finds an existing bot comment by an HTML marker embedded in the template. Subsequent runs on the same PR update rather than append. `github_commenter.py` also keeps an in-memory `_posted_comments` dict to block duplicate calls within a single execution.
