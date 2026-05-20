"""
AWS Lambda handler for GitHub webhook events.

Quickly validates the webhook signature and queues the event for the worker.
Responds to GitHub in <1 second to avoid delivery timeouts.
"""
import json
import os
import hmac
import hashlib
import boto3
from typing import Dict, Any

from src.utils.logger import logger
from src.utils.secrets import get_github_credentials
from src.utils.config import is_repo_allowed

sqs = boto3.client('sqs')
QUEUE_URL = os.environ.get('SQS_QUEUE_URL', '')


def verify_signature(payload: str, signature: str) -> bool:
    """Verify the HMAC-SHA256 webhook signature from GitHub."""
    creds = get_github_credentials()
    secret = creds['webhook_secret'].encode()
    expected = 'sha256=' + hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for GitHub webhook events.

    Validates the request, filters by repo allowlist, and queues pull_request
    events for the worker Lambda to process asynchronously.

    Args:
        event: API Gateway event
        context: Lambda context

    Returns:
        API Gateway response
    """
    try:
        logger.info('Received webhook event', {
            'path': event.get('path'),
            'method': event.get('httpMethod')
        })

        headers = event.get('headers', {})
        signature = headers.get('x-hub-signature-256') or headers.get('X-Hub-Signature-256')
        event_name = headers.get('x-github-event') or headers.get('X-GitHub-Event')

        if not signature or not event_name:
            logger.warning('Missing required headers')
            return {'statusCode': 400, 'body': json.dumps({'error': 'Missing required headers'})}

        body = event.get('body', '{}')

        if not verify_signature(body, signature):
            logger.error('Invalid webhook signature')
            return {'statusCode': 401, 'body': json.dumps({'error': 'Invalid signature'})}

        payload = json.loads(body)

        # Only process pull_request events
        if event_name != 'pull_request':
            logger.info('Ignoring non-PR event', {'event_name': event_name})
            return {'statusCode': 200, 'body': json.dumps({'message': 'Event ignored'})}

        action = payload.get('action')
        if action not in ('opened', 'synchronize', 'edited'):
            logger.info('Ignoring PR action', {'action': action})
            return {'statusCode': 200, 'body': json.dumps({'message': 'Action ignored'})}

        repository = payload.get('repository', {})
        repo_full_name = repository.get('full_name', '')

        if not is_repo_allowed(repo_full_name):
            logger.info('Ignoring event from non-allowed repo', {'repo': repo_full_name})
            return {'statusCode': 200, 'body': json.dumps({'message': 'Repository not in allowed list'})}

        pr_number = payload.get('pull_request', {}).get('number')

        logger.info('Queueing PR event for processing', {
            'repo': repo_full_name,
            'pr_number': pr_number,
            'action': action
        })

        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({'event_name': event_name, 'payload': payload}),
            MessageAttributes={
                'repo': {'StringValue': repo_full_name, 'DataType': 'String'},
                'event_type': {'StringValue': event_name, 'DataType': 'String'},
                'pr_number': {'StringValue': str(pr_number), 'DataType': 'Number'}
            }
        )

        logger.info('Job queued successfully', {'repo': repo_full_name, 'pr_number': pr_number})

        return {
            'statusCode': 202,
            'body': json.dumps({'message': 'pull_request event queued', 'pr_number': pr_number})
        }

    except Exception as error:
        logger.error('Error processing webhook', {'error': str(error)})
        return {'statusCode': 500, 'body': json.dumps({'error': 'Internal server error'})}
