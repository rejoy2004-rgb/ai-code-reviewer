import hmac
import hashlib
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app
from app.config.settings import settings

client = TestClient(app)


def test_webhook_signature_validation_fails():
    # Send a request with no or invalid signature
    response = client.post(
        "/api/v1/webhooks/github",
        json={"action": "opened"},
        headers={"X-Hub-Signature-256": "sha256=invalid"}
    )
    assert response.status_code == 401


@patch("app.api.webhooks.run_review_workflow")
def test_webhook_signature_validation_succeeds(mock_run_workflow):
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 1,
            "title": "Fix bug",
            "head": {"sha": "123"},
            "base": {"sha": "456"},
            "user": {"login": "dev"}
        },
        "repository": {
            "name": "reviewer",
            "full_name": "owner/reviewer",
            "owner": {"login": "owner"}
        }
    }
    
    # Calculate valid HMAC SHA256 signature
    import json
    body_str = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    mac = hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode('utf-8'),
        msg=body_str,
        digestmod=hashlib.sha256
    )
    signature = f"sha256={mac.hexdigest()}"
    
    response = client.post(
        "/api/v1/webhooks/github",
        content=body_str,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "pull_request",
            "Content-Type": "application/json"
        }
    )
    
    assert response.status_code == 200
    assert "Review workflow scheduled" in response.json()["message"]
