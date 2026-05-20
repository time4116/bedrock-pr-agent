"""
GitHub API client using PyGithub and direct REST calls.
"""
import io
import time
import zipfile
import requests
from typing import Optional, Dict, Any, List
from github import Github, Auth, GithubIntegration, GithubException, RateLimitExceededException

from src.utils.logger import logger
from src.utils.secrets import get_github_credentials


class GitHubClient:
    """GitHub API client wrapper."""

    def __init__(self, installation_id: Optional[int] = None):
        self.creds = get_github_credentials()
        self.installation_id = installation_id
        self._github = None

    def get_github_client(self) -> Github:
        """Get PyGithub client instance (lazy initialization)."""
        if not self._github:
            if not self.installation_id:
                raise ValueError('installation_id required for PyGithub client')
            integration = GithubIntegration(self.creds['app_id'], self.creds['private_key'])
            auth = integration.get_access_token(self.installation_id)
            self._github = Github(auth=Auth.Token(auth.token))
        return self._github

    def get_installation_token(self) -> str:
        """Return a short-lived installation access token for direct API calls."""
        if self.installation_id:
            integration = GithubIntegration(self.creds['app_id'], self.creds['private_key'])
            return integration.get_access_token(self.installation_id).token
        token = self.creds.get('token')
        if not token:
            raise ValueError('No authentication method available')
        return token

    def _request(self, method: str, url: str, **kwargs) -> Any:
        """Make an authenticated REST API request."""
        token = self.get_installation_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github.v3+json',
            **kwargs.pop('headers', {})
        }
        response = requests.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()

    def get_pull_request(self, repo: str, pr_number: int) -> Dict[str, Any]:
        owner, repo_name = repo.split('/')
        return self._request('GET', f'https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}')

    def get_commit_statuses(self, repo: str, ref: str) -> List[Dict[str, Any]]:
        owner, repo_name = repo.split('/')
        response = self._request('GET', f'https://api.github.com/repos/{owner}/{repo_name}/commits/{ref}/status')
        return response.get('statuses', [])

    def get_actions_runs_for_sha(self, repo: str, head_sha: str) -> List[Dict[str, Any]]:
        """Return completed GitHub Actions workflow runs for a commit SHA."""
        owner, repo_name = repo.split('/')
        url = f'https://api.github.com/repos/{owner}/{repo_name}/actions/runs'
        response = self._request('GET', url, params={'head_sha': head_sha, 'status': 'completed'})
        return response.get('workflow_runs', [])

    def download_run_logs(self, repo: str, run_id: int) -> bytes:
        """Download GitHub Actions workflow run logs as a ZIP archive."""
        owner, repo_name = repo.split('/')
        token = self.get_installation_token()
        url = f'https://api.github.com/repos/{owner}/{repo_name}/actions/runs/{run_id}/logs'
        response = requests.get(
            url,
            headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github.v3+json'},
            allow_redirects=True,
            timeout=60
        )
        response.raise_for_status()
        return response.content

    def extract_log_text(self, log_zip_bytes: bytes) -> str:
        """Extract and concatenate all .txt log files from a GHA log ZIP archive."""
        zip_buffer = io.BytesIO(log_zip_bytes)
        parts = []
        with zipfile.ZipFile(zip_buffer) as zf:
            for name in sorted(zf.namelist()):
                if name.endswith('.txt'):
                    content = zf.read(name).decode('utf-8', errors='replace')
                    parts.append(f'=== {name} ===\n{content}')
        return '\n'.join(parts)


def _retry_on_rate_limit(func, max_retries=3):
    """Retry GitHub API calls with exponential backoff on rate limit."""
    def wrapper(*args, **kwargs):
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except RateLimitExceededException:
                if attempt == max_retries - 1:
                    raise
                wait_time = 2 ** attempt
                logger.warning('GitHub rate limit hit, retrying', {
                    'attempt': attempt + 1,
                    'wait_time': wait_time
                })
                time.sleep(wait_time)
            except GithubException as e:
                if e.status in [403, 429] and attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning('GitHub API error, retrying', {
                        'status': e.status,
                        'attempt': attempt + 1
                    })
                    time.sleep(wait_time)
                else:
                    raise
        return None
    return wrapper


def get_pr_comment(
    octokit: Github,
    owner: str,
    repo: str,
    pr_number: int
) -> Optional[Dict[str, Any]]:
    """Get the bot's existing comment on a PR if it exists."""
    try:
        repository = octokit.get_repo(f'{owner}/{repo}')
        issue = repository.get_issue(pr_number)
        for comment in issue.get_comments():
            if comment.body and '<!-- GITHUB-PR-AGENT-COMMENT -->' in comment.body:
                return {'id': comment.id, 'body': comment.body}
        return None
    except Exception as error:
        logger.error('Error getting PR comments', {'error': str(error)})
        return None


def create_or_update_comment(
    octokit: Github,
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    existing_comment_id: Optional[int] = None
) -> Dict[str, Any]:
    """Create or update a comment on a PR (idempotent)."""
    @_retry_on_rate_limit
    def _post_comment():
        comment_body = f'<!-- GITHUB-PR-AGENT-COMMENT -->\n{body}'
        repository = octokit.get_repo(f'{owner}/{repo}')
        issue = repository.get_issue(pr_number)

        if existing_comment_id:
            comment = issue.get_comment(existing_comment_id)
            if '<!-- GITHUB-PR-AGENT-COMMENT -->' not in comment.body:
                logger.warning('Attempted to edit non-app comment', {'comment_id': existing_comment_id})
                new_comment = issue.create_comment(comment_body)
                logger.info('Created new PR comment (existing was not ours)')
                return new_comment
            comment.edit(comment_body)
            logger.info('Updated existing PR comment', {'comment_id': existing_comment_id})
            return comment
        else:
            new_comment = issue.create_comment(comment_body)
            logger.info('Created new PR comment', {'pr_number': pr_number})
            return new_comment

    try:
        comment = _post_comment()
        return {'id': comment.id, 'html_url': comment.html_url}
    except Exception as error:
        logger.error('Error creating/updating PR comment', {'error': str(error)})
        raise
