import sys
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


fake_langchain_aws = types.ModuleType("langchain_aws")
setattr(fake_langchain_aws, "ChatBedrockConverse", object)
sys.modules.setdefault("langchain_aws", fake_langchain_aws)

fake_github = types.ModuleType("github")
setattr(fake_github, "Github", object)
setattr(fake_github, "Auth", types.SimpleNamespace(Token=lambda token: token))
setattr(fake_github, "GithubIntegration", object)
setattr(fake_github, "GithubException", type("GithubException", (Exception,), {"status": None}))
setattr(
    fake_github, "RateLimitExceededException", type("RateLimitExceededException", (Exception,), {})
)
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

fake_langchain_core = types.ModuleType("langchain_core")
fake_messages = types.ModuleType("langchain_core.messages")
setattr(fake_messages, "HumanMessage", lambda content: types.SimpleNamespace(content=content))
sys.modules.setdefault("langchain_core", fake_langchain_core)
sys.modules.setdefault("langchain_core.messages", fake_messages)

fake_langgraph = types.ModuleType("langgraph")
fake_graph = types.ModuleType("langgraph.graph")
setattr(fake_graph, "END", "END")
setattr(fake_graph, "StateGraph", object)
sys.modules.setdefault("langgraph", fake_langgraph)
sys.modules.setdefault("langgraph.graph", fake_graph)

from src.agent.graph import _build_review_prompt, _route_after_fetch_diff  # noqa: E402
from src.agent.state import PRReviewState  # noqa: E402


def test_review_prompt_includes_security_context():
    prompt = _build_review_prompt(
        repo_full="time4116/example",
        pr_number=42,
        pr_title="Add debug endpoint",
        pr_body="Adds a temporary endpoint.",
        diff="+eval(req.query.expr)",
        diff_stats={"files_changed": 1, "additions": 1, "deletions": 0, "truncated": False},
        terraform_results=None,
        security_results={
            "success": True,
            "total_findings": 1,
            "findings": [
                {
                    "severity": "high",
                    "rule_id": "dynamic-code-execution",
                    "title": "Dynamic code execution",
                    "file": "app/server.js",
                    "line_number": 12,
                    "line": "+eval(req.query.expr)",
                    "recommendation": "Avoid eval and use a safe parser or allowlist.",
                }
            ],
        },
    )

    assert "**Security scan findings**" in prompt
    assert "Dynamic code execution" in prompt
    assert "app/server.js:12" in prompt
    assert "Do not invent security findings" in prompt


def test_review_template_includes_dedicated_security_section():
    prompt = _build_review_prompt(
        repo_full="time4116/example",
        pr_number=42,
        pr_title="Add debug endpoint",
        pr_body="Adds a temporary endpoint.",
        diff="+eval(req.query.expr)",
        diff_stats={"files_changed": 1, "additions": 1, "deletions": 0, "truncated": False},
        terraform_results=None,
        security_results={"success": True, "total_findings": 0, "findings": []},
    )

    assert "### Security scan" in prompt
    assert "{SECURITY_FINDINGS}" in prompt
    assert "{SECURITY_FINDINGS}: Summarize deterministic scanner results" in prompt


def test_terraform_review_template_includes_security_section_before_infrastructure():
    prompt = _build_review_prompt(
        repo_full="time4116/example",
        pr_number=42,
        pr_title="Update infra",
        pr_body="Changes Terraform.",
        diff="+resource \"aws_s3_bucket\" \"example\" {}",
        diff_stats={"files_changed": 1, "additions": 1, "deletions": 0, "truncated": False},
        terraform_results={"success": True, "terraform_plans": []},
        security_results={"success": True, "total_findings": 0, "findings": []},
    )

    assert prompt.index("### Security scan") < prompt.index("### Infrastructure changes")


def test_standard_review_template_omits_terraform_section_and_instruction():
    prompt = _build_review_prompt(
        repo_full="time4116/example",
        pr_number=42,
        pr_title="Docs only",
        pr_body="Updates docs.",
        diff="+README update",
        diff_stats={"files_changed": 1, "additions": 1, "deletions": 0, "truncated": False},
        terraform_results=None,
        security_results={"success": True, "total_findings": 0, "findings": []},
    )

    assert "### Infrastructure changes" not in prompt
    assert "{TERRAFORM_ENVIRONMENT_ANALYSIS}" not in prompt
    assert "Terraform validation not enabled" not in prompt


def test_review_prompt_omits_security_context_when_scan_did_not_run():
    prompt = _build_review_prompt(
        repo_full="time4116/example",
        pr_number=42,
        pr_title="Docs only",
        pr_body="Updates docs.",
        diff="+README update",
        diff_stats={"files_changed": 1, "additions": 1, "deletions": 0, "truncated": False},
        terraform_results=None,
        security_results=None,
    )

    assert "**Security scan findings**" not in prompt
    assert "Security scan unavailable" not in prompt


def _minimal_state() -> PRReviewState:
    return {
        "installation_id": 1,
        "owner": "time4116",
        "repo": "example",
        "pr_number": 42,
        "pr_title": "Title",
        "pr_body": "Body",
        "head_sha": "abc123",
        "pr_diff": None,
        "diff_stats": None,
        "terraform_results": None,
        "security_results": None,
        "analysis": None,
        "comment_posted": False,
        "error": None,
    }


def test_fetch_route_runs_security_scan_by_default():
    with patch.dict("os.environ", {}, clear=True):
        assert _route_after_fetch_diff(_minimal_state()) == "scan_security"


def test_fetch_route_skips_security_scan_when_disabled():
    with patch.dict("os.environ", {"SECURITY_SCAN_ENABLED": "false"}, clear=True):
        assert _route_after_fetch_diff(_minimal_state()) == "analyze_and_comment"


def test_fetch_route_preserves_terraform_validation_when_security_scan_disabled():
    with patch.dict(
        "os.environ",
        {
            "SECURITY_SCAN_ENABLED": "false",
            "TERRAFORM_VALIDATION_REPOS": "time4116/example",
        },
        clear=True,
    ):
        assert _route_after_fetch_diff(_minimal_state()) == "validate_terraform"
