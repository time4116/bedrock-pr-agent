"""
Configuration utilities for filtering repos.
"""
import os
from typing import List, Dict, Any

from src.utils.logger import logger


def is_repo_allowed(repo_full_name: str) -> bool:
    """
    Check if a repository is in the allowed list.

    Args:
        repo_full_name: Full repository name (owner/repo)

    Returns:
        True if allowed, False otherwise
    """
    allowed_repos = os.environ.get('ALLOWED_REPOS', '')

    if not allowed_repos:
        logger.warning('ALLOWED_REPOS not configured, allowing all repos')
        return True

    repo_list = [repo.strip().lower() for repo in allowed_repos.split(',')]
    is_allowed = repo_full_name.lower() in repo_list

    logger.debug('Checking repo allowlist', {
        'repo_full_name': repo_full_name,
        'is_allowed': is_allowed
    })

    return is_allowed


def is_repo_terraform_enabled(repo_full_name: str) -> bool:
    """
    Check if Terraform validation is enabled for a repository.

    When enabled, the agent will fetch GitHub Actions logs for the PR and
    validate any Terraform plan output found there.

    Args:
        repo_full_name: Full repository name (owner/repo)

    Returns:
        True if Terraform validation is enabled for this repo, False otherwise
    """
    terraform_repos = os.environ.get('TERRAFORM_VALIDATION_REPOS', '')

    if not terraform_repos:
        return False

    repo_list = [repo.strip().lower() for repo in terraform_repos.split(',')]
    is_enabled = repo_full_name.lower() in repo_list

    logger.debug('Checking Terraform validation', {
        'repo_full_name': repo_full_name,
        'is_enabled': is_enabled
    })

    return is_enabled


def get_config() -> Dict[str, Any]:
    """
    Get configuration values with defaults.

    Returns:
        Dict containing configuration values
    """
    allowed_repos_str = os.environ.get('ALLOWED_REPOS', '')
    terraform_repos_str = os.environ.get('TERRAFORM_VALIDATION_REPOS', '')

    return {
        'allowed_repos': [r.strip() for r in allowed_repos_str.split(',') if r.strip()],
        'terraform_validation_repos': [r.strip() for r in terraform_repos_str.split(',') if r.strip()],
        'aws_region': os.environ.get('AWS_REGION', 'us-east-1'),
        'stage': os.environ.get('STAGE', 'dev')
    }
