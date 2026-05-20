#!/usr/bin/env python3
"""
Create IAM role for AgentCore Runtime with proper permissions.

This script creates a role that AgentCore can assume with permissions for:
- Bedrock model invocation (Claude)
- Secrets Manager access (GitHub, Jira, Jenkins)
- KMS decryption for secrets
- CloudWatch Logs

Usage:
    python scripts/create_agentcore_role.py --stage dev
    python scripts/create_agentcore_role.py --stage prod --region us-west-2
"""
import argparse
import boto3
import json
import sys
from typing import Dict, Any


def create_agentcore_role(stage: str, region: str, account_id: str) -> str:
    """
    Create IAM role for AgentCore Runtime.
    
    Args:
        stage: Deployment stage (dev, prod)
        region: AWS region
        account_id: AWS account ID
        
    Returns:
        Role ARN
    """
    iam = boto3.client('iam', region_name=region)
    role_name = f"github-pr-agent-{stage}-agentcore-role"
    
    # Trust policy - Allow Bedrock AgentCore service to assume this role
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "bedrock-agentcore.amazonaws.com"
                },
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {
                        "aws:SourceAccount": account_id
                    }
                }
            }
        ]
    }
    
    # Check if role exists
    try:
        response = iam.get_role(RoleName=role_name)
        print(f"✅ Role already exists: {role_name}")
        role_arn = response['Role']['Arn']
    except iam.exceptions.NoSuchEntityException:
        # Create role
        print(f"📝 Creating role: {role_name}")
        response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description=f"AgentCore Runtime execution role for {stage} environment",
            Tags=[
                {'Key': 'Environment', 'Value': stage},
                {'Key': 'Application', 'Value': 'github-pr-agent'},
                {'Key': 'ManagedBy', 'Value': 'script'}
            ]
        )
        role_arn = response['Role']['Arn']
        print(f"✅ Role created: {role_arn}")
    
    # Secrets Manager access policy (custom secrets for GitHub, Jira, Jenkins)
    secrets_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:GetSecretValue"
                ],
                "Resource": [
                    f"arn:aws:secretsmanager:{region}:{account_id}:secret:github-pr-agent/*"
                ]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "kms:Decrypt",
                    "kms:DescribeKey"
                ],
                "Resource": f"arn:aws:kms:{region}:{account_id}:key/*",
                "Condition": {
                    "StringEquals": {
                        "kms:ViaService": f"secretsmanager.{region}.amazonaws.com"
                    }
                }
            }
        ]
    }
    
    # Full AgentCore Runtime policy (ECR, Logs, Bedrock, XRay, etc.)
    agentcore_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ECRImageAccess",
                "Effect": "Allow",
                "Action": [
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer"
                ],
                "Resource": [
                    f"arn:aws:ecr:{region}:{account_id}:repository/*"
                ]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:DescribeLogStreams",
                    "logs:CreateLogGroup"
                ],
                "Resource": [
                    f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"
                ]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:DescribeLogGroups"
                ],
                "Resource": [
                    f"arn:aws:logs:{region}:{account_id}:log-group:*"
                ]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                "Resource": [
                    f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"
                ]
            },
            {
                "Sid": "ECRTokenAccess",
                "Effect": "Allow",
                "Action": [
                    "ecr:GetAuthorizationToken"
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets"
                ],
                "Resource": [
                    "*"
                ]
            },
            {
                "Effect": "Allow",
                "Resource": "*",
                "Action": "cloudwatch:PutMetricData",
                "Condition": {
                    "StringEquals": {
                        "cloudwatch:namespace": "bedrock-agentcore"
                    }
                }
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:PutDeliverySource",
                    "logs:PutDeliveryDestination",
                    "logs:CreateDelivery",
                    "logs:GetDeliverySource",
                    "logs:DeleteDeliverySource",
                    "logs:DeleteDeliveryDestination"
                ],
                "Resource": "*"
            },
            {
                "Sid": "BedrockAgentCoreRuntime",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:InvokeAgentRuntime",
                    "bedrock-agentcore:InvokeAgentRuntimeForUser"
                ],
                "Resource": [
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/*"
                ]
            },
            {
                "Sid": "BedrockAgentCoreMemoryCreateMemory",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:CreateMemory"
                ],
                "Resource": "*"
            },
            {
                "Sid": "BedrockAgentCoreMemory",
                "Effect": "Allow",
                "Action": [
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
                    "bedrock-agentcore:RetrieveMemoryRecords"
                ],
                "Resource": [
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:memory/*"
                ]
            },
            {
                "Sid": "BedrockAgentCoreIdentityGetResourceApiKey",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:GetResourceApiKey"
                ],
                "Resource": [
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:token-vault/default",
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:token-vault/default/apikeycredentialprovider/*",
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/default/workload-identity/*"
                ]
            },
            {
                "Sid": "BedrockAgentCoreIdentityGetCredentialProviderClientSecret",
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:GetSecretValue"
                ],
                "Resource": [
                    f"arn:aws:secretsmanager:{region}:{account_id}:secret:bedrock-agentcore-identity!default/oauth2/*",
                    f"arn:aws:secretsmanager:{region}:{account_id}:secret:bedrock-agentcore-identity!default/apikey/*"
                ]
            },
            {
                "Sid": "BedrockAgentCoreIdentityGetResourceOauth2Token",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:GetResourceOauth2Token"
                ],
                "Resource": [
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:token-vault/default",
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:token-vault/default/oauth2credentialprovider/*",
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/default/workload-identity/pr_agent-*"
                ]
            },
            {
                "Sid": "BedrockModelInvocation",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:ApplyGuardrail"
                ],
                "Resource": [
                    "arn:aws:bedrock:*::foundation-model/*",
                    "arn:aws:bedrock:*:*:inference-profile/*",
                    f"arn:aws:bedrock:{region}:{account_id}:*"
                ]
            },
            {
                "Sid": "BedrockKnowledgeBaseAccess",
                "Effect": "Allow",
                "Action": [
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate"
                ],
                "Resource": [
                    f"arn:aws:bedrock:{region}:{account_id}:knowledge-base/*"
                ]
            },
            {
                "Sid": "MarketplaceSubscribeOnFirstCall",
                "Effect": "Allow",
                "Action": [
                    "aws-marketplace:ViewSubscriptions",
                    "aws-marketplace:Subscribe"
                ],
                "Resource": "*",
                "Condition": {
                    "StringEquals": {
                        "aws:CalledViaLast": "bedrock.amazonaws.com"
                    }
                }
            },
            {
                "Sid": "BedrockAgentCoreCodeInterpreter",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:CreateCodeInterpreter",
                    "bedrock-agentcore:StartCodeInterpreterSession",
                    "bedrock-agentcore:InvokeCodeInterpreter",
                    "bedrock-agentcore:StopCodeInterpreterSession",
                    "bedrock-agentcore:DeleteCodeInterpreter",
                    "bedrock-agentcore:ListCodeInterpreters",
                    "bedrock-agentcore:GetCodeInterpreter",
                    "bedrock-agentcore:GetCodeInterpreterSession",
                    "bedrock-agentcore:ListCodeInterpreterSessions"
                ],
                "Resource": [
                    f"arn:aws:bedrock-agentcore:{region}:aws:code-interpreter/*",
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:code-interpreter/*",
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:code-interpreter-custom/*"
                ]
            },
            {
                "Sid": "BedrockAgentCoreIdentity",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:CreateWorkloadIdentity",
                    "bedrock-agentcore:GetWorkloadAccessTokenForUserId"
                ],
                "Resource": [
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/default/workload-identity/*"
                ]
            },
            {
                "Sid": "AwsJwtFederation",
                "Effect": "Allow",
                "Action": "sts:GetWebIdentityToken",
                "Resource": "*"
            }
        ]
    }
    
    # Attach policies
    policies = [
        ('SecretsManagerAccess', secrets_policy),
        ('AgentCoreRuntimeAccess', agentcore_policy)
    ]
    
    for policy_name, policy_doc in policies:
        full_policy_name = f"{role_name}-{policy_name}"
        try:
            iam.put_role_policy(
                RoleName=role_name,
                PolicyName=full_policy_name,
                PolicyDocument=json.dumps(policy_doc)
            )
            print(f"✅ Attached inline policy: {full_policy_name}")
        except Exception as e:
            print(f"⚠️  Failed to attach policy {full_policy_name}: {e}")
    
    return role_arn


def main():
    parser = argparse.ArgumentParser(
        description='Create IAM role for AgentCore Runtime with proper permissions'
    )
    parser.add_argument(
        '--stage',
        default='dev',
        choices=['dev', 'prod'],
        help='Deployment stage (default: dev)'
    )
    parser.add_argument(
        '--region',
        default='us-east-1',
        help='AWS region (default: us-east-1)'
    )
    parser.add_argument(
        '--profile',
        help='AWS profile name (optional)'
    )
    
    args = parser.parse_args()
    
    # Create boto3 session with optional profile
    session_kwargs = {'region_name': args.region}
    if args.profile:
        session_kwargs['profile_name'] = args.profile
    
    session = boto3.Session(**session_kwargs)
    sts = session.client('sts')
    
    # Get account ID
    try:
        identity = sts.get_caller_identity()
        account_id = identity['Account']
        print(f"🔐 AWS Account: {account_id}")
        print(f"📍 Region: {args.region}")
        print(f"🏷️  Stage: {args.stage}\n")
    except Exception as e:
        print(f"❌ Failed to get AWS account identity: {e}")
        print("💡 Tip: Configure AWS credentials with 'aws configure' or set AWS_PROFILE")
        sys.exit(1)
    
    # Create role
    try:
        role_arn = create_agentcore_role(args.stage, args.region, account_id)
        print(f"\n✨ AgentCore role ready!")
        print(f"\n📋 Use this ARN when deploying AgentCore:")
        print(f"   {role_arn}")
        print(f"\n📝 Command to deploy AgentCore with this role:")
        print(f"   agentcore configure -e pr_agent.py -r {args.region}")
        print(f"   agentcore launch --execution-role-arn {role_arn}")
    except Exception as e:
        print(f"\n❌ Failed to create role: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
