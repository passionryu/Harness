import hashlib
import hmac
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

import orchestrator.api.routes as routes
import orchestrator.services.orchestration as orchestration
from orchestrator.main import app


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_github_plan_label_webhook_triggers_design_artifact(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_trigger_label", "ai-plan-ready")
    monkeypatch.setattr(routes.settings, "github_token", None)
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")

    issue_number = uuid4().int % 1_000_000_000
    payload = {
        "action": "labeled",
        "label": {"name": "ai-plan-ready"},
        "issue": {
            "number": issue_number,
            "title": "[FE] 회원 가입 기능 구현",
            "body": "회원가입 화면을 추가한다.",
            "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
            "labels": [{"name": "ai-plan-ready"}, {"name": "type: feFeature"}],
        },
    }
    body = json.dumps(payload).encode("utf-8")

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": _signature(secret, body),
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    result = response.json()
    assert result["current_state"] == "Design Artifact Ready"
    artifact_root = Path(tmp_path / "artifacts" / result["task_id"] / "plans")
    assert (artifact_root / "architecture.md").exists()
    assert (artifact_root / "work-units.md").exists()


def test_github_webhook_rejects_invalid_signature(monkeypatch):
    monkeypatch.setattr(routes.settings, "github_webhook_secret", "test-secret")

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/github",
            content=b"{}",
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": "sha256=bad",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 401


def test_issue_comment_develop_creates_codex_handoff(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "enable_github_comment_commands", True)
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", None)

    issue_number = uuid4().int % 1_000_000_000
    payload = {
        "action": "created",
        "issue": {
            "number": issue_number,
            "title": "[BE] 회원가입 API 구현",
            "body": "회원가입 API를 구현한다.",
            "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
            "labels": [{"name": "type: beFeature"}],
        },
        "comment": {"body": "@ai-harness develop"},
    }
    body = json.dumps(payload).encode("utf-8")

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, body),
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    result = response.json()
    assert result["current_state"] == "Codex Dev Handoff Ready"
    dev_dir = tmp_path / "artifacts" / result["task_id"] / "dev"
    assert (dev_dir / "codex-implementation-request.md").exists()
    assert "python_implementation_layer: removed" in (dev_dir / "codex-implementation-request.md").read_text(encoding="utf-8")


def test_issue_comment_commands_disabled_when_setting_is_off(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "enable_github_comment_commands", False)

    payload = {
        "action": "created",
        "issue": {"number": 1, "title": "[FE] 테스트", "body": "화면 수정"},
        "comment": {"body": "@ai-harness design"},
    }
    body = json.dumps(payload).encode("utf-8")

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, body),
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
