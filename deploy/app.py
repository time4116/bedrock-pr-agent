import os
import aws_cdk as cdk
from stacks.agentcore_stack import AgentCoreStack
from stacks.lambda_stack import LambdaStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("AWS_ACCOUNT", os.environ.get("CDK_DEFAULT_ACCOUNT")),
    region=os.environ.get("AWS_REGION", os.environ.get("CDK_DEFAULT_REGION", "us-east-1")),
)

stage = os.environ.get("STAGE", "dev")

config = {
    "stage": stage,
    "github_secret_name": os.environ.get("GITHUB_SECRET_NAME", "github-pr-agent/github"),
    "bedrock_model_id": os.environ.get(
        "BEDROCK_MODEL_ID",
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0",
    ),
    "allowed_repos": os.environ.get("ALLOWED_REPOS", ""),
    "terraform_validation_repos": os.environ.get("TERRAFORM_VALIDATION_REPOS", ""),
    "org_policy_check_enabled": os.environ.get("ORG_POLICY_CHECK_ENABLED", "false"),
    "log_level": os.environ.get("LOG_LEVEL", "info"),
}

agentcore_stack = AgentCoreStack(
    app,
    f"GitHubPrAgent-{stage}-AgentCore",
    config=config,
    env=env,
)

LambdaStack(
    app,
    f"GitHubPrAgent-{stage}-Lambda",
    config=config,
    agent_runtime_arn=agentcore_stack.agent_runtime_arn,
    env=env,
)

app.synth()
