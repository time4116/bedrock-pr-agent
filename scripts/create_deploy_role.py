#!/usr/bin/env python3
"""
Create the GitHub Actions IAM role for OIDC-based CDK deployments.

Creates (or updates) a role that GitHub Actions assumes via OIDC — no
long-lived AWS credentials stored in GitHub. Also creates the GitHub
OIDC identity provider if it doesn't already exist in this account.

The role is scoped to what CDK actually needs from the caller:
  - Read CDK bootstrap SSM parameters
  - Upload Lambda zip and Docker image to the CDK bootstrap S3 bucket / ECR repo
  - Call CloudFormation to create/update the project stacks
  - Pass the CDK cfn-exec-role to CloudFormation

Actual resource creation (Lambda, SQS, S3, AgentCore, etc.) happens inside
CloudFormation under the cfn-exec-role created by `cdk bootstrap`, not this role.

Usage:
    python scripts/create_deploy_role.py --github-username YOUR_USERNAME
    python scripts/create_deploy_role.py --github-org YOUR_ORG
    python scripts/create_deploy_role.py --github-username YOUR_USERNAME --role-name my-role
"""
import argparse
import json

import boto3
from botocore.exceptions import ClientError

OIDC_URL = 'https://token.actions.githubusercontent.com'
OIDC_AUDIENCE = 'sts.amazonaws.com'
OIDC_THUMBPRINT = '6938fd4d98bab03faadb97b34396831e3780aea1'
REPO_NAME = 'bedrock-pr-agent'
DEFAULT_ROLE_NAME = 'github-pr-agent-deploy'
POLICY_NAME = 'github-pr-agent-deploy-policy'


def get_account_id(sts) -> str:
    return sts.get_caller_identity()['Account']


def ensure_oidc_provider(iam, account_id: str) -> None:
    provider_arn = (
        f'arn:aws:iam::{account_id}:oidc-provider/token.actions.githubusercontent.com'
    )
    try:
        iam.get_open_id_connect_provider(OpenIDConnectProviderArn=provider_arn)
        print('OIDC provider already exists.')
        return
    except ClientError as e:
        if e.response['Error']['Code'] != 'NoSuchEntity':
            raise

    print('Creating GitHub Actions OIDC provider...')
    iam.create_open_id_connect_provider(
        Url=OIDC_URL,
        ClientIDList=[OIDC_AUDIENCE],
        ThumbprintList=[OIDC_THUMBPRINT],
    )
    print('Done.')


def build_trust_policy(account_id: str, owner: str) -> dict:
    return {
        'Version': '2012-10-17',
        'Statement': [{
            'Effect': 'Allow',
            'Principal': {
                'Federated': (
                    f'arn:aws:iam::{account_id}:oidc-provider/'
                    'token.actions.githubusercontent.com'
                )
            },
            'Action': 'sts:AssumeRoleWithWebIdentity',
            'Condition': {
                'StringEquals': {
                    'token.actions.githubusercontent.com:aud': OIDC_AUDIENCE,
                },
                'StringLike': {
                    'token.actions.githubusercontent.com:sub': (
                        f'repo:{owner}/{REPO_NAME}:ref:refs/heads/main'
                    ),
                },
            },
        }],
    }


def build_deploy_policy(account_id: str, region: str) -> dict:
    """
    Scoped policy for CDK deploys from GitHub Actions.

    The deploy role uploads assets and drives CloudFormation. The cfn-exec-role
    (created by `cdk bootstrap`, scoped to this account) handles actual resource
    creation inside CloudFormation — that role is not touched here.

    A few actions legitimately require Resource: '*':
      - ecr:GetAuthorizationToken   (no resource concept, AWS requirement)
      - cloudformation:ValidateTemplate  (no stack ARN at validation time)
      - sts:GetCallerIdentity        (no resource concept)
      - ec2:DescribeAvailabilityZones (CDK reads AZs during synthesis)
    """
    return {
        'Version': '2012-10-17',
        'Statement': [
            {
                'Sid': 'CDKBootstrapRead',
                'Effect': 'Allow',
                'Action': 'ssm:GetParameter',
                'Resource': f'arn:aws:ssm:{region}:{account_id}:parameter/cdk-bootstrap/*',
            },
            {
                'Sid': 'CDKAssetsBucket',
                'Effect': 'Allow',
                'Action': [
                    's3:GetObject',
                    's3:PutObject',
                    's3:ListBucket',
                    's3:GetBucketLocation',
                    's3:AbortMultipartUpload',
                ],
                'Resource': [
                    'arn:aws:s3:::cdk-*',
                    'arn:aws:s3:::cdk-*/*',
                ],
            },
            {
                # GetAuthorizationToken cannot be scoped to a resource — AWS requirement
                'Sid': 'ECRAuth',
                'Effect': 'Allow',
                'Action': 'ecr:GetAuthorizationToken',
                'Resource': '*',
            },
            {
                'Sid': 'CDKAssetsECR',
                'Effect': 'Allow',
                'Action': [
                    'ecr:BatchCheckLayerAvailability',
                    'ecr:CompleteLayerUpload',
                    'ecr:CreateRepository',
                    'ecr:DescribeImages',
                    'ecr:DescribeRepositories',
                    'ecr:GetDownloadUrlForLayer',
                    'ecr:BatchGetImage',
                    'ecr:InitiateLayerUpload',
                    'ecr:PutImage',
                    'ecr:SetRepositoryPolicy',
                    'ecr:UploadLayerPart',
                ],
                'Resource': f'arn:aws:ecr:{region}:{account_id}:repository/cdk-*',
            },
            {
                'Sid': 'CloudFormationStacks',
                'Effect': 'Allow',
                'Action': [
                    'cloudformation:CreateChangeSet',
                    'cloudformation:CreateStack',
                    'cloudformation:DeleteChangeSet',
                    'cloudformation:DeleteStack',
                    'cloudformation:DescribeChangeSet',
                    'cloudformation:DescribeStackEvents',
                    'cloudformation:DescribeStackResources',
                    'cloudformation:DescribeStacks',
                    'cloudformation:ExecuteChangeSet',
                    'cloudformation:GetTemplate',
                    'cloudformation:GetTemplateSummary',
                    'cloudformation:ListChangeSets',
                    'cloudformation:ListStackResources',
                    'cloudformation:UpdateStack',
                ],
                'Resource': [
                    f'arn:aws:cloudformation:{region}:{account_id}:stack/GitHubPrAgent-*/*',
                    f'arn:aws:cloudformation:{region}:{account_id}:stack/CDKToolkit/*',
                ],
            },
            {
                # CDK reads CDKToolkit outputs and validates templates before knowing ARNs
                'Sid': 'CloudFormationGlobal',
                'Effect': 'Allow',
                'Action': [
                    'cloudformation:DescribeStacks',
                    'cloudformation:ListStacks',
                    'cloudformation:ValidateTemplate',
                ],
                'Resource': '*',
            },
            {
                # Pass the cfn-exec-role to CloudFormation so it can create resources
                'Sid': 'PassCFNExecRole',
                'Effect': 'Allow',
                'Action': 'iam:PassRole',
                'Resource': f'arn:aws:iam::{account_id}:role/cdk-*',
            },
            {
                'Sid': 'CDKSynthesis',
                'Effect': 'Allow',
                'Action': [
                    'sts:GetCallerIdentity',
                    'ec2:DescribeAvailabilityZones',
                ],
                'Resource': '*',
            },
        ],
    }


def create_or_update_role(iam, role_name: str, trust_policy: dict) -> str:
    """Create the role or update its trust policy if it already exists. Returns the ARN."""
    try:
        role = iam.get_role(RoleName=role_name)['Role']
        print('Role already exists — updating trust policy.')
        iam.update_assume_role_policy(
            RoleName=role_name,
            PolicyDocument=json.dumps(trust_policy),
        )
        return role['Arn']
    except ClientError as e:
        if e.response['Error']['Code'] != 'NoSuchEntity':
            raise

    print(f'Creating role: {role_name}')
    role = iam.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description='GitHub Actions OIDC deploy role for github-pr-agent',
    )['Role']
    return role['Arn']


def put_deploy_policy(iam, role_name: str, policy: dict) -> None:
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName=POLICY_NAME,
        PolicyDocument=json.dumps(policy),
    )
    print('Inline deploy policy attached.')


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--github-username', help='GitHub username (personal account)')
    group.add_argument('--github-org', help='GitHub organization name')
    parser.add_argument(
        '--role-name', default=DEFAULT_ROLE_NAME,
        help=f'IAM role name (default: {DEFAULT_ROLE_NAME})',
    )
    parser.add_argument('--region', help='AWS region (default: from profile/env)')
    args = parser.parse_args()

    session = boto3.Session(region_name=args.region)
    iam = session.client('iam')
    sts = session.client('sts')

    account_id = get_account_id(sts)
    region = session.region_name or 'us-east-1'
    owner = args.github_username or args.github_org

    print(f'Account : {account_id}')
    print(f'Region  : {region}')
    print(f'Owner   : {owner}/{REPO_NAME}')
    print(f'Role    : {args.role_name}\n')

    ensure_oidc_provider(iam, account_id)
    trust_policy = build_trust_policy(account_id, owner)
    role_arn = create_or_update_role(iam, args.role_name, trust_policy)
    deploy_policy = build_deploy_policy(account_id, region)
    put_deploy_policy(iam, args.role_name, deploy_policy)

    print(f'\nRole ARN: {role_arn}')
    print('\nAdd to GitHub → Settings → Secrets and variables → Actions:')
    print(f'  Secret  AWS_DEPLOY_ROLE_ARN = {role_arn}')


if __name__ == '__main__':
    main()
