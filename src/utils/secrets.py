"""
AWS Secrets Manager client with per-process caching.
"""
import os
import json
from functools import cache
from typing import Dict, Any
import boto3
from botocore.exceptions import ClientError

from src.utils.logger import logger


@cache
def get_secret(secret_name: str) -> Dict[str, Any]:
    """
    Retrieve a secret from AWS Secrets Manager (cached for the container lifetime).

    Args:
        secret_name: Name of the secret in Secrets Manager

    Returns:
        Dict containing secret key/value pairs

    Raises:
        Exception: If the secret cannot be retrieved
    """
    region = os.environ.get('AWS_REGION', 'us-east-1')

    logger.info('Fetching secret from Secrets Manager', {
        'secret_name': secret_name,
        'region': region
    })

    try:
        client = boto3.client('secretsmanager', region_name=region)
        response = client.get_secret_value(SecretId=secret_name)

        if 'SecretString' in response:
            secret = json.loads(response['SecretString'])
            logger.info('Successfully retrieved secret', {
                'secret_name': secret_name,
                'keys': list(secret.keys())
            })
            return secret

        raise Exception(f'Secret {secret_name} does not contain SecretString')

    except ClientError as error:
        error_code = error.response['Error']['Code']
        logger.error('Failed to retrieve secret', {
            'secret_name': secret_name,
            'error_code': error_code
        })
        raise Exception(f'Failed to retrieve secret {secret_name}: {error_code}') from error


@cache
def get_github_credentials() -> Dict[str, str]:
    """
    Get GitHub App credentials from Secrets Manager (cached).

    Returns:
        Dict with keys: app_id, webhook_secret, private_key
    """
    secret_name = os.environ.get('GITHUB_SECRET_NAME', 'github-pr-agent/github')
    secret = get_secret(secret_name)

    for key in ('app_id', 'webhook_secret', 'private_key'):
        if key not in secret:
            raise ValueError(f"Missing required key '{key}' in GitHub secret")

    return secret
