import os
import sys
import types
import unittest
from unittest.mock import patch


fake_boto3 = types.ModuleType("boto3")
setattr(fake_boto3, "client", lambda *args, **kwargs: None)
sys.modules.setdefault("boto3", fake_boto3)

fake_botocore = types.ModuleType("botocore")
fake_botocore_exceptions = types.ModuleType("botocore.exceptions")
setattr(fake_botocore_exceptions, "ClientError", type("ClientError", (Exception,), {}))
sys.modules.setdefault("botocore", fake_botocore)
sys.modules.setdefault("botocore.exceptions", fake_botocore_exceptions)

from src.utils.config import is_repo_allowed  # noqa: E402


class RepoAllowlistSecurityTests(unittest.TestCase):
    def test_empty_allowlist_fails_closed(self):
        with patch.dict(os.environ, {"ALLOWED_REPOS": ""}, clear=False):
            self.assertFalse(is_repo_allowed("time4116/bedrock-pr-agent"))

    def test_explicit_wildcard_allows_all_repos(self):
        with patch.dict(os.environ, {"ALLOWED_REPOS": "*"}, clear=False):
            self.assertTrue(is_repo_allowed("time4116/bedrock-pr-agent"))

    def test_named_repo_allows_case_insensitive_match(self):
        with patch.dict(os.environ, {"ALLOWED_REPOS": "time4116/bedrock-pr-agent"}, clear=False):
            self.assertTrue(is_repo_allowed("Time4116/Bedrock-PR-Agent"))
            self.assertFalse(is_repo_allowed("other/repo"))


if __name__ == "__main__":
    unittest.main()
