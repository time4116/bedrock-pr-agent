import base64
import hashlib
import hmac
import json
import sys
import types
from unittest.mock import patch


class _FakeS3Client:
    class exceptions:
        class NoSuchKey(Exception):
            pass


class _FakeSQSClient:
    def __init__(self):
        self.messages = []

    def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return {"MessageId": "msg-1"}


_fake_sqs = _FakeSQSClient()


def _fake_client(service_name, *args, **kwargs):
    if service_name == "sqs":
        return _fake_sqs
    if service_name == "s3":
        return _FakeS3Client()
    raise AssertionError(f"unexpected boto3 client: {service_name}")


fake_boto3 = types.ModuleType("boto3")
setattr(fake_boto3, "client", _fake_client)
sys.modules["boto3"] = fake_boto3

fake_botocore = types.ModuleType("botocore")
fake_botocore_exceptions = types.ModuleType("botocore.exceptions")
setattr(fake_botocore_exceptions, "ClientError", type("ClientError", (Exception,), {}))
sys.modules.setdefault("botocore", fake_botocore)
sys.modules.setdefault("botocore.exceptions", fake_botocore_exceptions)

from src.handlers import webhook  # noqa: E402


def _signature(payload: str, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _event(body: str, signature: str, encoded: bool = False):
    return {
        "body": base64.b64encode(body.encode()).decode() if encoded else body,
        "isBase64Encoded": encoded,
        "headers": {
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": signature,
        },
    }


def test_handler_decodes_base64_body_before_signature_verification(monkeypatch):
    monkeypatch.setenv("ALLOWED_REPOS", "time4116/example")
    payload = json.dumps(
        {
            "action": "opened",
            "repository": {"full_name": "time4116/example"},
            "pull_request": {"number": 42},
        }
    )

    with patch(
        "src.handlers.webhook.get_github_credentials", return_value={"webhook_secret": "secret"}
    ):
        response = webhook.handler(
            _event(payload, _signature(payload, "secret"), encoded=True), None
        )

    assert response["statusCode"] == 202
    assert json.loads(response["body"])["pr_number"] == 42


def test_handler_rejects_invalid_base64_body(monkeypatch):
    monkeypatch.setenv("ALLOWED_REPOS", "time4116/example")
    event = {
        "body": "not-valid-base64",
        "isBase64Encoded": True,
        "headers": {
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=ignored",
        },
    }

    response = webhook.handler(event, None)

    assert response["statusCode"] == 400
