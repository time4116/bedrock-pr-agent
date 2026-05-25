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

from src.utils.config import is_repo_allowed, is_security_scan_enabled  # noqa: E402


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


class SecurityScanFeatureFlagTests(unittest.TestCase):
    def test_security_scan_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(is_security_scan_enabled())

    def test_security_scan_can_be_disabled(self):
        for value in ("false", "0", "no", "off", "FALSE"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"SECURITY_SCAN_ENABLED": value}, clear=False):
                    self.assertFalse(is_security_scan_enabled())

    def test_security_scan_allows_truthy_values(self):
        for value in ("true", "1", "yes", "on", "anything-else"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"SECURITY_SCAN_ENABLED": value}, clear=False):
                    self.assertTrue(is_security_scan_enabled())


if __name__ == "__main__":
    unittest.main()
