import os
from typing import Any
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    CfnOutput,
    aws_ecr_assets as ecr_assets,
    aws_iam as iam,
)
from aws_cdk import aws_bedrock_agentcore_alpha as agentcore
from constructs import Construct


class AgentCoreStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        stage = config["stage"]
        region = self.region
        account = self.account

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        image_asset = ecr_assets.DockerImageAsset(
            self,
            "AgentCoreImage",
            directory=repo_root,
            file=os.path.join("docker", "Dockerfile"),
            platform=ecr_assets.Platform.LINUX_ARM64,
            exclude=[
                "deploy/cdk.out",
                ".git",
                "**/__pycache__",
                "**/*.pyc",
                "**/*.egg-info",
                ".venv",
                "node_modules",
            ],
        )

        execution_role = iam.Role(
            self,
            "AgentCoreExecutionRole",
            role_name=f"github-pr-agent-{stage}-agentcore-role",
            description=f"AgentCore Runtime execution role for {stage} environment",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": account},
                },
            ),
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SecretsManagerAccess",
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{region}:{account}:secret:github-pr-agent/*",
                    f"arn:aws:secretsmanager:{region}:{account}:secret:bedrock-agentcore-identity!default/oauth2/*",
                    f"arn:aws:secretsmanager:{region}:{account}:secret:bedrock-agentcore-identity!default/apikey/*",
                ],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="KmsDecrypt",
                actions=["kms:Decrypt", "kms:DescribeKey"],
                resources=[f"arn:aws:kms:{region}:{account}:key/*"],
                conditions={
                    "StringEquals": {
                        "kms:ViaService": f"secretsmanager.{region}.amazonaws.com"
                    }
                },
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="ECRImageAccess",
                actions=["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                resources=[f"arn:aws:ecr:{region}:{account}:repository/*"],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="ECRTokenAccess",
                actions=["ecr:GetAuthorizationToken"],
                resources=["*"],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="LogsAgentCoreStreams",
                actions=["logs:DescribeLogStreams", "logs:CreateLogGroup"],
                resources=[
                    f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*"
                ],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="LogsDescribeAll",
                actions=["logs:DescribeLogGroups"],
                resources=[f"arn:aws:logs:{region}:{account}:log-group:*"],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="LogsAgentCoreEvents",
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[
                    f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"
                ],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="LogsDelivery",
                actions=[
                    "logs:CreateLogGroup",
                    "logs:PutDeliverySource",
                    "logs:PutDeliveryDestination",
                    "logs:CreateDelivery",
                    "logs:GetDeliverySource",
                    "logs:DeleteDeliverySource",
                    "logs:DeleteDeliveryDestination",
                ],
                resources=["*"],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="XRay",
                actions=[
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                resources=["*"],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}},
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockAgentCoreRuntime",
                actions=[
                    "bedrock-agentcore:InvokeAgentRuntime",
                    "bedrock-agentcore:InvokeAgentRuntimeForUser",
                ],
                resources=[
                    f"arn:aws:bedrock-agentcore:{region}:{account}:runtime/*"
                ],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockAgentCoreMemoryCreateMemory",
                actions=["bedrock-agentcore:CreateMemory"],
                resources=["*"],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockAgentCoreMemory",
                actions=[
                    "bedrock-agentcore:CreateEvent",
                    "bedrock-agentcore:GetEvent",
                    "bedrock-agentcore:GetMemory",
                    "bedrock-agentcore:GetMemoryRecord",
                    "bedrock-agentcore:ListActors",
                    "bedrock-agentcore:ListEvents",
                    "bedrock-agentcore:ListMemoryRecords",
                    "bedrock-agentcore:ListSessions",
                    "bedrock-agentcore:DeleteEvent",
                    "bedrock-agentcore:DeleteMemoryRecord",
                    "bedrock-agentcore:RetrieveMemoryRecords",
                ],
                resources=[
                    f"arn:aws:bedrock-agentcore:{region}:{account}:memory/*"
                ],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockAgentCoreIdentityGetResourceApiKey",
                actions=["bedrock-agentcore:GetResourceApiKey"],
                resources=[
                    f"arn:aws:bedrock-agentcore:{region}:{account}:token-vault/default",
                    f"arn:aws:bedrock-agentcore:{region}:{account}:token-vault/default/apikeycredentialprovider/*",
                    f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default/workload-identity/*",
                ],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockAgentCoreIdentityGetResourceOauth2Token",
                actions=["bedrock-agentcore:GetResourceOauth2Token"],
                resources=[
                    f"arn:aws:bedrock-agentcore:{region}:{account}:token-vault/default",
                    f"arn:aws:bedrock-agentcore:{region}:{account}:token-vault/default/oauth2credentialprovider/*",
                    f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default/workload-identity/pr_agent-*",
                ],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockModelInvocation",
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:ApplyGuardrail",
                ],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/*",
                    "arn:aws:bedrock:*:*:inference-profile/*",
                    f"arn:aws:bedrock:{region}:{account}:*",
                ],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockKnowledgeBaseAccess",
                actions=["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"],
                resources=[
                    f"arn:aws:bedrock:{region}:{account}:knowledge-base/*"
                ],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="MarketplaceSubscribeOnFirstCall",
                actions=[
                    "aws-marketplace:ViewSubscriptions",
                    "aws-marketplace:Subscribe",
                ],
                resources=["*"],
                conditions={
                    "StringEquals": {"aws:CalledViaLast": "bedrock.amazonaws.com"}
                },
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockAgentCoreCodeInterpreter",
                actions=[
                    "bedrock-agentcore:CreateCodeInterpreter",
                    "bedrock-agentcore:StartCodeInterpreterSession",
                    "bedrock-agentcore:InvokeCodeInterpreter",
                    "bedrock-agentcore:StopCodeInterpreterSession",
                    "bedrock-agentcore:DeleteCodeInterpreter",
                    "bedrock-agentcore:ListCodeInterpreters",
                    "bedrock-agentcore:GetCodeInterpreter",
                    "bedrock-agentcore:GetCodeInterpreterSession",
                    "bedrock-agentcore:ListCodeInterpreterSessions",
                ],
                resources=[
                    f"arn:aws:bedrock-agentcore:{region}:aws:code-interpreter/*",
                    f"arn:aws:bedrock-agentcore:{region}:{account}:code-interpreter/*",
                    f"arn:aws:bedrock-agentcore:{region}:{account}:code-interpreter-custom/*",
                ],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockAgentCoreIdentity",
                actions=[
                    "bedrock-agentcore:CreateWorkloadIdentity",
                    "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                ],
                resources=[
                    f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default/workload-identity/*",
                ],
            )
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="AwsJwtFederation",
                actions=["sts:GetWebIdentityToken"],
                resources=["*"],
            )
        )

        self.inference_profile_arn = "us.anthropic.claude-sonnet-4-20250514-v1:0"

        runtime = agentcore.Runtime(
            self,
            "AgentCoreRuntime",
            agent_runtime_artifact=agentcore.AgentRuntimeArtifact.from_image_uri(
                image_asset.image_uri
            ),
            runtime_name=f"pr_agent_{stage}",
            description=f"GitHub PR Agent AgentCore Runtime ({stage})",
            execution_role=execution_role,
        )

        self.agent_runtime_arn = runtime.agent_runtime_arn

        CfnOutput(
            self,
            "AgentRuntimeArn",
            value=self.agent_runtime_arn,
            export_name=f"GitHubPrAgent-{stage}-AgentRuntimeArn",
        )
