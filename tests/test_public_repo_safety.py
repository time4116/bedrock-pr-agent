import re
import subprocess
import unittest
from pathlib import Path


SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "account_specific_bedrock_arn": re.compile(
        r"arn:aws:bedrock:[a-z0-9-]+:\d{12}:inference-profile/"
    ),
}

ALLOWLISTED_PLACEHOLDERS = {
    "AWS_ACCOUNT=000000000000",
}


class PublicRepoSafetyTests(unittest.TestCase):
    def test_tracked_text_files_do_not_contain_high_confidence_secrets(self):
        repo_root = Path(__file__).resolve().parents[1]
        tracked_files = subprocess.check_output(
            ["git", "ls-files"], cwd=repo_root, text=True
        ).splitlines()

        findings = []
        for rel_path in tracked_files:
            path = repo_root / rel_path
            data = path.read_bytes()
            if b"\0" in data:
                continue
            text = data.decode("utf-8", errors="ignore")
            for name, pattern in SECRET_PATTERNS.items():
                for match in pattern.finditer(text):
                    snippet = match.group(0)
                    if snippet in ALLOWLISTED_PLACEHOLDERS:
                        continue
                    line = text.count("\n", 0, match.start()) + 1
                    findings.append(f"{rel_path}:{line}: {name}: {snippet[:32]}...")

        self.assertEqual(findings, [])

    def test_github_app_manifest_helper_uses_loopback_callback(self):
        repo_root = Path(__file__).resolve().parents[1]
        source = (repo_root / "scripts/create_github_app.py").read_text(encoding="utf-8")
        self.assertIn('HTTPServer(("127.0.0.1", port), Handler)', source)
        self.assertNotIn('HTTPServer(("0.0.0.0", port), Handler)', source)


if __name__ == "__main__":
    unittest.main()
