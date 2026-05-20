"""
Terraform validation tool for Strands Agent.

Fetches GitHub Actions workflow logs for the PR, extracts Terraform plan output,
and returns it for agent analysis. Flags resource deletions and replacements that
may indicate stagnant branches or accidental infrastructure removal.
"""
import re
from typing import Dict, Any, List

from src.utils.logger import logger
from src.services.github_client import GitHubClient


def validate_terraform_plan(
    owner: str,
    repo: str,
    pr_number: int,
    installation_id: int
) -> Dict[str, Any]:
    """
    Fetch GitHub Actions logs for the PR's head commit and extract Terraform plan output.

    Validates the plan for unexpected resource deletions that may indicate a stagnant
    branch needing rebase or accidental infrastructure removal.

    Args:
        owner: Repository owner (GitHub org or username)
        repo: Repository name
        pr_number: Pull request number
        installation_id: GitHub App installation ID

    Returns:
        Dictionary with validation results:
        {
            "success": bool,
            "terraform_plans": List[Dict] — each with "plan", "deletion_summary", "plan_size",
            "run_id": int — the GitHub Actions run that was used,
            "error": str (if failed)
        }
    """
    try:
        repo_full = f'{owner}/{repo}'
        logger.info('Starting Terraform plan validation via GitHub Actions', {
            'repo': repo_full,
            'pr_number': pr_number
        })

        github_client = GitHubClient(installation_id)

        # Get the PR's head SHA
        pr_data = github_client.get_pull_request(repo_full, pr_number)
        head_sha = pr_data.get('head', {}).get('sha')
        if not head_sha:
            return {'success': False, 'error': 'Could not determine PR head SHA'}

        # Find the most recent completed Actions run for this commit
        runs = github_client.get_actions_runs_for_sha(repo_full, head_sha)
        if not runs:
            logger.warning('No completed GitHub Actions runs found for commit', {
                'head_sha': head_sha
            })
            return {
                'success': True,
                'terraform_plans': [],
                'message': 'No completed GitHub Actions runs found for this commit'
            }

        # Use the most recent run
        latest_run = runs[0]
        run_id = latest_run['id']
        logger.info('Using GitHub Actions run', {
            'run_id': run_id,
            'name': latest_run.get('name'),
            'conclusion': latest_run.get('conclusion')
        })

        # Download and extract log archive
        log_zip = github_client.download_run_logs(repo_full, run_id)
        log_text = github_client.extract_log_text(log_zip)

        # Extract Terraform plan sections
        terraform_plans = _extract_terraform_plans(log_text)

        if not terraform_plans:
            return {
                'success': True,
                'terraform_plans': [],
                'run_id': run_id,
                'message': 'No Terraform plan output found in workflow logs'
            }

        total_size = sum(p['plan_size'] for p in terraform_plans)
        logger.info('Extracted Terraform plans', {
            'plan_count': len(terraform_plans),
            'total_size_kb': round(total_size / 1024, 2)
        })

        return {
            'success': True,
            'terraform_plans': terraform_plans,
            'run_id': run_id,
            'deletion_warning': (
                'CRITICAL: Review ALL resource deletions against the PR description. '
                'Deletions may indicate a stagnant branch needing rebase OR accidental removal.'
            ),
            'template_guidance': """Format Terraform validation results:

### 🏗️ Terraform Validation

For each environment/plan found:
**{Environment}**: (✅ / ⚠️ / 🚨) + brief assessment

Resource Deletions:
🚨 IF any resources are being DESTROYED:
  - List each deleted resource explicitly
  - Cross-reference with the PR description
  - If NOT mentioned in PR → flag as unexpected (stagnant branch or accidental removal)
  - If justified by PR description → confirm alignment

For all changes: list resources being added/changed/destroyed.
Highlight REPLACEMENT operations (destroy + create) — these carry data-loss risk.
Use code blocks for resource details. Flag critical issues with 🚨."""
        }

    except Exception as error:
        logger.error('Failed to validate Terraform plan', {
            'error': str(error),
            'repo': f'{owner}/{repo}',
            'pr_number': pr_number
        })
        return {'success': False, 'error': str(error)}


def _analyze_plan_deletions(plan_text: str) -> Dict[str, Any]:
    """Identify resource deletions and replacements in a Terraform plan section."""
    analysis = {
        'has_deletions': False,
        'deletion_count': 0,
        'deleted_resources': [],
        'has_replacements': False,
        'replacement_count': 0,
        'replaced_resources': []
    }

    for line in plan_text.split('\n'):
        if 'will be destroyed' in line.lower():
            analysis['has_deletions'] = True
            analysis['deletion_count'] += 1
            match = re.search(r'#\s+([^\s]+)\s+will be destroyed', line)
            if match:
                analysis['deleted_resources'].append(match.group(1))

        if 'must be replaced' in line.lower() or 'forces replacement' in line.lower():
            analysis['has_replacements'] = True
            analysis['replacement_count'] += 1
            match = re.search(r'#\s+([^\s]+)\s+', line)
            if match and match.group(1) not in analysis['replaced_resources']:
                analysis['replaced_resources'].append(match.group(1))

    return analysis


def _extract_terraform_plans(log_content: str) -> List[Dict[str, Any]]:
    """
    Extract Terraform plan sections from workflow log text.

    Captures text between 'Terraform will perform the following actions:' and the
    'Plan: X to add' summary line. Plans are NOT truncated — losing middle context
    makes deletion detection unreliable.
    """
    plans = []
    lines = log_content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i]

        if 'Terraform will perform the following actions:' in line:
            plan_lines = [line]
            i += 1

            while i < len(lines):
                current_line = lines[i]
                plan_lines.append(current_line)

                if ('Plan:' in current_line and
                        any(k in current_line for k in ('to add', 'to change', 'to destroy'))):
                    break

                # Stop if a new plan section starts
                if (i > 0 and
                        'Terraform will perform the following actions:' in current_line):
                    plan_lines.pop()
                    i -= 1
                    break

                i += 1

            if len(plan_lines) > 1:
                plan_text = '\n'.join(plan_lines)
                plan_size = len(plan_text)

                if plan_size > 50 * 1024:
                    logger.warning('Large Terraform plan — not truncating', {
                        'plan_size_kb': round(plan_size / 1024, 2)
                    })

                plans.append({
                    'plan': plan_text,
                    'deletion_summary': _analyze_plan_deletions(plan_text),
                    'plan_size': plan_size
                })

            continue

        i += 1

    return plans
