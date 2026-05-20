"""
Amazon Bedrock AgentCore entrypoint for PR analysis.

The agent runs a deterministic LangGraph StateGraph:
  1. fetch_diff          — download the unified diff from GitHub
  2. check_policy        — validate changes against org policy documents (optional)
  3. validate_terraform  — detect risky infra changes (optional)
  4. analyze_and_comment — call Claude via Bedrock, render template, post comment
"""
import os
from typing import Dict, Any, Literal
from pathlib import Path

from bedrock_agentcore import BedrockAgentCoreApp
from langgraph.graph import StateGraph, END
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage

from src.agent.state import PRReviewState
from src.agent.tools.pr_diff_fetcher import fetch_pr_diff
from src.agent.tools.org_policy_checker import check_organization_policy
from src.agent.tools.terraform_validator import validate_terraform_plan
from src.agent.tools.github_commenter import post_github_comment
from src.utils.logger import logger
from src.utils.config import is_repo_allowed, is_repo_terraform_enabled

TEMPLATES_DIR = Path(__file__).parent / 'templates'


def _load_template(name: str) -> str:
    try:
        return (TEMPLATES_DIR / name).read_text(encoding='utf-8')
    except Exception as e:
        logger.error(f'Failed to load template {name}', {'error': str(e)})
        return ''


TEMPLATE_WITH_TERRAFORM = _load_template('pr-comment-with-terraform.md')
TEMPLATE_WITHOUT_TERRAFORM = _load_template('pr-comment-without-terraform.md')

app = BedrockAgentCoreApp()

MODEL_ID = os.getenv('BEDROCK_MODEL_ID', 'us.amazon.nova-pro-v1:0')

logger.info('AgentCore PR Agent initialized', {'model': MODEL_ID})


# ---------------------------------------------------------------------------
# Graph node implementations
# ---------------------------------------------------------------------------

def node_fetch_diff(state: PRReviewState) -> Dict[str, Any]:
    result = fetch_pr_diff(
        installation_id=state['installation_id'],
        owner=state['owner'],
        repo=state['repo'],
        pr_number=state['pr_number'],
    )
    if not result.get('success'):
        return {'error': f"fetch_diff failed: {result.get('error', 'unknown')}"}

    diff_content = ''
    diff_file = result.get('diff_file')
    if diff_file:
        try:
            with open(diff_file, 'r', encoding='utf-8') as f:
                diff_content = f.read()
        except Exception as e:
            return {'error': f'Could not read diff file: {e}'}

    return {'pr_diff': diff_content}


def node_check_policy(state: PRReviewState) -> Dict[str, Any]:
    diff = state.get('pr_diff') or ''

    changed_files: list[str] = []
    for line in diff.splitlines():
        if line.startswith('+++ b/'):
            changed_files.append(line[6:])

    result = check_organization_policy(
        pr_diff=diff,
        pr_metadata={
            'title': state['pr_title'],
            'description': state['pr_body'],
            'branch_name': state.get('head_sha', ''),
            'repo_name': f"{state['owner']}/{state['repo']}",
        },
        changed_files=changed_files,
    )
    return {'policy_results': result}


def node_validate_terraform(state: PRReviewState) -> Dict[str, Any]:
    result = validate_terraform_plan(
        owner=state['owner'],
        repo=state['repo'],
        pr_number=state['pr_number'],
        installation_id=state['installation_id'],
    )
    return {'terraform_results': result}


def node_analyze_and_comment(state: PRReviewState) -> Dict[str, Any]:
    repo_full = f"{state['owner']}/{state['repo']}"
    pr_number = state['pr_number']
    diff = state.get('pr_diff') or ''
    policy_results = state.get('policy_results')
    terraform_results = state.get('terraform_results')

    enable_terraform = terraform_results is not None
    template = TEMPLATE_WITH_TERRAFORM if enable_terraform else TEMPLATE_WITHOUT_TERRAFORM

    # Build the policy section context for the model
    policy_context = ''
    if policy_results and policy_results.get('policy_enabled'):
        relevant = policy_results.get('relevant_policies', [])
        if relevant:
            policy_context = '\n\n**Organization Policies to check against:**\n' + '\n---\n'.join(relevant)
        else:
            policy_context = '\n\n**Organization Policy Check**: No policy documents found.'

    # Build the terraform context for the model
    terraform_context = ''
    if terraform_results and terraform_results.get('success'):
        plans = terraform_results.get('terraform_plans', [])
        if plans:
            plan_texts = []
            for i, p in enumerate(plans, 1):
                plan_texts.append(f'Plan {i}:\n{p["plan"]}')
            terraform_context = '\n\n**Terraform Plans from GitHub Actions:**\n' + '\n\n'.join(plan_texts)
        else:
            terraform_context = f'\n\n**Terraform Validation**: {terraform_results.get("message", "No plans found.")}'

    prompt = f"""You are a GitHub PR review assistant. Analyze this pull request and produce a structured review comment.

**Repository**: {repo_full}
**PR Number**: #{pr_number}
**PR Title**: {state['pr_title']}
**PR Description**:
{state['pr_body']}

**PR Diff**:
{diff}
{policy_context}{terraform_context}

**Instructions:**
Fill in the following template exactly. Replace every placeholder with your analysis.
Do NOT invent requirements beyond what the PR description states.
Keep analysis concise (2–4 sentences per section).

Placeholders to fill:
- {{PR_ANALYSIS}}: Whether the code changes match the PR title and description. Note obvious gaps or unrelated changes.
- {{POLICY_COMPLIANCE_SECTION}}: Policy findings (violations / warnings / recommendations). If policy check was not run, write "Policy check not enabled."
- {{TERRAFORM_ENVIRONMENT_ANALYSIS}}: Per-environment Terraform assessment with 🚨 warnings for unexpected deletions. If Terraform check was not run, write "Terraform validation not enabled for this repository."
- {{COVERAGE_STATUS}}: One of ✅ / ⚠️ / ❌ based on how well the diff matches the PR description.
- {{REQUIREMENTS_ANALYSIS}}: Specific observations about what was and wasn't implemented.
- {{OVERALL_ASSESSMENT_ICON}}: One of ✅ / ⚠️ / 🚨
- {{OVERALL_RECOMMENDATION}}: 1–2 sentence summary and clear recommendation.

**Template:**
{template}

Return ONLY the filled-in comment. Do not add any text before or after it."""

    llm = ChatBedrockConverse(
        model=MODEL_ID,
        temperature=0.3,
        max_tokens=4096,
    )

    logger.info('Calling Bedrock for PR analysis', {
        'pr_number': pr_number,
        'repo': repo_full,
        'diff_size': len(diff),
        'terraform_enabled': enable_terraform,
        'policy_enabled': bool(policy_results and policy_results.get('policy_enabled')),
    })

    response = llm.invoke([HumanMessage(content=prompt)])
    comment_text = response.content if isinstance(response.content, str) else str(response.content)

    post_result = post_github_comment(
        installation_id=state['installation_id'],
        owner=state['owner'],
        repo=state['repo'],
        pr_number=pr_number,
        comment_text=comment_text,
    )

    if not post_result.get('success'):
        return {'error': f"post_github_comment failed: {post_result.get('error', 'unknown')}"}

    logger.info('PR review comment posted', {
        'pr_number': pr_number,
        'repo': repo_full,
        'action': post_result.get('action'),
        'comment_id': post_result.get('comment_id'),
    })

    return {'analysis': comment_text, 'comment_posted': True}


def node_handle_error(state: PRReviewState) -> Dict[str, Any]:
    error = state.get('error', 'Unknown error')
    pr_number = state['pr_number']
    repo_full = f"{state['owner']}/{state['repo']}"

    logger.error('PR agent graph error', {
        'error': error,
        'pr_number': pr_number,
        'repo': repo_full,
    })

    # Best-effort minimal error comment
    try:
        post_github_comment(
            installation_id=state['installation_id'],
            owner=state['owner'],
            repo=state['repo'],
            pr_number=pr_number,
            comment_text=(
                f'<!-- GITHUB-PR-AGENT-COMMENT -->\n'
                f'## 🤖 Automated PR Review\n\n'
                f'⚠️ The PR agent encountered an error and could not complete the review.\n\n'
                f'**Error**: `{error}`'
            ),
        )
    except Exception as e:
        logger.error('Failed to post error comment', {'error': str(e)})

    return {}


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def _route_after_fetch_diff(state: PRReviewState) -> Literal['check_policy', 'validate_terraform', 'analyze_and_comment', 'handle_error']:
    if state.get('error'):
        return 'handle_error'
    if os.environ.get('ORG_POLICY_CHECK_ENABLED', 'false').lower() == 'true':
        return 'check_policy'
    repo_full = f"{state['owner']}/{state['repo']}"
    if is_repo_terraform_enabled(repo_full):
        return 'validate_terraform'
    return 'analyze_and_comment'


def _route_after_check_policy(state: PRReviewState) -> Literal['validate_terraform', 'analyze_and_comment', 'handle_error']:
    if state.get('error'):
        return 'handle_error'
    repo_full = f"{state['owner']}/{state['repo']}"
    if is_repo_terraform_enabled(repo_full):
        return 'validate_terraform'
    return 'analyze_and_comment'


def _route_after_validate_terraform(state: PRReviewState) -> Literal['analyze_and_comment', 'handle_error']:
    if state.get('error'):
        return 'handle_error'
    return 'analyze_and_comment'


def _route_after_analyze(state: PRReviewState) -> Literal[str]:
    if state.get('error'):
        return 'handle_error'
    return END


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _build_graph() -> Any:
    builder = StateGraph(PRReviewState)

    builder.add_node('fetch_diff', node_fetch_diff)
    builder.add_node('check_policy', node_check_policy)
    builder.add_node('validate_terraform', node_validate_terraform)
    builder.add_node('analyze_and_comment', node_analyze_and_comment)
    builder.add_node('handle_error', node_handle_error)

    builder.set_entry_point('fetch_diff')

    builder.add_conditional_edges(
        'fetch_diff',
        _route_after_fetch_diff,
        {
            'check_policy': 'check_policy',
            'validate_terraform': 'validate_terraform',
            'analyze_and_comment': 'analyze_and_comment',
            'handle_error': 'handle_error',
        },
    )
    builder.add_conditional_edges(
        'check_policy',
        _route_after_check_policy,
        {
            'validate_terraform': 'validate_terraform',
            'analyze_and_comment': 'analyze_and_comment',
            'handle_error': 'handle_error',
        },
    )
    builder.add_conditional_edges(
        'validate_terraform',
        _route_after_validate_terraform,
        {
            'analyze_and_comment': 'analyze_and_comment',
            'handle_error': 'handle_error',
        },
    )
    builder.add_conditional_edges(
        'analyze_and_comment',
        _route_after_analyze,
        {
            'handle_error': 'handle_error',
            END: END,
        },
    )
    builder.add_edge('handle_error', END)

    return builder.compile()


_graph = _build_graph()


# ---------------------------------------------------------------------------
# AgentCore entrypoint
# ---------------------------------------------------------------------------

@app.entrypoint
def invoke(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entrypoint for PR analysis via AgentCore Runtime.

    Expected payload (forwarded from the worker Lambda via SQS):
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
    branch_name = pull_request.get('head', {}).get('ref', '')
    installation_id = installation.get('id')

    logger.set_pr_context(
        pr_number=pr_number,
        repo=repo_full_name,
        branch=branch_name,
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

        owner = repository.get('owner', {}).get('login', '')
        repo_name = repository.get('name', '')
        pr_title = pull_request.get('title', '')
        pr_body = pull_request.get('body', '') or '(no description provided)'
        head_sha = pull_request.get('head', {}).get('sha', '')

        initial_state: PRReviewState = {
            'installation_id': installation_id,
            'owner': owner,
            'repo': repo_name,
            'pr_number': pr_number,
            'pr_title': pr_title,
            'pr_body': pr_body,
            'head_sha': head_sha,
            'pr_diff': None,
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
            'policies_enabled': os.environ.get('ORG_POLICY_CHECK_ENABLED', 'false').lower() == 'true',
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
