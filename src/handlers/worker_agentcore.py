"""
Worker Lambda — receives SQS messages and invokes AgentCore Runtime.

All analysis logic lives in the AgentCore agent (pr_agent.py) and its tools.
This handler is intentionally thin: parse the event, forward to AgentCore.
"""
import os
import json
import uuid
import boto3
from botocore.config import Config
from typing import Dict, Any

from src.utils.logger import logger


# Extended timeout: AgentCore can take 10+ minutes for complex PRs
boto3_config = Config(
    read_timeout=900,
    connect_timeout=10,
    retries={'max_attempts': 0}
)

agentcore_client = boto3.client('bedrock-agentcore', config=boto3_config)

AGENT_ARN = os.environ.get('AGENT_ARN')
if not AGENT_ARN:
    raise ValueError('AGENT_ARN environment variable must be set')


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Process SQS messages by forwarding PR events to AgentCore Runtime.

    Args:
        event: SQS event containing GitHub webhook payloads
        context: Lambda context

    Returns:
        Processing status
    """
    logger.info('Worker Lambda invoked', {
        'records': len(event.get('Records', []))
    })

    for record in event.get('Records', []):
        try:
            message_body = json.loads(record['body'])
            event_name = message_body.get('event_name')
            payload = message_body.get('payload', {})

            if event_name != 'pull_request':
                logger.info('Skipping non-PR event', {'event_name': event_name})
                continue

            pull_request = payload.get('pull_request', {})
            repository = payload.get('repository', {})
            installation = payload.get('installation', {})

            _invoke_agent_for_pr(pull_request, repository, installation)

        except Exception as error:
            logger.error('Error processing SQS message', {
                'error': str(error),
                'message_id': record.get('messageId')
            })
            raise  # Trigger SQS retry / DLQ

    return {
        'statusCode': 200,
        'body': json.dumps({'status': 'processed'})
    }


def _invoke_agent_for_pr(
    pull_request: Dict[str, Any],
    repository: Dict[str, Any],
    installation: Dict[str, Any]
) -> None:
    """Invoke AgentCore Runtime for a specific PR."""
    pr_number = pull_request.get('number')
    repo_full_name = repository.get('full_name', '')

    logger.info('Invoking AgentCore for PR', {
        'repo': repo_full_name,
        'pr_number': pr_number
    })

    agentcore_payload = {
        'event_name': 'pull_request',
        'action': 'opened',
        'pull_request': pull_request,
        'repository': repository,
        'installation': installation,
        'config': {
            'allowed_repos': os.environ.get('ALLOWED_REPOS', ''),
            'terraform_validation_repos': os.environ.get('TERRAFORM_VALIDATION_REPOS', ''),
            'bedrock_model_id': os.environ.get('BEDROCK_MODEL_ID', ''),
            'github_secret_name': os.environ.get('GITHUB_SECRET_NAME', 'github-pr-agent/github'),
            'org_policy_check_enabled': os.environ.get('ORG_POLICY_CHECK_ENABLED', 'false'),
        }
    }

    try:
        response = agentcore_client.invoke_agent_runtime(
            agentRuntimeArn=AGENT_ARN,
            runtimeSessionId=str(uuid.uuid4()),
            payload=json.dumps(agentcore_payload).encode('utf-8'),
            qualifier='DEFAULT'
        )

        content_chunks = []
        for chunk in response.get('response', []):
            content_chunks.append(chunk.decode('utf-8'))

        result = json.loads(''.join(content_chunks))

        agent_response = result.get('agent_response', '')
        if not isinstance(agent_response, str):
            agent_response = str(agent_response)

        if result.get('status') == 'success':
            logger.info('PR processed successfully', {
                'pr_number': pr_number,
                'repo': repo_full_name,
                'response': agent_response[:200]
            })
        elif result.get('status') == 'skipped':
            logger.info('PR processing skipped', {
                'reason': result.get('reason'),
                'pr_number': pr_number
            })
        elif result.get('status') == 'error':
            logger.error('Agent returned error', {
                'error': result.get('error'),
                'pr_number': pr_number
            })

    except Exception as error:
        error_type = type(error).__name__
        error_message = str(error)

        if 'MaxTokens' in error_type or 'max_tokens' in error_message.lower():
            logger.error('AgentCore hit token limit', {
                'error_type': error_type,
                'pr_number': pr_number,
                'repo': repo_full_name,
                'recommendation': 'Consider switching to Nova Pro (300K context) or disabling policy checks for large PRs'
            })
        else:
            logger.error('AgentCore invocation failed', {
                'error_type': error_type,
                'error': error_message,
                'pr_number': pr_number,
                'repo': repo_full_name
            })
