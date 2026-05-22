#!/usr/bin/env python3
"""
Create a GitHub App via the App Manifest flow and store credentials in
AWS Secrets Manager.

Starts a local HTTP server, opens your browser at GitHub's pre-filled
"Create GitHub App" page, then captures credentials automatically after
you click "Create GitHub App".

Usage:
    python scripts/create_github_app.py
    python scripts/create_github_app.py --name my-pr-agent
    python scripts/create_github_app.py --org my-org
    python scripts/create_github_app.py --store-secret
    python scripts/create_github_app.py --store-secret --region us-west-2

Requirements:
    - Logged in to GitHub in your default browser
    - AWS credentials configured (only if using --store-secret)
"""
import argparse
import http.server
import json
import os
import sys
import threading
import webbrowser
from urllib.parse import parse_qs, urlparse

import requests

DEFAULT_APP_NAME = "pr-agent"
DEFAULT_PORT = 3456
SECRET_NAME = "github-pr-agent/github"


def build_manifest(name: str, port: int) -> dict:
    return {
        "name": name,
        "url": "https://github.com",
        "hook_attributes": {
            "url": "https://placeholder.example.com",
            "active": False,
        },
        "redirect_url": f"http://localhost:{port}/callback",
        "public": False,
        "default_permissions": {
            "issues": "write",
            "pull_requests": "read",
            "contents": "read",
            "actions": "read",
            "metadata": "read",
        },
        "default_events": ["pull_request"],
    }


def _form_html(manifest: dict, action_url: str) -> bytes:
    escaped = json.dumps(manifest).replace("&", "&amp;").replace('"', "&quot;")
    return f"""<!DOCTYPE html>
<html><body>
<form id="f" method="post" action="{action_url}">
  <input type="hidden" name="manifest" value="{escaped}">
</form>
<script>document.getElementById('f').submit();</script>
<p>Redirecting to GitHub...</p>
</body></html>""".encode()


def _done_html() -> bytes:
    return b"""<!DOCTYPE html>
<html><body>
<h2>GitHub App created. You can close this tab.</h2>
</body></html>"""


def run_local_server(manifest: dict, github_url: str, port: int) -> str:
    """Serve the manifest form and wait for GitHub's callback. Returns the code."""
    code_holder: list[str] = []
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(_form_html(manifest, github_url))
            elif parsed.path == "/callback":
                params = parse_qs(parsed.query)
                code = params.get("code", [None])[0]
                self.send_response(200 if code else 400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                if code:
                    code_holder.append(code)
                    self.wfile.write(_done_html())
                    done.set()
                else:
                    self.wfile.write(b"<html><body>Missing code — something went wrong.</body></html>")
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *_args):
            pass  # suppress request logs

    server = http.server.HTTPServer(("localhost", port), Handler)
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()

    webbrowser.open(f"http://localhost:{port}/")
    print("Browser opened — click 'Create GitHub App' on GitHub to continue.")
    done.wait()
    server.shutdown()

    if not code_holder:
        sys.exit("No code received from GitHub.")
    return code_holder[0]


def exchange_code(code: str) -> dict:
    resp = requests.post(
        f"https://api.github.com/app-manifests/{code}/conversions",
        headers={"Accept": "application/vnd.github.v3+json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def store_in_secrets_manager(credentials: dict, secret_name: str, region: str) -> None:
    import boto3

    client = boto3.client("secretsmanager", region_name=region)
    value = json.dumps({
        "app_id": str(credentials["id"]),
        "webhook_secret": credentials["webhook_secret"],
        "private_key": credentials["pem"],
    })
    try:
        client.create_secret(Name=secret_name, SecretString=value)
        print(f"Secret created: {secret_name} ({region})")
    except client.exceptions.ResourceExistsException:
        client.put_secret_value(SecretId=secret_name, SecretString=value)
        print(f"Secret updated: {secret_name} ({region})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--name", default=DEFAULT_APP_NAME,
                        help=f"GitHub App name (default: {DEFAULT_APP_NAME})")
    parser.add_argument("--org",
                        help="Create under a GitHub org instead of your personal account")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Local callback port (default: {DEFAULT_PORT})")
    parser.add_argument("--store-secret", action="store_true",
                        help="Store credentials in AWS Secrets Manager after creation")
    parser.add_argument("--secret-name", default=SECRET_NAME,
                        help=f"Secrets Manager secret name (default: {SECRET_NAME})")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"),
                        help="AWS region for Secrets Manager (default: us-east-1)")
    args = parser.parse_args()

    if args.org:
        github_url = f"https://github.com/organizations/{args.org}/settings/apps/new"
    else:
        github_url = "https://github.com/settings/apps/new"

    manifest = build_manifest(args.name, args.port)

    print(f"Creating GitHub App '{args.name}'")
    print(f"  Target : {'org: ' + args.org if args.org else 'personal account'}")
    print(f"  Webhook: https://placeholder.example.com (update after CDK deploy)\n")

    code = run_local_server(manifest, github_url, args.port)

    print("Exchanging code for credentials...")
    credentials = exchange_code(code)

    app_id = credentials["id"]
    webhook_secret = credentials["webhook_secret"]
    html_url = credentials.get("html_url", "")

    print(f"\nApp created: {html_url}")
    print(f"  App ID         : {app_id}")
    print(f"  Webhook secret : {webhook_secret}")

    if args.store_secret:
        print(f"\nStoring credentials in Secrets Manager...")
        store_in_secrets_manager(credentials, args.secret_name, args.region)
        print("\nNext: run 'cdk deploy --all', then update the webhook URL in GitHub App settings.")
    else:
        print("\nCredentials not stored. Re-run with --store-secret, or store manually:")
        print(f"\n  python scripts/create_github_app.py --store-secret\n")
        print("Private key (save this):")
        print(credentials["pem"])


if __name__ == "__main__":
    main()
