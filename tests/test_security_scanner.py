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


def test_scan_diff_flags_remote_script_piped_to_shell():
    diff = """diff --git a/install.sh b/install.sh
--- a/install.sh
+++ b/install.sh
@@ -1,2 +1,3 @@
+curl -fsSL https://example.test/install.sh | bash
+wget -qO- https://example.test/bootstrap.sh | sh
+curl -fsSL https://example.test/install.sh > install.sh
+curl -fsSL https://example.test/archive.tgz -o archive.tgz
"""

    result = scan_diff_for_security_findings(diff)

    findings = [
        finding for finding in result["findings"] if finding["rule_id"] == "curl-pipe-shell"
    ]
    assert len(findings) == 2
    assert {finding["line_number"] for finding in findings} == {1, 2}
    assert not any("install.sh > install.sh" in finding["line"] for finding in findings)
    assert not any("archive.tgz" in finding["line"] for finding in findings)


def test_scan_diff_advances_line_numbers_after_matched_added_lines():
    diff = """diff --git a/app/routes.py b/app/routes.py
--- a/app/routes.py
+++ b/app/routes.py
@@ -8,2 +10,3 @@
+eval(request.args["expr"])
+api_key = "1234567890abcdef1234567890abcdef"
+safe_value = "not a finding"
"""

    result = scan_diff_for_security_findings(diff)

    locations = {
        finding["rule_id"]: finding["line_number"] for finding in result["findings"]
    }
    assert locations == {
        "dynamic-code-execution": 10,
        "hardcoded-secret": 11,
    }


def test_sql_interpolation_requires_sql_and_interpolation_in_same_statement():
    diff = """diff --git a/app/reports.py b/app/reports.py
--- a/app/reports.py
+++ b/app/reports.py
@@ -1,2 +1,3 @@
+logger.info("SELECT examples should use parameters", f"user={user_id}")
+query = f"SELECT * FROM users WHERE id = {user_id}"
+db.execute("DELETE FROM users WHERE id = %s", [user_id])
"""

    result = scan_diff_for_security_findings(diff)

    sql_findings = [
        finding for finding in result["findings"] if finding["rule_id"] == "sql-string-interpolation"
    ]
    assert [finding["line_number"] for finding in sql_findings] == [2]
    assert "logger.info" not in sql_findings[0]["line"]


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
