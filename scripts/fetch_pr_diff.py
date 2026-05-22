"""
Fetch a PR diff from GitHub using the same credentials as the app.

Usage: python fetch_pr_diff.py <owner> <repo> <pr_number> <installation_id>
Example: python fetch_pr_diff.py your-org your-repo 1 12345678
"""
import sys
import os
import requests
from github import Auth, GithubIntegration

# Add src to path so we can import utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from utils.secrets import get_secret


def fetch_pr_diff(owner: str, repo: str, pr_number: int, installation_id: int, output_file: str):
    """
    Fetch PR diff from GitHub API using GitHub App credentials.
    
    Uses the same authentication method as the app (GitHub App installation token).
    """
    print(f"Fetching PR #{pr_number} from {owner}/{repo}...")
    print(f"Using GitHub App installation ID: {installation_id}")
    
    # Get GitHub App credentials from Secrets Manager (same as the app)
    github_secret = get_secret(os.environ.get('GITHUB_SECRET_NAME', 'github-pr-agent/github'))
    app_id = github_secret.get('app_id')
    private_key = github_secret.get('private_key')
    
    if not app_id or not private_key:
        print("❌ Error: GitHub App credentials not found in secrets")
        sys.exit(1)
    
    # Create installation token (same as app does)
    integration = GithubIntegration(app_id, private_key)
    auth = integration.get_access_token(installation_id)
    
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    print(f"API URL: {url}")
    
    headers = {
        'Authorization': f'Bearer {auth.token}',
        'Accept': 'application/vnd.github.v3.diff',
        'User-Agent': 'GitHub-PR-Agent-Test'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        diff_content = response.text
        
        # Save to file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(diff_content)
        
        print(f"\n✅ Successfully fetched diff!")
        print(f"   Size: {len(diff_content):,} bytes ({len(diff_content) / 1024:.2f} KB)")
        print(f"   Saved to: {output_file}")
        print(f"\nNow run: python test_diff_truncation.py {output_file}")
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"\n❌ Error: PR not found or not accessible")
            print(f"   This might be a private repo requiring authentication")
        elif e.response.status_code == 403:
            print(f"\n❌ Error: Access forbidden (rate limit or private repo)")
        else:
            print(f"\n❌ Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


def main():
    if len(sys.argv) != 5:
        print("Usage: python fetch_pr_diff.py <owner> <repo> <pr_number> <installation_id>")
        print("\nExample:")
        print("  python fetch_pr_diff.py your-org your-repo 1 12345678")
        print("\nNote: Uses GitHub App credentials from AWS Secrets Manager")
        print("      (same as the app uses in production)")
        print("\nRequires:")
        print("  - AWS credentials configured (for Secrets Manager access)")
        print("  - GITHUB_SECRET_NAME env var (defaults to 'github-pr-agent/github')")
        sys.exit(1)
    
    owner = sys.argv[1]
    repo = sys.argv[2]
    pr_number = int(sys.argv[3])
    installation_id = int(sys.argv[4])
    
    output_file = f"pr{pr_number}_diff.txt"
    
    fetch_pr_diff(owner, repo, pr_number, installation_id, output_file)


if __name__ == '__main__':
    main()
