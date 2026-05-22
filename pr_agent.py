"""
Amazon Bedrock AgentCore entrypoint for PR analysis.

The LangGraph graph lives in src/agent/graph.py and is importable independently
of AgentCore — use scripts/run_local.py to run against a PR without the GitHub
App / webhook infrastructure (AWS Bedrock credentials still required).
"""
import os
from typing import Dict, Any

from bedrock_agentcore import BedrockAgentCoreApp

from src.agent.graph import build_graph
from src.agent.state import PRReviewState
from src.utils.config import is_repo_allowed, is_repo_terraform_enabled
from src.utils.logger import logger

app = BedrockAgentCoreApp()
_graph = build_graph()

logger.info('AgentCore PR Agent initialized', {
    'model': os.getenv('BEDROCK_MODEL_ID', 'us.anthropic.claude-sonnet-4-20250514-v1:0'),
})


@app.entrypoint
def invoke(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entrypoint called by AgentCore Runtime.

    Expected payload (forwarded from worker Lambda via SQS):
    {
        "event_name": "pull_request",
        "action": "opened" | "synchronize" | "edited",
        "pull_request": {...},
        "repository": {...},
        "installation": {...},
        "config": {...}
    }
    """
    pull_request = payload.get('pull_request', {})
    repository = payload.get('repository', {})
    installation = payload.get('installation', {})

    pr_number = pull_request.get('number')
    repo_full_name = repository.get('full_name', '')
    installation_id = installation.get('id')

    logger.set_pr_context(
        pr_number=pr_number,
        repo=repo_full_name,
        branch=pull_request.get('head', {}).get('ref', ''),
        installation_id=installation_id,
    )

    try:
        for key, value in payload.get('config', {}).items():
            if value:
                os.environ[key.upper()] = str(value)

        if payload.get('event_name') != 'pull_request':
            return {'status': 'skipped', 'reason': f'Not a PR event: {payload.get("event_name")}'}

        action = payload.get('action')
        if action not in ('opened', 'synchronize', 'edited', 'status_update'):
            return {'status': 'skipped', 'reason': f'Action not supported: {action}'}

        if not is_repo_allowed(repo_full_name):
            return {'status': 'skipped', 'reason': f'Repository not in allowed list: {repo_full_name}'}

        initial_state: PRReviewState = {
            'installation_id': installation_id,
            'owner': repository.get('owner', {}).get('login', ''),
            'repo': repository.get('name', ''),
            'pr_number': pr_number,
            'pr_title': pull_request.get('title', ''),
            'pr_body': pull_request.get('body', '') or '(no description provided)',
            'head_sha': pull_request.get('head', {}).get('sha', ''),
            'pr_diff': None,
            'diff_stats': None,
            'policy_results': None,
            'terraform_results': None,
            'analysis': None,
            'comment_posted': False,
            'error': None,
        }

        logger.info('Invoking LangGraph PR review', {
            'pr_number': pr_number,
            'repo': repo_full_name,
            'terraform_enabled': is_repo_terraform_enabled(repo_full_name),
        })

        final_state = _graph.invoke(initial_state)

        if final_state.get('error'):
            return {
                'status': 'error',
                'error': final_state['error'],
                'pr_number': pr_number,
                'repo': repo_full_name,
            }

        return {
            'status': 'success',
            'pr_number': pr_number,
            'repo': repo_full_name,
            'agent_response': f'Successfully reviewed PR #{pr_number}. Comment posted to GitHub.',
        }

    except Exception as error:
        logger.error('Error in AgentCore PR analysis', {
            'error': str(error),
            'error_type': type(error).__name__,
        })
        return {
            'status': 'error',
            'error': str(error),
            'pr_number': pr_number,
            'repo': repo_full_name,
        }
    finally:
        logger.clear_pr_context()


if __name__ == '__main__':
    app.run()
