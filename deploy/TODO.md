# Deployment — CDK Implementation

CDK implementation is complete. Both the AgentCore Runtime and Lambda infrastructure
are deployed in a single command.

## Deploy

```bash
cd deploy
pip install -r requirements.txt
cdk deploy --all
```

Set environment variables before deploying (see `.env.example`):

```bash
export AWS_ACCOUNT=123456789012
export AWS_REGION=us-east-1
export STAGE=dev
export GITHUB_SECRET_NAME=github-pr-agent/github
export BEDROCK_MODEL_ID=arn:aws:bedrock:us-east-1:...
export ALLOWED_REPOS=your-org/your-repo
```

## File structure

```
deploy/
├── app.py                      # CDK app entrypoint
├── cdk.json
├── requirements.txt
└── stacks/
    ├── __init__.py
    ├── agentcore_stack.py      # AgentCore Runtime + IAM execution role + ECR image
    └── lambda_stack.py         # Lambda + SQS + API Gateway
```

## Stacks

**GitHubPrAgent-{stage}-AgentCore**
- Builds and pushes Docker image from `.bedrock_agentcore/pr_agent/Dockerfile` via `DockerImageAsset`
- Creates IAM execution role matching `scripts/create_agentcore_role.py` exactly
- Creates `AWS::BedrockAgentCore::Runtime` via `CfnRuntime` (L1 construct)
- Exports `AgentRuntimeArn`

**GitHubPrAgent-{stage}-Lambda**
- Reads `AgentRuntimeArn` from AgentCore stack output and scopes worker IAM to it
- WebhookHandler (Python 3.12, 10s timeout, 512 MB)
- WorkerHandler (Python 3.12, 900s timeout, 512 MB, max concurrency 10)
- SQS queue (visibility 1200s, retention 24h, DLQ max-receive 3, DLQ retention 14d)
- REST API with POST /webhook → WebhookHandler
- CloudWatch log groups with 30-day retention for both Lambdas

## Notes

- `aws_cdk.aws_bedrock_agentcore_alpha` is an alpha module — its API may change between
  CDK versions. `CfnRuntime` (L1) is used here for stability; migrate to L2 `Runtime`
  once the construct stabilises.
- `samconfig.toml` and `template.yaml` are superseded by this CDK app but are kept for
  reference.
- CDK requires Node.js for the CLI: `npm install -g aws-cdk`
