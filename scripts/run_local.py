#!/usr/bin/env python3
"""
Local PR runner — review a PR without the GitHub App / webhook infrastructure.

Calls AWS Bedrock directly; AWS credentials are required (AWS_PROFILE or
AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY). Uses a plain GitHub token instead of
the GitHub App installation flow, so no Lambda or AgentCore deployment is needed.

Usage:
    GITHUB_TOKEN=ghp_... PR_URL=https://github.com/org/repo/pull/123 python scripts/run_local.py

    # Print the review without posting to GitHub:
    DRY_RUN=true GITHUB_TOKEN=ghp_... PR_URL=... python scripts/run_local.py

    # Enable Terraform validation for this run:
    TERRAFORM_VALIDATION_REPOS=org/repo GITHUB_TOKEN=ghp_... PR_URL=... python scripts/run_local.py

Required environment variables:
    GITHUB_TOKEN    Personal access token with repo scope (replaces the GitHub App)
    PR_URL          Full GitHub PR URL

Optional environment variables:
    BEDROCK_MODEL_ID           Bedrock inference profile ARN or model ID (defaults to Claude Sonnet cross-region)
    DRY_RUN                    Set to 'true' to print the review instead of posting it
    TERRAFORM_VALIDATION_REPOS Comma-separated repos to enable Terraform plan checking
    AWS_PROFILE                AWS credentials profile (alternative to AWS_ACCESS_KEY_ID)
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

from src.agent.graph import build_graph
from src.agent.state import PRReviewState


def parse_pr_url(url: str) -> tuple[str, str, int]:
    match = re.match(r'https://github\.com/([^/]+)/([^/]+)/pull/(\d+)', url.rstrip('/'))
    if not match:
        sys.exit(
            f'Error: invalid PR URL {url!r}\n'
            'Expected: https://github.com/owner/repo/pull/123'
        )
    owner, repo, pr_number = match.groups()
    return owner, repo, int(pr_number)


def main() -> None:
    token = os.environ.get('GITHUB_TOKEN')
    pr_url = os.environ.get('PR_URL')

    if not token:
        sys.exit('Error: GITHUB_TOKEN environment variable is required.')
    if not pr_url:
        sys.exit('Error: PR_URL environment variable is required.')

    dry_run = os.environ.get('DRY_RUN', '').lower() == 'true'
    owner, repo, pr_number = parse_pr_url(pr_url)

    print(f'Fetching PR #{pr_number} from {owner}/{repo}...')

    resp = requests.get(
        f'https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}',
        headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github.v3+json',
        },
        timeout=30,
    )
    resp.raise_for_status()
    pr_data = resp.json()

    if dry_run:
        print('DRY_RUN=true — review will be printed, not posted to GitHub.\n')

    initial_state: PRReviewState = {
        'installation_id': 0,
        'owner': owner,
        'repo': repo,
        'pr_number': pr_number,
        'pr_title': pr_data.get('title', ''),
        'pr_body': pr_data.get('body') or '(no description provided)',
        'head_sha': pr_data.get('head', {}).get('sha', ''),
        'pr_diff': None,
        'diff_stats': None,
        'policy_results': None,
        'terraform_results': None,
        'analysis': None,
        'comment_posted': False,
        'error': None,
    }

    print('Running PR analysis...')
    graph = build_graph()
    final_state = graph.invoke(initial_state)

    if final_state.get('error'):
        sys.exit(f'Error: {final_state["error"]}')

    if dry_run:
        print('\n' + '─' * 60)
        print(final_state.get('analysis', '(no analysis generated)'))
        print('─' * 60)
    else:
        print(f'Done — comment posted to PR #{pr_number}.')


if __name__ == '__main__':
    main()
