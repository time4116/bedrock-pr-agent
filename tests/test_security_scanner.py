import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent.tools.security_scanner import (  # noqa: E402
    format_security_context,
    scan_diff_for_security_findings,
)


def test_scan_diff_finds_language_agnostic_high_confidence_risks():
    diff = """diff --git a/app/server.js b/app/server.js
--- a/app/server.js
+++ b/app/server.js
@@ -1,3 +1,8 @@
+app.get('/debug', (req, res) => eval(req.query.expr));
+const api_key = "1234567890abcdef1234567890abcdef";
+child_process.exec(`deploy ${req.query.env}`);
+fetch(url, { rejectUnauthorized: false });
+db.query(`SELECT * FROM users WHERE id = ${req.query.id}`);
 context line should not be scanned: eval(req.body.x)
-const old = "removed_fake_token_value";
"""

    result = scan_diff_for_security_findings(diff)

    assert result["success"] is True
    assert result["total_findings"] == 5
    rules = {finding["rule_id"] for finding in result["findings"]}
    assert rules == {
        "dynamic-code-execution",
        "hardcoded-secret",
        "shell-command-injection",
        "tls-verification-disabled",
        "sql-string-interpolation",
    }
    assert all(finding["file"] == "app/server.js" for finding in result["findings"])
    assert all(finding["line"].startswith("+") for finding in result["findings"])
    assert not any("context line" in finding["line"] for finding in result["findings"])
    assert not any("oldtoken" in finding["line"] for finding in result["findings"])


def test_security_context_is_compact_and_actionable():
    findings = {
        "success": True,
        "total_findings": 2,
        "findings": [
            {
                "severity": "high",
                "rule_id": "dynamic-code-execution",
                "title": "Dynamic code execution",
                "file": "app/server.js",
                "line_number": 12,
                "line": "+eval(req.query.expr)",
                "recommendation": "Avoid eval and use a safe parser or allowlist.",
            },
            {
                "severity": "medium",
                "rule_id": "tls-verification-disabled",
                "title": "TLS verification disabled",
                "file": "infra/main.tf",
                "line_number": 34,
                "line": "+insecure = true",
                "recommendation": "Keep TLS certificate verification enabled.",
            },
        ],
    }

    context = format_security_context(findings)

    assert "**Security scan findings**" in context
    assert "Dynamic code execution" in context
    assert "app/server.js:12" in context
    assert "Avoid eval" in context
    assert "TLS verification disabled" in context
    assert len(context) < 1200


def test_security_context_reports_clean_scan_without_extra_noise():
    context = format_security_context({"success": True, "total_findings": 0, "findings": []})

    assert context == "\n\n**Security scan findings**: No high-confidence diff security findings."
