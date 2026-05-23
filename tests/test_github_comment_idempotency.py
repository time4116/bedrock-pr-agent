import sys
import types
import unittest


# The production module imports optional deployment dependencies at import time.
# These fakes let the idempotency unit tests exercise the comment logic without
# requiring AWS/PyGithub packages in the local test environment.
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

from src.services.github_client import create_or_update_comment  # noqa: E402


MARKER = "<!-- GITHUB-PR-AGENT-COMMENT -->"


class FakeComment:
    def __init__(self, comment_id, body):
        self.id = comment_id
        self.body = body
        self.html_url = f"https://example.test/comments/{comment_id}"
        self.edit_calls = []

    def edit(self, body):
        self.edit_calls.append(body)
        self.body = body


class FakeIssue:
    def __init__(self, comments):
        self.comments = comments
        self.created_comments = []

    def get_comments(self):
        return list(self.comments)

    def get_comment(self, comment_id):
        for comment in self.comments:
            if comment.id == comment_id:
                return comment
        raise AssertionError(f"unknown comment id {comment_id}")

    def create_comment(self, body):
        comment = FakeComment(999, body)
        self.comments.append(comment)
        self.created_comments.append(comment)
        return comment


class FakeRepository:
    def __init__(self, issue):
        self.issue = issue

    def get_issue(self, pr_number):
        assert pr_number == 6
        return self.issue


class FakeGithub:
    def __init__(self, issue):
        self.issue = issue

    def get_repo(self, full_name):
        assert full_name == "time4116/bedrock-pr-agent"
        return FakeRepository(self.issue)


class CreateOrUpdateCommentTests(unittest.TestCase):
    def test_updates_existing_bot_comment_when_no_existing_id_is_passed(self):
        existing = FakeComment(123, f"{MARKER}\nold review")
        issue = FakeIssue([existing])
        octokit = FakeGithub(issue)

        result = create_or_update_comment(
            octokit,
            "time4116",
            "bedrock-pr-agent",
            6,
            "new review",
            existing_comment_id=None,
        )

        self.assertEqual(result["id"], 123)
        self.assertEqual(len(issue.created_comments), 0)
        self.assertEqual(existing.edit_calls, [f"{MARKER}\nnew review"])


if __name__ == "__main__":
    unittest.main()
