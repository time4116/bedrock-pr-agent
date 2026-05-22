"""
GitHub comment tool.

This tool allows the agent to post or update comments on GitHub PRs using
standardized templates for consistency.
"""
import os
from typing import Dict, Any

from src.services.github_client import create_github_client, create_or_update_comment, get_pr_comment
from src.utils.logger import logger


# In-memory cache to prevent duplicate posts within same execution
# Key: "owner/repo/pr_number", Value: comment_id
_posted_comments = {}


def post_github_comment(
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    comment_text: str
) -> Dict[str, Any]:
    """
    Post or update a comment on a GitHub pull request using standardized templates.
    
    This tool handles creating a new comment or updating an existing one
    that was previously posted by this app (identified by HTML marker).

    IMPORTANT: The agent should format comment_text using one of these templates:
    - templates/pr-comment-with-terraform.md (Terraform changes detected)
    - templates/pr-comment-without-terraform.md (standard PR review)
    
    Args:
        installation_id: GitHub App installation ID
        owner: Repository owner (username or org)
        repo: Repository name
        pr_number: Pull request number
        comment_text: The formatted comment content (agent should use templates)
        
    Returns:
        Dictionary with status and comment details:
        {
            "success": bool,
            "comment_id": int,
            "action": "created" or "updated",
            "error": str (if failed),
            "template_hint": str (reminder about templates)
        }
    """
    try:
        if os.environ.get('DRY_RUN', '').lower() == 'true':
            print(comment_text)
            return {'success': True, 'comment_id': None, 'action': 'dry_run'}

        # Create cache key for this PR
        cache_key = f"{owner}/{repo}/{pr_number}"
        
        # Check if we already posted a comment in this execution
        if cache_key in _posted_comments:
            logger.warning('Duplicate post_github_comment call detected', {
                'owner': owner,
                'repo': repo,
                'pr_number': pr_number,
                'previous_comment_id': _posted_comments[cache_key]
            })
            return {
                'success': True,
                'comment_id': _posted_comments[cache_key],
                'action': 'skipped_duplicate',
                'message': 'Comment already posted in this execution'
            }
        
        logger.info('Posting GitHub comment', {
            'owner': owner,
            'repo': repo,
            'pr_number': pr_number
        })
        
        # Initialize GitHub client
        octokit = create_github_client(installation_id)
        
        # Check if we already have a comment
        existing_comment = get_pr_comment(octokit, owner, repo, pr_number)
        
        # Create or update comment
        result = create_or_update_comment(
            octokit,
            owner,
            repo,
            pr_number,
            comment_text,
            existing_comment.get('id') if existing_comment else None
        )
        
        action = 'updated' if existing_comment else 'created'
        
        # Cache the comment ID to prevent duplicate posts
        _posted_comments[cache_key] = result.get('id')
        
        logger.info('GitHub comment posted successfully', {
            'pr_number': pr_number,
            'action': action,
            'comment_id': result.get('id')
        })
        
        return {
            'success': True,
            'comment_id': result.get('id'),
            'action': action,
            'url': result.get('html_url'),
            'template_hint': 'Use templates/pr-comment-*.md for consistent formatting'
        }
        
    except Exception as error:
        logger.error('Failed to post GitHub comment', {
            'error': str(error),
            'pr_number': pr_number,
            'owner': owner,
            'repo': repo
        })
        
        return {
            'success': False,
            'error': str(error)
        }
