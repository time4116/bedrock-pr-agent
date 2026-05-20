import os
from typing import Any
import aws_cdk as cdk
from aws_cdk import (
    Duration,
    Stack,
    CfnOutput,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_event_sources,
    aws_logs as logs,
    aws_sqs as sqs,
    aws_apigateway as apigw,
)
from constructs import Construct


class LambdaStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: dict[str, Any],
        agent_runtime_arn: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        stage = config["stage"]
        region = self.region
        account = self.account

        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )

        dlq = sqs.Queue(
            self,
            "PRAnalysisDeadLetterQueue",
            queue_name=f"github-pr-agent-{stage}-pr-analysis-dlq",
            retention_period=Duration.days(14),
        )

        queue = sqs.Queue(
            self,
            "PRAnalysisQueue",
            queue_name=f"github-pr-agent-{stage}-pr-analysis",
            visibility_timeout=Duration.seconds(1200),
            retention_period=Duration.seconds(86400),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=dlq,
            ),
        )

        shared_env = {
            "GITHUB_SECRET_NAME": config["github_secret_name"],
            "BEDROCK_MODEL_ID": config["bedrock_model_id"],
            "ALLOWED_REPOS": config["allowed_repos"],
            "TERRAFORM_VALIDATION_REPOS": config["terraform_validation_repos"],
            "ORG_POLICY_CHECK_ENABLED": config["org_policy_check_enabled"],
            "AGENT_ARN": agent_runtime_arn,
            "STAGE": stage,
            "LOG_LEVEL": config["log_level"],
            "SQS_QUEUE_URL": queue.queue_url,
        }

        webhook_role = iam.Role(
            self,
            "WebhookExecutionRole",
            role_name=f"github-pr-agent-{stage}-webhook-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        webhook_role.add_to_policy(
            iam.PolicyStatement(
                sid="GitHubSecretAccess",
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{region}:{account}:secret:github-pr-agent/*"
                ],
            )
        )

        webhook_role.add_to_policy(
            iam.PolicyStatement(
                sid="WebhookKmsDecrypt",
                actions=["kms:Decrypt"],
                resources=[f"arn:aws:kms:{region}:{account}:key/*"],
                conditions={
                    "StringEquals": {
                        "kms:ViaService": f"secretsmanager.{region}.amazonaws.com"
                    }
                },
            )
        )

        webhook_role.add_to_policy(
            iam.PolicyStatement(
                sid="SQSSendAccess",
                actions=["sqs:SendMessage"],
                resources=[queue.queue_arn],
            )
        )

        worker_role = iam.Role(
            self,
            "WorkerExecutionRole",
            role_name=f"github-pr-agent-{stage}-worker-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        worker_role.add_to_policy(
            iam.PolicyStatement(
                sid="AgentCoreInvokeAccess",
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[agent_runtime_arn],
            )
        )

        worker_role.add_to_policy(
            iam.PolicyStatement(
                sid="WorkerSecretsManagerAccess",
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{region}:{account}:secret:github-pr-agent/*"
                ],
            )
        )

        worker_role.add_to_policy(
            iam.PolicyStatement(
                sid="WorkerKmsDecrypt",
                actions=["kms:Decrypt", "kms:DescribeKey"],
                resources=[f"arn:aws:kms:{region}:{account}:key/*"],
                conditions={
                    "StringEquals": {
                        "kms:ViaService": f"secretsmanager.{region}.amazonaws.com"
                    }
                },
            )
        )

        worker_role.add_to_policy(
            iam.PolicyStatement(
                sid="SQSReceiveAccess",
                actions=[
                    "sqs:ReceiveMessage",
                    "sqs:DeleteMessage",
                    "sqs:GetQueueAttributes",
                ],
                resources=[queue.queue_arn, dlq.queue_arn],
            )
        )

        webhook_log_group = logs.LogGroup(
            self,
            "WebhookLogGroup",
            log_group_name=f"/aws/lambda/github-pr-agent-{stage}-webhook",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        worker_log_group = logs.LogGroup(
            self,
            "WorkerLogGroup",
            log_group_name=f"/aws/lambda/github-pr-agent-{stage}-worker",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        webhook_fn = lambda_.Function(
            self,
            "WebhookFunction",
            function_name=f"github-pr-agent-{stage}-webhook",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset(repo_root),
            handler="src/handlers/webhook.handler",
            timeout=Duration.seconds(10),
            memory_size=512,
            role=webhook_role,
            environment=shared_env,
            log_group=webhook_log_group,
        )

        worker_fn = lambda_.Function(
            self,
            "WorkerFunction",
            function_name=f"github-pr-agent-{stage}-worker",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset(repo_root),
            handler="src/handlers/worker_agentcore.handler",
            timeout=Duration.seconds(900),
            memory_size=512,
            reserved_concurrent_executions=10,
            role=worker_role,
            environment=shared_env,
            log_group=worker_log_group,
        )

        worker_fn.add_event_source(
            lambda_event_sources.SqsEventSource(
                queue,
                batch_size=1,
                enabled=True,
            )
        )

        api = apigw.RestApi(
            self,
            "WebhookApi",
            rest_api_name=f"github-pr-agent-{stage}-api",
            deploy_options=apigw.StageOptions(stage_name=stage),
            endpoint_configuration=apigw.EndpointConfiguration(
                types=[apigw.EndpointType.REGIONAL],
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_methods=["POST"],
                allow_headers=[
                    "Content-Type",
                    "X-GitHub-Event",
                    "X-Hub-Signature-256",
                ],
                allow_origins=["*"],
            ),
        )

        webhook_resource = api.root.add_resource("webhook")
        webhook_resource.add_method(
            "POST",
            apigw.LambdaIntegration(webhook_fn),
        )

        CfnOutput(
            self,
            "WebhookUrl",
            value=f"https://{api.rest_api_id}.execute-api.{region}.amazonaws.com/{stage}/webhook",
            export_name=f"GitHubPrAgent-{stage}-WebhookUrl",
        )

        CfnOutput(
            self,
            "WebhookFunctionArn",
            value=webhook_fn.function_arn,
            export_name=f"GitHubPrAgent-{stage}-WebhookFunctionArn",
        )

        CfnOutput(
            self,
            "WorkerFunctionArn",
            value=worker_fn.function_arn,
            export_name=f"GitHubPrAgent-{stage}-WorkerFunctionArn",
        )

        CfnOutput(
            self,
            "QueueUrl",
            value=queue.queue_url,
            export_name=f"GitHubPrAgent-{stage}-QueueUrl",
        )

        CfnOutput(
            self,
            "DeadLetterQueueUrl",
            value=dlq.queue_url,
            export_name=f"GitHubPrAgent-{stage}-DeadLetterQueueUrl",
        )
