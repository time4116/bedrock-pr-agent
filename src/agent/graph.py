"""
LangGraph PR review agent — business logic, independent of the AgentCore runtime.
"""
import os
from pathlib import Path
from typing import Any, Dict, Literal

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from src.agent.state import PRReviewState
from src.agent.tools.github_commenter import post_github_comment
from src.agent.tools.pr_diff_fetcher import fetch_pr_diff
from src.agent.tools.terraform_validator import validate_terraform_plan
from src.utils.config import is_repo_terraform_enabled
from src.utils.logger import logger

_REPO_ROOT = Path(__file__).parent.parent.parent
_TEMPLATES_DIR = _REPO_ROOT / 'templates'
_PROMPTS_DIR = _REPO_ROOT / 'prompts'


def _load_file(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except Exception as e:
        logger.error(f'Failed to load {path.name}', {'error': str(e)})
        return ''


_TEMPLATE_WITH_TERRAFORM = _load_file(_TEMPLATES_DIR / 'pr-comment-with-terraform.md')
_TEMPLATE_WITHOUT_TERRAFORM = _load_file(_TEMPLATES_DIR / 'pr-comment-without-terraform.md')
_PROMPT_PR_REVIEW = _load_file(_PROMPTS_DIR / 'pr-review.md')


# ---------------------------------------------------------------------------
# Nodes
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

    return {
        'pr_diff': diff_content,
        'diff_stats': {
            'files_changed': result.get('files_changed', 0),
            'additions': result.get('additions', 0),
            'deletions': result.get('deletions', 0),
            'truncated': result.get('truncated', False),
            'diff_size_kb': result.get('diff_size_kb', 0),
        },
    }


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
    diff_stats = state.get('diff_stats') or {}
    terraform_results = state.get('terraform_results')

    enable_terraform = terraform_results is not None
    template = _TEMPLATE_WITH_TERRAFORM if enable_terraform else _TEMPLATE_WITHOUT_TERRAFORM

    # Pre-fill factual diff stats so Claude only fills the analytical placeholders
    truncation_note = (
        '> ⚠️ Diff truncated to 320 KB — analysis may be incomplete for very large PRs.\n'
        if diff_stats.get('truncated') else ''
    )
    template = (
        template
        .replace('{FILES_CHANGED}', str(diff_stats.get('files_changed', '?')))
        .replace('{ADDITIONS}', str(diff_stats.get('additions', '?')))
        .replace('{DELETIONS}', str(diff_stats.get('deletions', '?')))
        .replace('{TRUNCATION_NOTE}', truncation_note)
    )

    terraform_context = ''
    if terraform_results and terraform_results.get('success'):
        plans = terraform_results.get('terraform_plans', [])
        if plans:
            plan_texts = [f'Plan {i}:\n{p["plan"]}' for i, p in enumerate(plans, 1)]
            terraform_context = '\n\n**Terraform Plans from GitHub Actions:**\n' + '\n\n'.join(plan_texts)
        else:
            terraform_context = f'\n\n**Terraform Validation**: {terraform_results.get("message", "No plans found.")}'

    prompt = (
        _PROMPT_PR_REVIEW
        .replace('{REPO}', repo_full)
        .replace('{PR_NUMBER}', str(pr_number))
        .replace('{PR_TITLE}', state['pr_title'])
        .replace('{PR_BODY}', state['pr_body'])
        .replace('{DIFF}', diff)
        .replace('{TERRAFORM_CONTEXT}', terraform_context)
        .replace('{REVIEW_TEMPLATE}', template)
    )

    model_id = os.getenv('BEDROCK_MODEL_ID', 'arn:aws:bedrock:us-west-2:322264632107:inference-profile/global.anthropic.claude-sonnet-4-6')
    llm = ChatBedrockConverse(model=model_id, model_provider="anthropic", temperature=0.3, max_tokens=4096)

    logger.info('Calling Bedrock for PR analysis', {
        'pr_number': pr_number,
        'repo': repo_full,
        'diff_size': len(diff),
        'terraform_enabled': enable_terraform,
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

    logger.error('PR agent graph error', {'error': error, 'pr_number': pr_number, 'repo': repo_full})

    try:
        post_github_comment(
            installation_id=state['installation_id'],
            owner=state['owner'],
            repo=state['repo'],
            pr_number=pr_number,
            comment_text=(
                '## PR Analysis\n\n'
                '⚠️ The PR agent encountered an error and could not complete the review.\n\n'
                f'**Error**: `{error}`'
            ),
        )
    except Exception as e:
        logger.error('Failed to post error comment', {'error': str(e)})

    return {}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _route_after_fetch_diff(
    state: PRReviewState,
) -> Literal['validate_terraform', 'analyze_and_comment', 'handle_error']:
    if state.get('error'):
        return 'handle_error'
    if is_repo_terraform_enabled(f"{state['owner']}/{state['repo']}"):
        return 'validate_terraform'
    return 'analyze_and_comment'


def _route_after_validate_terraform(
    state: PRReviewState,
) -> Literal['analyze_and_comment', 'handle_error']:
    if state.get('error'):
        return 'handle_error'
    return 'analyze_and_comment'


def _route_after_analyze(state: PRReviewState) -> Literal[str]:
    if state.get('error'):
        return 'handle_error'
    return END


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_graph() -> Any:
    builder = StateGraph(PRReviewState)

    builder.add_node('fetch_diff', node_fetch_diff)
    builder.add_node('validate_terraform', node_validate_terraform)
    builder.add_node('analyze_and_comment', node_analyze_and_comment)
    builder.add_node('handle_error', node_handle_error)

    builder.set_entry_point('fetch_diff')

    builder.add_conditional_edges('fetch_diff', _route_after_fetch_diff, {
        'validate_terraform': 'validate_terraform',
        'analyze_and_comment': 'analyze_and_comment',
        'handle_error': 'handle_error',
    })
    builder.add_conditional_edges('validate_terraform', _route_after_validate_terraform, {
        'analyze_and_comment': 'analyze_and_comment',
        'handle_error': 'handle_error',
    })
    builder.add_conditional_edges('analyze_and_comment', _route_after_analyze, {
        'handle_error': 'handle_error',
        END: END,
    })
    builder.add_edge('handle_error', END)

    return builder.compile()
