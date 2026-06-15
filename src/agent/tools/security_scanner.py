"""Zero-cost, language-agnostic security checks over unified PR diffs.

This module intentionally avoids network calls and paid services. It looks only at
added lines in the unified diff and reports high-confidence patterns that are
useful context for the Bedrock review prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SecurityRule:
    rule_id: str
    title: str
    severity: str
    pattern: re.Pattern[str]
    recommendation: str


RULES: tuple[SecurityRule, ...] = (
    SecurityRule(
        rule_id="hardcoded-secret",
        title="Hardcoded secret or token",
        severity="high",
        pattern=re.compile(
            r"(?i)(gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{40,}|"
            r"AKIA[0-9A-Z]{16}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|"
            r"xox[baprs]-[A-Za-z0-9-]{20,}|npm_[A-Za-z0-9]{20,}|"
            r"(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{16,}['\"])",
        ),
        recommendation="Move secrets to a secret manager or CI secret and rotate any exposed value.",
    ),
    SecurityRule(
        rule_id="dynamic-code-execution",
        title="Dynamic code execution",
        severity="high",
        pattern=re.compile(
            r"(?i)(\beval\s*\(|(?<!\.)\bexec\s*\(|new\s+Function\s*\(|Function\s*\()"
        ),
        recommendation="Avoid dynamic execution; use a parser, allowlist, or explicit dispatch table.",
    ),
    SecurityRule(
        rule_id="shell-command-injection",
        title="Shell command injection risk",
        severity="high",
        pattern=re.compile(
            r"(?i)(shell\s*=\s*True|child_process\.(exec|execSync)\s*\(|"
            r"\bos\.system\s*\(|subprocess\.[A-Za-z_]+\s*\([^\n)]*shell\s*=\s*True|"
            r"Runtime\.getRuntime\(\)\.exec\s*\()"
        ),
        recommendation="Avoid shell interpolation; pass argument arrays and validate untrusted inputs.",
    ),
    SecurityRule(
        rule_id="curl-pipe-shell",
        title="Remote script piped to shell",
        severity="high",
        pattern=re.compile(r"(?i)\b(curl|wget)\b[^\n|;]*\|[^\n]*(sh|bash|zsh)\b"),
        recommendation="Download and verify remote scripts before execution; pin trusted installers by digest when possible.",
    ),
    SecurityRule(
        rule_id="tls-verification-disabled",
        title="TLS verification disabled",
        severity="medium",
        pattern=re.compile(
            r"(?i)(verify\s*=\s*False|rejectUnauthorized\s*:\s*false|"
            r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0|insecure_skip_verify\s*=\s*true|"
            r"curl\s+[^\n]*\s-k\b)"
        ),
        recommendation="Keep TLS certificate verification enabled except in tightly controlled tests.",
    ),
    SecurityRule(
        rule_id="sql-string-interpolation",
        title="SQL built with string interpolation",
        severity="high",
        pattern=re.compile(
            r"(?ix)("
            r"f['\"][^'\"\n]*(SELECT|INSERT|UPDATE|DELETE)\b[^'\"\n]*\{[^'\"\n]*['\"]|"
            r"`[^`\n]*(SELECT|INSERT|UPDATE|DELETE)\b[^`\n]*\$\{[^`\n]*`|"
            r"(SELECT|INSERT|UPDATE|DELETE)\b[^;\n]*(\.format\s*\(|\+\s*\w)"
            r")"
        ),
        recommendation="Use parameterized queries or a safe query builder instead of string interpolation.",
    ),
    SecurityRule(
        rule_id="docker-privileged-container",
        title="Privileged container enabled",
        severity="medium",
        pattern=re.compile(r"(?i)\bprivileged\s*[:=]\s*true\b"),
        recommendation="Avoid privileged containers unless required and tightly scoped.",
    ),
    SecurityRule(
        rule_id="permissive-cors",
        title="Permissive CORS origin",
        severity="medium",
        pattern=re.compile(
            r"(?i)(Access-Control-Allow-Origin['\"]?\s*[:=]\s*['\"]\*|allow_origins\s*=\s*\[[^\]]*['\"]\*)"
        ),
        recommendation="Restrict CORS origins to trusted domains when credentials or sensitive data are involved.",
    ),
)


_IGNORE_ADDED_PREFIXES = ("+++ ",)
_MAX_FINDINGS = 12


def _redact(line: str) -> str:
    redacted = re.sub(r"gh[pousr]_[A-Za-z0-9_]{8,}", "ghp_[REDACTED]", line)
    redacted = re.sub(r"github_pat_[A-Za-z0-9_]{12,}", "github_pat_[REDACTED]", redacted)
    redacted = re.sub(r"AKIA[0-9A-Z]{16}", "AKIA[REDACTED]", redacted)
    redacted = re.sub(r"sk-(?:proj-)?[A-Za-z0-9_-]{8,}", "sk-[REDACTED]", redacted)
    redacted = re.sub(r"xox[baprs]-[A-Za-z0-9-]{8,}", "xoxb-[REDACTED]", redacted)
    redacted = re.sub(
        r"(?i)((?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"])[^'\"]{8,}(['\"])",
        r"\1[REDACTED]\2",
        redacted,
    )
    return redacted[:240]


def scan_diff_for_security_findings(diff: str) -> dict[str, Any]:
    """Scan added lines in a unified diff for high-confidence security risks."""
    findings: list[dict[str, Any]] = []
    current_file = "unknown"
    new_line_number: int | None = None

    for raw_line in diff.splitlines():
        if raw_line.startswith("diff --git "):
            parts = raw_line.split()
            if len(parts) >= 4 and parts[3].startswith("b/"):
                current_file = parts[3][2:]
            new_line_number = None
            continue

        if raw_line.startswith("+++ b/"):
            current_file = raw_line.removeprefix("+++ b/")
            continue

        if raw_line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", raw_line)
            new_line_number = int(match.group(1)) if match else None
            continue

        if raw_line.startswith("+") and not raw_line.startswith(_IGNORE_ADDED_PREFIXES):
            line_number = new_line_number
            try:
                for rule in RULES:
                    if rule.pattern.search(raw_line):
                        findings.append(
                            {
                                "severity": rule.severity,
                                "rule_id": rule.rule_id,
                                "title": rule.title,
                                "file": current_file,
                                "line_number": line_number,
                                "line": _redact(raw_line),
                                "recommendation": rule.recommendation,
                            }
                        )
                        break
            finally:
                if new_line_number is not None:
                    new_line_number += 1
        elif raw_line.startswith("-"):
            continue
        elif new_line_number is not None:
            new_line_number += 1

        if len(findings) >= _MAX_FINDINGS:
            break

    return {
        "success": True,
        "total_findings": len(findings),
        "findings": findings,
        "truncated": len(findings) >= _MAX_FINDINGS,
    }


def format_security_context(results: dict[str, Any] | None) -> str:
    """Format scanner output as compact prompt context."""
    if not results or not results.get("success"):
        return (
            "\n\n**Security scan findings**: Security scan unavailable. Do not infer tool findings."
        )

    findings = results.get("findings") or []
    if not findings:
        return "\n\n**Security scan findings**: No high-confidence diff security findings."

    lines = [
        "\n\n**Security scan findings**:",
        (
            "Use these deterministic scanner results as grounded security context. "
            "Do not invent security findings beyond the diff and scanner output."
        ),
    ]
    for index, finding in enumerate(findings[:_MAX_FINDINGS], 1):
        location = f"{finding.get('file', 'unknown')}:{finding.get('line_number', '?')}"
        lines.append(
            f"{index}. [{finding.get('severity', 'unknown')}] {finding.get('title', 'Security finding')} "
            f"({finding.get('rule_id', 'rule')}) at {location}\n"
            f"   Line: `{finding.get('line', '')}`\n"
            f"   Recommendation: {finding.get('recommendation', 'Review and mitigate if exploitable.')}"
        )
    if results.get("truncated"):
        lines.append("Additional findings omitted to keep the prompt compact.")
    return "\n".join(lines)
