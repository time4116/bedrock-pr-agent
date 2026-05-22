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
    "allowed_repos": os.environ.get("ALLOWED_REPOS", ""),
    "terraform_validation_repos": os.environ.get("TERRAFORM_VALIDATION_REPOS", ""),
    "log_level": os.environ.get("LOG_LEVEL", "info"),
    "weekly_review_limit": os.environ.get("WEEKLY_REVIEW_LIMIT", "2"),
}

agentcore_stack = AgentCoreStack(
    app,
    f"GitHubPrAgent-{stage}-AgentCore",
    config=config,
    env=env,
)

# Use the inference profile created in AgentCoreStack so the Lambda passes the
# correct ARN to the AgentCore container via the invocation payload.
config["bedrock_model_id"] = agentcore_stack.inference_profile_arn

LambdaStack(
    app,
    f"GitHubPrAgent-{stage}-Lambda",
    config=config,
    agent_runtime_arn=agentcore_stack.agent_runtime_arn,
    env=env,
)

app.synth()
