"""
PR Diff Fetcher Tool for Agent.

This tool fetches the actual code changes (diff) from a GitHub PR.
"""
import os
from typing import Dict, Any

from src.services.github_client import create_github_client
from src.utils.logger import logger


def fetch_pr_diff(
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int
) -> Dict[str, Any]:
    """
    Fetch the actual code changes (diff) from a GitHub pull request.
    
    This retrieves the unified diff format showing all file changes in the PR,
    which is more reliable than PR description for validating acceptance criteria.
    
    Args:
        installation_id: GitHub App installation ID
        owner: Repository owner (username or org)
        repo: Repository name
        pr_number: Pull request number
        
    Returns:
        Dictionary with diff file reference:
        {
            "success": bool,
            "diff_file": str (path to temp file with diff content),
            "files_changed": int,
            "additions": int,
            "deletions": int,
            "diff_size_kb": float,
            "truncated": bool (if diff was too large and truncated),
            "error": str (if failed)
        }
    """
    try:
        logger.info('Fetching PR diff', {
            'owner': owner,
            'repo': repo,
            'pr_number': pr_number
        })
        
        # Initialize GitHub client
        octokit = create_github_client(installation_id)
        
        # Get the PR object
        repository = octokit.get_repo(f"{owner}/{repo}")
        pr = repository.get_pull(pr_number)
        
        # Get basic PR stats
        files_changed = pr.changed_files
        additions = pr.additions
        deletions = pr.deletions
        
        # Fetch the diff using GitHub API
        # PyGithub doesn't have direct diff support, so we use raw HTTP request
        import requests
        from src.utils.secrets import get_secret
        
        # Get GitHub credentials
        github_secret = get_secret(os.environ.get('GITHUB_SECRET_NAME', 'github-pr-agent/github'))
        
        # Create installation token
        from github import Auth, GithubIntegration
        app_id = github_secret.get('app_id')
        private_key = github_secret.get('private_key')
        
        integration = GithubIntegration(app_id, private_key)
        auth = integration.get_access_token(installation_id)
        
        # Fetch diff via GitHub API (with Accept header for diff format)
        diff_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        headers = {
            'Authorization': f'Bearer {auth.token}',
            'Accept': 'application/vnd.github.v3.diff'
        }
        
        response = requests.get(diff_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        diff_content = response.text
        original_size = len(diff_content)
        
        # Truncate diff at 400KB (increased for Nova Pro's 300K context)
        # Use intelligent truncation: keep first 160KB + last 160KB + middle indicator
        max_diff_size = 400 * 1024  # 400KB
        truncated = original_size > max_diff_size
        
        if truncated:
            first_chunk_size = 160 * 1024  # 160KB
            last_chunk_size = 160 * 1024   # 160KB
            
            first_chunk = diff_content[:first_chunk_size]
            last_chunk = diff_content[-last_chunk_size:]
            
            truncation_info = (
                f"\n\n{'='*80}\n"
                f"⚠️  DIFF TRUNCATED FOR TOKEN LIMIT\n"
                f"Original size: {original_size:,} bytes\n"
                f"Truncated: {original_size - (first_chunk_size + last_chunk_size):,} bytes\n"
                f"Files changed: {files_changed}\n"
                f"Showing: First 160KB + Last 160KB\n"
                f"{'='*80}\n\n"
            )
            
            diff_content = first_chunk + truncation_info + last_chunk
            
            logger.warning('PR diff truncated due to size', {
                'pr_number': pr_number,
                'original_size': original_size,
                'truncated_size': len(diff_content),
                'files_changed': files_changed
            })
        
        # Write diff to temp file to keep it out of conversation history
        diff_file = f"/tmp/pr-{pr_number}-{owner}-{repo}-diff.txt"
        with open(diff_file, 'w', encoding='utf-8') as f:
            f.write(diff_content)
        
        logger.info('Successfully fetched PR diff and wrote to file', {
            'pr_number': pr_number,
            'files_changed': files_changed,
            'additions': additions,
            'deletions': deletions,
            'diff_file': diff_file,
            'diff_size': len(diff_content),
            'diff_size_kb': round(len(diff_content) / 1024, 2),
            'original_size': original_size,
            'original_size_kb': round(original_size / 1024, 2),
            'truncated': truncated,
            'estimated_tokens': round(len(diff_content) / 4)  # ~4 chars per token estimate
        })
        
        return {
            'success': True,
            'diff_file': diff_file,
            'files_changed': files_changed,
            'additions': additions,
            'deletions': deletions,
            'diff_size_kb': round(len(diff_content) / 1024, 2),
            'truncated': truncated
        }
        
    except Exception as error:
        logger.error('Failed to fetch PR diff', {
            'error': str(error),
            'pr_number': pr_number,
            'owner': owner,
            'repo': repo
        })
        
        return {
            'success': False,
            'error': str(error)
        }
