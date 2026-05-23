# End-to-End Setup

## Before you start

You need:
- AWS account with admin access (CDK bootstrap requires broad IAM permissions)
- AWS CLI configured (`aws configure`)
- Docker running (CDK builds and pushes the AgentCore container image)
- Node.js (for the CDK CLI: `npm install -g aws-cdk`)
- Python 3.11+

---

## 1. Create the GitHub App

This creates the App and stores its credentials (`app_id`, `webhook_secret`, `private_key`) in AWS Secrets Manager — both are needed before CDK deploys.

```bash
pip install -r requirements.txt

# Personal account
python scripts/create_github_app.py --store-secret

# GitHub org
python scripts/create_github_app.py --org my-org --store-secret
```

The script opens your browser to a pre-filled GitHub App creation page. Click **Create GitHub App**, and it captures the credentials automatically. The webhook URL is set to a placeholder — you'll update it in step 6.

> **Manual alternative:** GitHub → Settings → Developer settings → GitHub Apps → New GitHub App. Permissions: Issues (write), Pull requests / Contents / Actions / Metadata (read). Subscribe to `pull_request` events. Generate a private key. Store as a JSON secret in Secrets Manager at `github-pr-agent/github`:
> ```json
> {"app_id": "...", "webhook_secret": "...", "private_key": "..."}
> ```

---

## 2. Enable Bedrock model access

In the AWS Console: **Amazon Bedrock → Model access** → enable **Claude Sonnet 4**.

CDK creates a cross-region inference profile for it automatically — you don't need to copy any ARN.

---

## 3. Configure your environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

| Variable | What to set |
|----------|-------------|
| `AWS_ACCOUNT` | Your 12-digit AWS account ID |
| `AWS_REGION` | e.g. `us-east-1` |
| `ALLOWED_REPOS` | Comma-separated `owner/repo` list, or leave empty to allow all |

Leave `BEDROCK_MODEL_ID` blank — CDK sets it automatically.

---

## 4. Bootstrap CDK (first time only)

```bash
cd deploy
pip install -r requirements.txt
cdk bootstrap aws://YOUR_ACCOUNT_ID/YOUR_REGION
```

This creates the CDK bootstrap stack (`CDKToolkit`) including the S3 bucket for assets, ECR repository, and the `cdk-cfn-exec-role` that CloudFormation uses to create resources.

---

## 5. Create the deploy IAM role (GitHub Actions path)

Skip this step if you're deploying locally.

This creates an IAM role that GitHub Actions assumes via OIDC — no long-lived AWS credentials stored in GitHub. The role is scoped to what CDK needs: upload assets to S3/ECR and drive CloudFormation. Actual resource creation (Lambda, SQS, AgentCore, etc.) happens under the `cdk-cfn-exec-role` created by bootstrap, not this role.

```bash
# Personal account
python scripts/create_deploy_role.py --github-username YOUR_USERNAME

# GitHub org
python scripts/create_deploy_role.py --github-org YOUR_ORG
```

The script prints the role ARN. Add the following to **GitHub → Settings → Secrets and variables → Actions**:

| Type | Name | Value |
|------|------|-------|
| Secret | `AWS_DEPLOY_ROLE_ARN` | ARN printed above |
| Variable | `AWS_ACCOUNT` | Your 12-digit account ID |
| Variable | `AWS_REGION` | e.g. `us-east-1` |
| Variable | `STAGE` | `prod` |
| Variable | `ALLOWED_REPOS` | Comma-separated `owner/repo`, or leave empty |
| Variable | `TERRAFORM_VALIDATION_REPOS` | Comma-separated repos, or leave empty |
| Variable | `WEEKLY_REVIEW_LIMIT` | `2` |

`GITHUB_SECRET_NAME` and `LOG_LEVEL` fall back to sensible defaults.

---

## 6. Deploy

**Option A — GitHub Actions (recommended)**

Push to `main`. The `.github/workflows/deploy.yml` workflow runs `cdk deploy --all` automatically using the role from step 5.

**Option B — local**

```bash
# Export env vars from your .env first
export $(grep -v '^#' .env | xargs)

cd deploy
cdk deploy --all
```

CDK builds the AgentCore Docker image, pushes it to ECR, and creates all infrastructure. At the end it prints a `WebhookUrl` — copy it.

**What CDK creates:**

| Resource | Name |
|----------|------|
| AgentCore Runtime | `pr-agent-{stage}` |
| Bedrock inference profile | `pr-agent-{stage}-claude` (cross-region Claude Sonnet 4) |
| Webhook Lambda | `github-pr-agent-{stage}-webhook` |
| Worker Lambda | `github-pr-agent-{stage}-worker` |
| SQS queue + DLQ | `github-pr-agent-{stage}-pr-analysis` |
| API Gateway | `github-pr-agent-{stage}-api` |
| S3 bucket | `github-pr-agent-{stage}-rate-limits-{account}` |

**IAM roles CDK creates automatically:**

| Role | Trusted by | Purpose |
|------|-----------|---------|
| `github-pr-agent-{stage}-agentcore-role` | `bedrock-agentcore.amazonaws.com` | Lets the AgentCore container call Bedrock, pull from ECR, write CloudWatch logs, read Secrets Manager |
| `github-pr-agent-{stage}-webhook-role` | `lambda.amazonaws.com` | Lets the Webhook Lambda verify HMAC (Secrets Manager), send to SQS, update the S3 rate-limit counter |
| `github-pr-agent-{stage}-worker-role` | `lambda.amazonaws.com` | Lets the Worker Lambda invoke AgentCore and consume from SQS |

---

## 7. Point the GitHub App at the deployed webhook

In the GitHub App settings:

1. Set **Webhook URL** to the `WebhookUrl` output from CDK (e.g. `https://abc123.execute-api.us-east-1.amazonaws.com/prod/webhook`)
2. Set **Content type** to `application/json`
3. Set **Active** to checked — `create_github_app.py` creates it inactive; you must enable it here

---

## 8. Install the GitHub App on your repos

GitHub App settings → **Install App** → select your org or specific repositories.

Repos you install on must appear in `ALLOWED_REPOS`, or leave that variable empty to allow all. Open a pull request to verify — the agent should post a review comment within a few minutes.

