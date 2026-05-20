# Deployment — CDK Consolidation (TODO)

## Current state (two-step manual process)

```bash
# Step 1 — Build and deploy AgentCore Runtime
agentcore configure -e pr_agent.py -r us-east-1
agentcore launch --local-build

# Step 2 — Deploy Lambda infrastructure (separate)
sam build --use-container
sam deploy --guided
```

Step 1 uses the `agentcore` CLI to build and push the Docker image to ECR and
create/update the AgentCore Runtime. Step 2 deploys Lambda + SQS + API Gateway via SAM.

## Goal: single `cdk deploy` command

Replace both steps with a Python CDK app. **Native CDK and CloudFormation support for
AgentCore Runtime is available** as of CDK v2.221.0 — no custom resource needed.

1. **Builds and pushes the Docker image** using `aws_cdk.aws_ecr_assets.DockerImageAsset`
   - Builds from `.bedrock_agentcore/pr_agent/Dockerfile`
   - CDK handles ECR repository creation and image push automatically

2. **Creates the AgentCore Runtime** using `aws_cdk.aws_bedrock_agentcore_alpha`
   - Native L2 construct (CDK v2.221.0+): `aws_bedrock_agentcore_alpha.Runtime`
   - CloudFormation resource type: `AWS::BedrockAgentCore::Runtime` (released Sept 2025)
   - No custom resource Lambda required

3. **Deploys Lambda + SQS + API Gateway** using native CDK constructs
   - Replace `template.yaml` with a CDK stack
   - `aws_cdk.aws_lambda.Function` with `AGENT_ARN` env var pointing to step 2's ARN
   - `aws_cdk.aws_sqs.Queue` with DLQ
   - `aws_cdk.aws_apigateway.RestApi` for GitHub webhook endpoint
   - `aws_cdk.aws_lambda_event_sources.SqsEventSource` wiring Lambda to SQS

4. **Wires Secrets Manager** permissions to Lambda execution role

### File structure

```
deploy/
├── app.py              # CDK app entrypoint
├── stacks/
│   ├── agentcore_stack.py   # AgentCore Runtime (aws_bedrock_agentcore_alpha.Runtime)
│   └── lambda_stack.py      # Lambda + SQS + API Gateway
├── requirements.txt    # aws-cdk-lib, aws-cdk.aws-bedrock-agentcore-alpha, constructs
└── cdk.json
```

### Deploy command

```bash
cd deploy
pip install -r requirements.txt
cdk deploy --all
```

### Notes

- CDK requires Node.js for the CDK CLI (`npm install -g aws-cdk`)
- `aws_bedrock_agentcore_alpha` is an alpha module — API may change between CDK versions
- `bedrock-agentcore-starter-toolkit` (the old PyPI package) is now legacy; use CDK directly
