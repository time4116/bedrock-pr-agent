import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


# The production modules import optional deployment dependencies at import time.
fake_github = types.ModuleType("github")
setattr(fake_github, "Github", object)
setattr(fake_github, "Auth", types.SimpleNamespace(Token=lambda token: token))
setattr(fake_github, "GithubIntegration", object)
setattr(fake_github, "GithubException", type("GithubException", (Exception,), {"status": None}))
setattr(fake_github, "RateLimitExceededException", type("RateLimitExceededException", (Exception,), {}))
sys.modules.setdefault("github", fake_github)

fake_boto3 = types.ModuleType("boto3")
setattr(fake_boto3, "client", lambda *args, **kwargs: None)
sys.modules.setdefault("boto3", fake_boto3)

fake_botocore = types.ModuleType("botocore")
fake_botocore_exceptions = types.ModuleType("botocore.exceptions")
setattr(fake_botocore_exceptions, "ClientError", type("ClientError", (Exception,), {}))
sys.modules.setdefault("botocore", fake_botocore)
sys.modules.setdefault("botocore.exceptions", fake_botocore_exceptions)

fake_requests = types.ModuleType("requests")
setattr(fake_requests, "request", lambda *args, **kwargs: None)
setattr(fake_requests, "get", lambda *args, **kwargs: None)
sys.modules.setdefault("requests", fake_requests)

from src.agent.tools import pr_diff_fetcher  # noqa: E402
import src.services.github_client as github_client_module  # noqa: E402


class FakeFile:
    def __init__(self, filename, status, additions, deletions, patch_text):
        self.filename = filename
        self.status = status
        self.additions = additions
        self.deletions = deletions
        self.patch = patch_text


class FakePullRequest:
    changed_files = 1
    additions = 2
    deletions = 1

    def get_files(self):
        return [
            FakeFile(
                "README.md",
                "modified",
                2,
                1,
                "@@ -1 +1,2 @@\n-old\n+new\n+line",
            )
        ]


class FakeRepository:
    def get_pull(self, pr_number):
        assert pr_number == 9
        return FakePullRequest()


class FakeGithub:
    def get_repo(self, full_name):
        assert full_name == "time4116/bedrock-pr-agent"
        return FakeRepository()


class RaisingGitHubClient:
    def __init__(self, installation_id):
        raise AssertionError("fetch_pr_diff should not use the raw diff HTTP token path")


class FetchPrDiffTests(unittest.TestCase):
    def test_builds_diff_from_authenticated_pull_request_files(self):
        with patch.object(pr_diff_fetcher, "create_github_client", return_value=FakeGithub()), \
             patch.object(github_client_module, "GitHubClient", RaisingGitHubClient):
            result = pr_diff_fetcher.fetch_pr_diff(
                installation_id=123,
                owner="time4116",
                repo="bedrock-pr-agent",
                pr_number=9,
            )

        self.assertTrue(result["success"], result.get("error"))
        diff_path = Path(result["diff_file"])
        diff_text = diff_path.read_text(encoding="utf-8")
        self.assertIn("diff --git a/README.md b/README.md", diff_text)
        self.assertIn("@@ -1 +1,2 @@", diff_text)
        self.assertEqual(result["files_changed"], 1)
        self.assertEqual(result["additions"], 2)
        self.assertEqual(result["deletions"], 1)


if __name__ == "__main__":
    unittest.main()
