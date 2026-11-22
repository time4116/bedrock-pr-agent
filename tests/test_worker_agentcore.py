"""SQS must retry AgentCore failures instead of acknowledging their messages."""

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def worker(monkeypatch):
    client = Mock()
    boto3 = types.ModuleType("boto3")
    setattr(boto3, "client", Mock(return_value=client))
    botocore_config = types.ModuleType("botocore.config")
    setattr(botocore_config, "Config", Mock(return_value=object()))
    monkeypatch.setenv("AGENT_ARN", "arn:aws:bedrock-agentcore:example")
    module_path = Path(__file__).resolve().parents[1] / "src/handlers/worker_agentcore.py"
    spec = importlib.util.spec_from_file_location("worker_under_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"boto3": boto3, "botocore.config": botocore_config}):
        spec.loader.exec_module(module)
    return module, client


def _event(event_name="pull_request"):
    return {
        "Records": [
            {
                "messageId": "message-1",
                "body": json.dumps(
                    {
                        "event_name": event_name,
                        "payload": {
                            "pull_request": {"number": 42},
                            "repository": {"full_name": "time4116/example"},
                            "installation": {"id": 123},
                        },
                    }
                ),
            }
        ]
    }


def _response(result):
    return {"response": [json.dumps(result).encode()]}


def test_invocation_exception_reaches_sqs_handler(worker):
    module, client = worker
    failure = RuntimeError("AgentCore unavailable")
    client.invoke_agent_runtime.side_effect = failure

    with pytest.raises(RuntimeError, match="AgentCore unavailable") as caught:
        module.handler(_event(), None)

    assert caught.value is failure
    client.invoke_agent_runtime.assert_called_once()


def test_token_limit_exception_reaches_sqs_handler(worker):
    module, client = worker
    client.invoke_agent_runtime.side_effect = RuntimeError("max_tokens exceeded")

    with pytest.raises(RuntimeError, match="max_tokens exceeded"):
        module.handler(_event(), None)


def test_agent_error_result_reaches_sqs_handler(worker):
    module, client = worker
    client.invoke_agent_runtime.return_value = _response(
        {"status": "error", "error": "review failed"}
    )

    with pytest.raises(RuntimeError, match="review failed"):
        module.handler(_event(), None)


def test_invalid_agent_response_reaches_sqs_handler(worker):
    module, client = worker
    client.invoke_agent_runtime.return_value = {"response": [b"not json"]}

    with pytest.raises(json.JSONDecodeError):
        module.handler(_event(), None)


@pytest.mark.parametrize(
    "result",
    [{}, {"status": "failed", "error": "review failed"}, {"status": None}],
    ids=["missing-status", "unknown-status", "null-status"],
)
def test_unrecognized_agent_result_reaches_sqs_handler(worker, result):
    module, client = worker
    client.invoke_agent_runtime.return_value = _response(result)

    with pytest.raises(RuntimeError, match="AgentCore returned unexpected status"):
        module.handler(_event(), None)
    client.invoke_agent_runtime.assert_called_once()


@pytest.mark.parametrize("result", [None, [], "success", 42])
def test_malformed_agent_result_reaches_sqs_handler(worker, result):
    module, client = worker
    client.invoke_agent_runtime.return_value = _response(result)

    with pytest.raises(RuntimeError, match="AgentCore returned invalid result"):
        module.handler(_event(), None)
    client.invoke_agent_runtime.assert_called_once()


@pytest.mark.parametrize("status", ["success", "skipped"])
def test_completed_agent_result_is_acknowledged(worker, status):
    module, client = worker
    client.invoke_agent_runtime.return_value = _response({"status": status})

    assert json.loads(module.handler(_event(), None)["body"]) == {"status": "processed"}
    client.invoke_agent_runtime.assert_called_once()


def test_non_pr_event_is_acknowledged_without_invocation(worker):
    module, client = worker

    assert module.handler(_event("push"), None)["statusCode"] == 200
    client.invoke_agent_runtime.assert_not_called()
