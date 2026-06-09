import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from git import Repo

import orchestrator.api.routes as routes
import orchestrator.services.orchestration as orchestration
import agents.qa_agent as qa_agent
from orchestrator.main import app


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


# 테스트에서 사람 승인 gate를 명시적으로 통과시킨다.
def _approve_issue_stage(issue_number: int, stage: str) -> None:
    from orchestrator.api.schemas import HumanApproval
    from orchestrator.db.session import SessionLocal
    from orchestrator.services.orchestration import OrchestrationService

    with SessionLocal() as db:
        OrchestrationService(db).approve_stage_for_github_issue(
            issue_number,
            stage,
            HumanApproval(approved_by="test", notes=f"{stage} 승인 테스트"),
        )


def test_github_plan_label_webhook_triggers_plan(tmp_path, monkeypatch):
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
            "labels": [{"name": "ai-plan-ready"}],
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
    assert result["current_state"] == "Plan Review"
    assert "Design Agent 실행이 완료" in result["message"]

    artifact_root = Path(tmp_path / "artifacts" / result["task_id"] / "plans")
    assert (artifact_root / "architecture.md").exists()
    assert (artifact_root / "sequence-diagram.md").exists()
    assert (artifact_root / "flow.md").exists()
    assert (artifact_root / "flow-chart.md").exists()
    assert (artifact_root / "edge-case-checklist.md").exists()
    assert "Implementation Steps" in (artifact_root / "architecture.md").read_text()


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


def test_github_issue_comment_commands_are_disabled_when_setting_is_off(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "enable_github_comment_commands", False)

    payload = {
        "action": "created",
        "issue": {
            "number": 1,
            "title": "[FE] 회원 가입 기능 구현",
            "body": "회원가입 화면을 추가한다.",
            "html_url": "https://github.com/passionryu/targetApp/issues/1",
        },
        "comment": {"body": "@ai-harness plan"},
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
    assert response.json() == {
        "status": "ignored",
        "reason": "GitHub 댓글 명령 추적은 비활성화되어 있습니다.",
    }


def test_plan_comment_contains_reviewable_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")

    captured: dict[str, str] = {}

    class FakeGitHubAdapter:
        def __init__(self, token: str):
            self.token = token

        def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
            captured["body"] = body

    monkeypatch.setattr(orchestration.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "github_owner", "passionryu")
    monkeypatch.setattr(orchestration.settings, "github_repo", "targetApp")
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    from orchestrator.db.session import SessionLocal, create_db
    from orchestrator.services.orchestration import OrchestrationService

    issue_number = uuid4().int % 1_000_000_000
    create_db()
    with SessionLocal() as db:
        service = OrchestrationService(db)
        event = service.run_plan_for_github_issue(
            issue_number=issue_number,
            title="[FE] 회원 가입 기능 구현",
            body="\n".join(
                [
                    "## 목표",
                    "회원가입 화면을 추가한다.",
                    "",
                    "## 작업 범위",
                    "- 회원가입 진입 버튼 또는 링크 추가",
                    "- 회원가입 화면/페이지 생성",
                    "",
                    "## 완료 기준",
                    "- 사용자가 회원가입 화면으로 이동할 수 있다.",
                ]
            ),
            issue_url=f"https://github.com/passionryu/targetApp/issues/{issue_number}",
        )

    assert event.message == "Design Agent 실행이 완료되어 Plan Review에서 사람 승인을 기다립니다."
    assert "### 구현 요약" in captured["body"]
    assert "### 변경 대상" in captured["body"]
    assert "### 구현 순서" in captured["body"]
    assert "### 검증 기준" in captured["body"]
    assert "### 결정 필요 질문" in captured["body"]
    assert "### 시퀀스 다이어그램" in captured["body"]
    assert "### 플로우 차트" in captured["body"]
    assert "### 다음 추천 명령어" in captured["body"]
    assert "`harness approve --issue" in captured["body"]
    assert "`@ai-harness redesign`" in captured["body"]


def test_config_plan_omits_usecase_diagrams(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")

    captured: dict[str, str] = {}

    class FakeGitHubAdapter:
        def __init__(self, token: str):
            self.token = token

        def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
            captured["body"] = body

    monkeypatch.setattr(orchestration.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "github_owner", "passionryu")
    monkeypatch.setattr(orchestration.settings, "github_repo", "myMentalCare")
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    from orchestrator.db.session import SessionLocal, create_db
    from orchestrator.services.orchestration import OrchestrationService

    issue_number = uuid4().int % 1_000_000_000
    create_db()
    with SessionLocal() as db:
        service = OrchestrationService(db)
        event = service.run_plan_for_github_issue(
            issue_number=issue_number,
            title="[Config] Spring Security + JWT + Redis 인증 기반 설정",
            body="\n".join(
                [
                    "## 목표",
                    "Spring Security, JWT, Redis 기반 인증 설정을 추가한다.",
                    "",
                    "## 완료 기준",
                    "- 백엔드가 정상 기동한다.",
                    "- 인증 설정 테스트가 통과한다.",
                ]
            ),
            issue_url=f"https://github.com/passionryu/myMentalCare/issues/{issue_number}",
            issue_labels=["type: config"],
        )

    plan_dir = tmp_path / "artifacts" / event.task_id / "plans"
    architecture = (plan_dir / "architecture.md").read_text()

    assert (plan_dir / "architecture.md").exists()
    assert (plan_dir / "work-units.md").exists()
    assert (plan_dir / "edge-case-checklist.md").exists()
    assert not (plan_dir / "sequence-diagram.md").exists()
    assert not (plan_dir / "flow.md").exists()
    assert not (plan_dir / "flow-chart.md").exists()
    assert "## Proposed" not in architecture
    assert "### 시퀀스 다이어그램" not in captured["body"]
    assert "### 플로우 차트" not in captured["body"]
    assert "sequence-diagram.md" not in captured["body"]
    assert "flow-chart.md" not in captured["body"]
    assert "환경변수 또는 secret 관리 위치는 어디로 확정할 것인가?" in captured["body"]


def test_github_comment_falls_back_to_gh_cli_when_api_forbidden(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    captured: dict[str, str] = {}

    class ForbiddenGitHubAdapter:
        def __init__(self, token: str):
            self.token = token

        def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
            raise RuntimeError("403 Forbidden")

    # gh CLI fallback이 받은 body-file 내용을 캡처한다.
    def fake_run(command, capture_output, text, timeout, check):
        captured["command"] = " ".join(command)
        captured["body"] = Path(command[-1]).read_text()
        return SimpleNamespace(returncode=0, stderr="", stdout="commented")

    monkeypatch.setattr(orchestration.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "github_owner", "passionryu")
    monkeypatch.setattr(orchestration.settings, "github_repo", "myMentalCare")
    monkeypatch.setattr(orchestration, "GitHubAdapter", ForbiddenGitHubAdapter)
    monkeypatch.setattr(orchestration.subprocess, "run", fake_run)

    from orchestrator.db.session import SessionLocal, create_db
    from orchestrator.services.orchestration import OrchestrationService

    issue_number = uuid4().int % 1_000_000_000
    create_db()
    with SessionLocal() as db:
        service = OrchestrationService(db)
        event = service.run_plan_for_github_issue(
            issue_number=issue_number,
            title="[Config] 인증 기반 설정",
            body="## 목표\nSpring Security와 JWT 설정을 추가한다.",
            issue_url=f"https://github.com/passionryu/myMentalCare/issues/{issue_number}",
        )

    assert event.current_state == "Plan Review"
    assert f"gh issue comment {issue_number}" in captured["command"]
    assert "# 🏗️ AI Design:" in captured["body"]
    assert "Spring Security와 JWT 설정을 추가한다." in captured["body"]


def test_issue_comment_replan_command_forces_new_plan(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "replan_command", "@ai-harness replan")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", None)

    issue_number = uuid4().int % 1_000_000_000
    payload = {
        "action": "created",
        "issue": {
            "number": issue_number,
            "title": "[FE] 회원 가입 기능 구현",
            "body": "\n".join(
                [
                    "## 목표",
                    "회원가입 화면을 추가한다.",
                    "",
                    "## 작업 범위",
                    "- 회원가입 화면/페이지 생성",
                    "",
                    "## 완료 기준",
                    "- 사용자가 회원가입 화면으로 이동할 수 있다.",
                ]
            ),
            "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
        },
        "comment": {
            "body": "\n".join(
                [
                    "@ai-harness replan",
                    "",
                    "- 회원가입은 별도 페이지가 아니라 모달로 만든다.",
                    "- 전화번호 필드는 제외한다.",
                ]
            )
        },
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
    assert "Design Agent 실행이 완료" in result["message"]

    architecture = (
        tmp_path / "artifacts" / result["task_id"] / "plans" / "architecture.md"
    ).read_text()
    assert "Human Replan Request" in architecture
    assert "모달로 만든다" in architecture
    assert "전화번호 필드는 제외한다" in architecture


def test_issue_comment_plan_command_triggers_initial_plan(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", None)

    issue_number = uuid4().int % 1_000_000_000
    payload = {
        "action": "created",
        "issue": {
            "number": issue_number,
            "title": "[FE] 회원 가입 기능 구현",
            "body": "회원가입 화면을 추가한다.",
            "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
            "labels": [{"name": "type: feFeature"}],
        },
        "comment": {"body": "@ai-harness plan"},
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
    assert "Design Agent 실행이 완료" in result["message"]
    architecture = tmp_path / "artifacts" / result["task_id"] / "plans" / "architecture.md"
    assert architecture.exists()
    assert "## Issue Type\nfeFeature" in architecture.read_text()


def test_issue_comment_status_command_comments_current_state(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(routes.settings, "status_command", "@ai-harness status")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")

    captured_comments: list[str] = []

    class FakeGitHubAdapter:
        def __init__(self, token: str):
            self.token = token

        def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
            captured_comments.append(body)

    monkeypatch.setattr(orchestration.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "github_owner", "passionryu")
    monkeypatch.setattr(orchestration.settings, "github_repo", "targetApp")
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    issue_number = uuid4().int % 1_000_000_000
    issue = {
        "number": issue_number,
        "title": "[FE] 회원 가입 기능 구현",
        "body": "회원가입 화면을 추가한다.",
        "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
        "labels": [{"name": "type: feFeature"}],
    }

    with TestClient(app) as client:
        plan_payload = {"action": "created", "issue": issue, "comment": {"body": "@ai-harness plan"}}
        plan_body = json.dumps(plan_payload).encode("utf-8")
        client.post(
            "/webhooks/github",
            content=plan_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, plan_body),
                "Content-Type": "application/json",
            },
        )

        status_payload = {
            "action": "created",
            "issue": issue,
            "comment": {"body": "@ai-harness status"},
        }
        status_body = json.dumps(status_payload).encode("utf-8")
        response = client.post(
            "/webhooks/github",
            content=status_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, status_body),
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "📍 AI Harness Status" in captured_comments[-1]
    assert "- state: `Plan Review`" in captured_comments[-1]
    assert "마지막 Agent 실행" in captured_comments[-1]
    assert "harness approve --stage plan" in captured_comments[-1]


def test_issue_comment_cancel_command_marks_task_cancelled(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(routes.settings, "cancel_command", "@ai-harness cancel")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")

    captured_comments: list[str] = []

    class FakeGitHubAdapter:
        def __init__(self, token: str):
            self.token = token

        def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
            captured_comments.append(body)

    monkeypatch.setattr(orchestration.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "github_owner", "passionryu")
    monkeypatch.setattr(orchestration.settings, "github_repo", "targetApp")
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    issue_number = uuid4().int % 1_000_000_000
    issue = {
        "number": issue_number,
        "title": "[BE] 회원가입 API 구현",
        "body": "회원가입 API를 추가한다.",
        "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
        "labels": [{"name": "type: beFeature"}],
    }

    with TestClient(app) as client:
        plan_payload = {"action": "created", "issue": issue, "comment": {"body": "@ai-harness plan"}}
        plan_body = json.dumps(plan_payload).encode("utf-8")
        client.post(
            "/webhooks/github",
            content=plan_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, plan_body),
                "Content-Type": "application/json",
            },
        )

        cancel_payload = {
            "action": "created",
            "issue": issue,
            "comment": {"body": "@ai-harness cancel\n\n잘못된 방향이라 중지"},
        }
        cancel_body = json.dumps(cancel_payload).encode("utf-8")
        response = client.post(
            "/webhooks/github",
            content=cancel_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, cancel_body),
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "AI Harness 작업 중지" in captured_comments[-1]
    assert "- current: `Cancelled`" in captured_comments[-1]
    assert "잘못된 방향이라 중지" in captured_comments[-1]


def test_plan_agent_uses_backend_feature_profile(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", None)

    issue_number = uuid4().int % 1_000_000_000
    payload = {
        "action": "created",
        "issue": {
            "number": issue_number,
            "title": "[BE] 스터디 생성 API 구현",
            "body": "\n".join(
                [
                    "### 목표",
                    "사용자가 스터디를 생성할 수 있는 API를 만든다.",
                    "",
                    "### 완료 기준",
                    "- 스터디 생성 API가 정상 응답한다.",
                    "- 서버 빌드가 통과한다.",
                ]
            ),
            "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
            "labels": [{"name": "type: beFeature"}],
        },
        "comment": {"body": "@ai-harness plan"},
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
    architecture = (
        tmp_path / "artifacts" / result["task_id"] / "plans" / "architecture.md"
    ).read_text()
    sequence = (
        tmp_path / "artifacts" / result["task_id"] / "plans" / "sequence-diagram.md"
    ).read_text()
    assert "## Issue Type\nbeFeature" in architecture
    assert "apps/server/modules/application 하위 usecase" in architecture
    assert "트랜잭션 경계와 repository port를 확정한다." in architecture
    assert "participant Service as 서비스" in sequence
    assert "도메인 정책" in sequence
    assert "Controller" not in sequence
    assert "UseCase" not in sequence


def test_backend_plan_comment_uses_backend_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")

    captured: dict[str, str] = {}

    class FakeGitHubAdapter:
        def __init__(self, token: str):
            self.token = token

        def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
            captured["body"] = body

    monkeypatch.setattr(orchestration.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "github_owner", "passionryu")
    monkeypatch.setattr(orchestration.settings, "github_repo", "targetApp")
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    from orchestrator.db.session import SessionLocal, create_db
    from orchestrator.services.orchestration import OrchestrationService

    issue_number = uuid4().int % 1_000_000_000
    create_db()
    with SessionLocal() as db:
        service = OrchestrationService(db)
        service.run_plan_for_github_issue(
            issue_number=issue_number,
            title="[BE] 회원가입 API 구현",
            body="\n".join(
                [
                    "## 목표",
                    "회원가입 요청을 받아 신규 회원을 생성하는 API를 구현한다.",
                    "",
                    "## 완료 기준",
                    "- 이메일이 중복되지 않으면 회원이 생성된다.",
                    "- 비밀번호는 해싱되어 저장된다.",
                ]
            ),
            issue_url=f"https://github.com/passionryu/targetApp/issues/{issue_number}",
            issue_labels=["type: beFeature"],
        )

    assert "### 이슈 타입\nbeFeature" in captured["body"]
    assert "apps/server/modules/application 하위 usecase" in captured["body"]
    assert "회원가입 요청을 받아 신규 회원을 생성하는 API를 구현한다." in captured["body"]
    assert "도메인 정책" in captured["body"]
    assert "Controller" not in captured["body"]
    assert "UseCase" not in captured["body"]
    assert "apps/web/app/signup/page.tsx" not in captured["body"]
    assert "회원가입 진입 버튼" not in captured["body"]


def test_issue_comment_plan_command_skips_duplicate_successful_plan(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")

    captured_comments: list[str] = []

    class FakeGitHubAdapter:
        def __init__(self, token: str):
            self.token = token

        def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
            captured_comments.append(body)

    monkeypatch.setattr(orchestration.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "github_owner", "passionryu")
    monkeypatch.setattr(orchestration.settings, "github_repo", "targetApp")
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    issue_number = uuid4().int % 1_000_000_000
    payload = {
        "action": "created",
        "issue": {
            "number": issue_number,
            "title": "[FE] 회원 가입 기능 구현",
            "body": "회원가입 화면을 추가한다.",
            "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
        },
        "comment": {"body": "@ai-harness plan"},
    }

    with TestClient(app) as client:
        body = json.dumps(payload).encode("utf-8")
        first_response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, body),
                "Content-Type": "application/json",
            },
        )
        second_response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, body),
                "Content-Type": "application/json",
            },
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert "Design Agent 실행이 완료" in first_response.json()["message"]
    assert second_response.json()["message"] == "이미 Design이 완료되어 중복 실행을 스킵했습니다."
    assert len(captured_comments) == 1
    assert "AI Design" in captured_comments[-1]


def test_issue_comment_replan_updates_existing_plan_comment(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "replan_command", "@ai-harness replan")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")

    updated_comments: list[tuple[int, str]] = []
    deleted_comments: list[int] = []
    created_comments: list[str] = []

    class FakeGitHubAdapter:
        def __init__(self, token: str, use_gh_cli: bool = False):
            self.token = token
            self.use_gh_cli = use_gh_cli

        def is_configured(self) -> bool:
            return True

        def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict]:
            return [
                {"id": 101, "body": "<!-- ai-harness-generated -->\n\n# 🏗️ AI Design: old"},
                {"id": 102, "body": "<!-- ai-harness-generated -->\n\n# ♻️ 🏗️ AI Re-Design: older"},
            ]

        def update_issue_comment(self, owner: str, repo: str, comment_id: int, body: str) -> None:
            updated_comments.append((comment_id, body))

        def delete_issue_comment(self, owner: str, repo: str, comment_id: int) -> None:
            deleted_comments.append(comment_id)

        def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
            created_comments.append(body)

    monkeypatch.setattr(orchestration.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "github_owner", "passionryu")
    monkeypatch.setattr(orchestration.settings, "github_repo", "targetApp")
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    issue_number = uuid4().int % 1_000_000_000
    payload = {
        "action": "created",
        "issue": {
            "number": issue_number,
            "title": "[BE] 로그인 API 구현",
            "body": "로그인 API를 구현한다.",
            "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
        },
        "comment": {"body": "@ai-harness replan\n\n로그인 흐름을 더 구체화한다."},
    }

    with TestClient(app) as client:
        body = json.dumps(payload).encode("utf-8")
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
    assert created_comments == []
    assert updated_comments[0][0] == 102
    assert "# ♻️ 🏗️ AI Re-Design" in updated_comments[0][1]
    assert deleted_comments == [101]


def test_issue_comment_develop_command_approves_plan_and_runs_dev(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(routes.settings, "develop_command", "@ai-harness develop")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", None)
    monkeypatch.setattr(orchestration.settings, "development_base_branch", "main")
    target_repo = tmp_path / "targetApp"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (target_repo / "apps/web").mkdir(parents=True)
    (target_repo / "apps/web/package.json").write_text(
        json.dumps({"name": "@app/web", "private": True, "scripts": {}}),
        encoding="utf-8",
    )
    repo.index.add(["README.md", "apps/web/package.json"])
    repo.index.commit("Initial commit")
    monkeypatch.setattr(orchestration.settings, "target_repo_path", target_repo)

    issue_number = uuid4().int % 1_000_000_000
    expected_branch = f"feature(FE)-{issue_number}"
    issue = {
        "number": issue_number,
        "title": "[FE] 회원 가입 기능 구현",
        "body": "회원가입 화면을 추가한다.",
        "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
        "labels": [{"name": "type: feFeature"}],
    }

    with TestClient(app) as client:
        plan_payload = {"action": "created", "issue": issue, "comment": {"body": "@ai-harness plan"}}
        plan_body = json.dumps(plan_payload).encode("utf-8")
        plan_response = client.post(
            "/webhooks/github",
            content=plan_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, plan_body),
                "Content-Type": "application/json",
            },
        )

        _approve_issue_stage(issue_number, "plan")

        develop_payload = {
            "action": "created",
            "issue": issue,
            "comment": {"body": "@ai-harness develop"},
        }
        develop_body = json.dumps(develop_payload).encode("utf-8")
        develop_response = client.post(
            "/webhooks/github",
            content=develop_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, develop_body),
                "Content-Type": "application/json",
            },
        )

    assert plan_response.status_code == 200
    assert develop_response.status_code == 200
    result = develop_response.json()
    assert result["status"] == "failed"
    assert "frontend_implementation_runner" in result["reason"]
    assert "test_implementation_runner" in result["reason"]
    assert repo.active_branch.name == expected_branch
    task_id = plan_response.json()["task_id"]
    commit_plan = tmp_path / "artifacts" / task_id / "dev" / "commit-plan.md"
    dev_status = tmp_path / "artifacts" / task_id / "dev" / "dev-status.md"
    assert commit_plan.exists()
    assert dev_status.exists()
    assert expected_branch in commit_plan.read_text()
    assert "selected_runner: `frontend_implementation_runner, test_implementation_runner`" in (
        commit_plan.read_text()
    )
    assert "status: `needs_human`" in dev_status.read_text()
    assert (tmp_path / "artifacts" / task_id / "dev" / "frontend_implementation_runner.md").exists()
    assert (tmp_path / "artifacts" / task_id / "dev" / "test_implementation_runner.md").exists()
    assert (tmp_path / "artifacts" / task_id / "dev" / "implementation.patch").exists()
    assert (tmp_path / "artifacts" / task_id / "dev" / "test-report.md").exists()


def test_issue_comment_develop_command_without_plan_is_ignored(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "develop_command", "@ai-harness develop")
    monkeypatch.setattr(orchestration.settings, "github_token", None)

    issue_number = uuid4().int % 1_000_000_000
    payload = {
        "action": "created",
        "issue": {
            "number": issue_number,
            "title": "[FE] 회원 가입 기능 구현",
            "body": "회원가입 화면을 추가한다.",
            "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
            "labels": [{"name": "type: feFeature"}],
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
    assert response.json() == {
        "status": "ignored",
        "reason": "Design을 찾을 수 없습니다. 먼저 @ai-harness design을 실행하세요.",
    }


def test_fix_develop_command_is_deprecated(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "github_owner", "passionryu")
    monkeypatch.setattr(orchestration.settings, "github_repo", "targetApp")

    captured: dict[str, str] = {}

    class FakeGitHubAdapter:
        def __init__(self, token: str):
            self.token = token

        def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
            captured["body"] = body

    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    from orchestrator.db.models import Run, Task
    from orchestrator.db.session import SessionLocal, create_db
    from orchestrator.services.orchestration import OrchestrationService

    create_db()
    issue_number = uuid4().int % 1_000_000_000
    with SessionLocal() as db:
        task = Task(
            title="[FS] 로그인 아이디 기반 회원가입/로그인 구조를 추가한다.",
            body="\n".join(
                [
                    "## 목표",
                    "로그인 아이디 기반 회원가입/로그인 구조를 추가한다.",
                    "",
                    "## Harness Metadata",
                    f"- issue_number: {issue_number}",
                    "- labels: type: fullstackFeature",
                ]
            ),
            github_issue_number=issue_number,
            github_issue_url=f"https://github.com/passionryu/targetApp/issues/{issue_number}",
            state="Dev Review",
        )
        db.add(task)
        db.flush()
        db.add(
            Run(
                task_id=task.id,
                agent_name="dev",
                status="failed",
                summary="fullstack_runner가 Gradle 테스트에서 실패했습니다.",
                error="Kotlin/Spring 구현 후 Gradle 테스트가 실패했습니다.",
            )
        )
        db.commit()

        result = OrchestrationService(db).run_fix_develop_for_github_issue(
            issue_number=issue_number,
            title=task.title,
            body=task.body,
            issue_url=task.github_issue_url or "",
            issue_labels=["type: fullstackFeature"],
        )

    assert result["status"] == "deprecated"
    assert "fix-develop Agent는 deprecated되었습니다" in result["reason"]
    assert "fix-develop은 deprecated되었습니다" in captured["body"]
    assert "Dev Agent 내부 runner" in captured["body"]


def test_backend_develop_uses_kotlin_runner_and_generates_member_signup_files(
    tmp_path, monkeypatch
):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(routes.settings, "develop_command", "@ai-harness develop")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", None)
    monkeypatch.setattr(orchestration.settings, "development_base_branch", "main")
    target_repo = tmp_path / "targetApp"
    (target_repo / "apps/server").mkdir(parents=True)
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (target_repo / "apps/server/build.gradle.kts").write_text(
        "plugins { kotlin(\"jvm\") version \"2.0.0\" }\n",
        encoding="utf-8",
    )
    (target_repo / "apps/server/modules/bootstrap/app").mkdir(parents=True)
    (target_repo / "apps/server/modules/bootstrap/app/build.gradle.kts").write_text(
        "\n".join(
            [
                "dependencies {",
                '    implementation("org.springdoc:springdoc-openapi-starter-webmvc-ui:2.8.6")',
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    repo.index.add(
        [
            "README.md",
            "apps/server/build.gradle.kts",
            "apps/server/modules/bootstrap/app/build.gradle.kts",
        ]
    )
    repo.index.commit("Initial commit")
    monkeypatch.setattr(orchestration.settings, "target_repo_path", target_repo)

    issue_number = uuid4().int % 1_000_000_000
    issue = {
        "number": issue_number,
        "title": "[BE] 회원가입 API 구현",
        "body": "회원가입 API를 추가한다.",
        "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
        "labels": [{"name": "type: beFeature"}],
    }

    with TestClient(app) as client:
        plan_payload = {"action": "created", "issue": issue, "comment": {"body": "@ai-harness plan"}}
        plan_body = json.dumps(plan_payload).encode("utf-8")
        plan_response = client.post(
            "/webhooks/github",
            content=plan_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, plan_body),
                "Content-Type": "application/json",
            },
        )

        _approve_issue_stage(issue_number, "plan")

        develop_payload = {
            "action": "created",
            "issue": issue,
            "comment": {"body": "@ai-harness develop"},
        }
        develop_body = json.dumps(develop_payload).encode("utf-8")
        develop_response = client.post(
            "/webhooks/github",
            content=develop_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, develop_body),
                "Content-Type": "application/json",
            },
        )

    assert plan_response.status_code == 200
    assert develop_response.status_code == 200
    result = develop_response.json()
    assert result["status"] == "failed"
    assert "ddd_modeling_runner" in result["reason"]
    assert "api_implementation_runner" in result["reason"]
    assert "test_implementation_runner" in result["reason"]

    task_id = plan_response.json()["task_id"]
    dev_dir = tmp_path / "artifacts" / task_id / "dev"
    assert (
        "selected_runner: `ddd_modeling_runner, api_implementation_runner, test_implementation_runner`"
    ) in (dev_dir / "commit-plan.md").read_text()
    assert (dev_dir / "ddd_modeling_runner.md").exists()
    assert (dev_dir / "api_implementation_runner.md").exists()
    assert (dev_dir / "test_implementation_runner.md").exists()
    assert "자동 구현은 아직 수행하지 않습니다" in (
        dev_dir / "ddd_modeling_runner.md"
    ).read_text()
    assert "backend orchestration style skill: required" in (
        dev_dir / "backend-style-checklist.md"
    ).read_text()
    assert not (
        target_repo
        / "apps/server/modules/bootstrap/app/src/main/kotlin/com/example/server/bootstrap/presentation/member/MemberSignupController.kt"
    ).exists()


def test_issue_comment_develop_command_continues_from_in_progress(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(routes.settings, "develop_command", "@ai-harness develop")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", None)
    monkeypatch.setattr(orchestration.settings, "development_base_branch", "main")
    target_repo = tmp_path / "targetApp"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (target_repo / "apps/web").mkdir(parents=True)
    (target_repo / "apps/web/package.json").write_text(
        json.dumps({"name": "@app/web", "private": True, "scripts": {}}),
        encoding="utf-8",
    )
    repo.index.add(["README.md", "apps/web/package.json"])
    repo.index.commit("Initial commit")
    monkeypatch.setattr(orchestration.settings, "target_repo_path", target_repo)

    original_run_agent = orchestration.OrchestrationService._run_agent

    def fake_run_agent(self, task, agent_name):
        from orchestrator.db.models import Run

        if agent_name != "dev":
            return original_run_agent(self, task, agent_name)

        run = Run(
            task_id=task.id,
            agent_name=agent_name,
            status="success",
            summary="테스트용 Dev Agent 실행 성공",
        )
        self.db.add(run)
        self.db.flush()
        return run.id

    monkeypatch.setattr(orchestration.OrchestrationService, "_run_agent", fake_run_agent)

    issue_number = uuid4().int % 1_000_000_000
    issue = {
        "number": issue_number,
        "title": "[FE] 회원 가입 기능 구현",
        "body": "회원가입 화면을 추가한다.",
        "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
        "labels": [{"name": "type: feFeature"}],
    }

    with TestClient(app) as client:
        plan_payload = {"action": "created", "issue": issue, "comment": {"body": "@ai-harness plan"}}
        plan_body = json.dumps(plan_payload).encode("utf-8")
        plan_response = client.post(
            "/webhooks/github",
            content=plan_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, plan_body),
                "Content-Type": "application/json",
            },
        )
        assert plan_response.status_code == 200
        _approve_issue_stage(issue_number, "plan")

        develop_payload = {"action": "created", "issue": issue, "comment": {"body": "@ai-harness develop"}}
        develop_body = json.dumps(develop_payload).encode("utf-8")
        develop_response = client.post(
            "/webhooks/github",
            content=develop_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, develop_body),
                "Content-Type": "application/json",
            },
        )
        assert develop_response.status_code == 200

        for command in ["@ai-harness develop"]:
            payload = {"action": "created", "issue": issue, "comment": {"body": command}}
            body = json.dumps(payload).encode("utf-8")
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

        continue_payload = {
            "action": "created",
            "issue": issue,
            "comment": {"body": "@ai-harness develop"},
        }
        continue_body = json.dumps(continue_payload).encode("utf-8")
        continue_response = client.post(
            "/webhooks/github",
            content=continue_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, continue_body),
                "Content-Type": "application/json",
            },
        )

    assert continue_response.status_code == 200
    result = continue_response.json()
    assert result["previous_state"] == "Dev Review"
    assert result["current_state"] == "Dev Review"
    assert result["message"] == "Dev Agent와 Review Agent 실행이 완료되어 Dev Review에서 사람 승인을 기다립니다."


def test_issue_comment_refactor_command_applies_human_request(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(routes.settings, "develop_command", "@ai-harness develop")
    monkeypatch.setattr(routes.settings, "refactor_command", "@ai-harness refactor")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", None)
    monkeypatch.setattr(orchestration.settings, "development_base_branch", "main")
    target_repo = tmp_path / "targetApp"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (target_repo / "apps/web").mkdir(parents=True)
    (target_repo / "apps/web/package.json").write_text(
        json.dumps({"name": "@app/web", "private": True, "scripts": {}}),
        encoding="utf-8",
    )
    repo.index.add(["README.md", "apps/web/package.json"])
    repo.index.commit("Initial commit")
    monkeypatch.setattr(orchestration.settings, "target_repo_path", target_repo)

    original_run_agent = orchestration.OrchestrationService._run_agent

    def fake_develop_success_then_real_refactor(self, task, agent_name):
        from orchestrator.db.models import Run

        if agent_name != "dev" or self.has_successful_agent_run(task.id, "dev"):
            return original_run_agent(self, task, agent_name)

        run = Run(
            task_id=task.id,
            agent_name=agent_name,
            status="success",
            summary="테스트용 Dev Agent 실행 성공",
        )
        self.db.add(run)
        self.db.flush()
        return run.id

    monkeypatch.setattr(
        orchestration.OrchestrationService,
        "_run_agent",
        fake_develop_success_then_real_refactor,
    )

    issue_number = uuid4().int % 1_000_000_000
    issue = {
        "number": issue_number,
        "title": "[FE] 회원 가입 기능 구현",
        "body": "회원가입 화면을 추가한다.",
        "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
        "labels": [{"name": "type: feFeature"}],
    }

    with TestClient(app) as client:
        plan_payload = {"action": "created", "issue": issue, "comment": {"body": "@ai-harness plan"}}
        plan_body = json.dumps(plan_payload).encode("utf-8")
        plan_response = client.post(
            "/webhooks/github",
            content=plan_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, plan_body),
                "Content-Type": "application/json",
            },
        )
        assert plan_response.status_code == 200
        _approve_issue_stage(issue_number, "plan")

        develop_payload = {"action": "created", "issue": issue, "comment": {"body": "@ai-harness develop"}}
        develop_body = json.dumps(develop_payload).encode("utf-8")
        develop_response = client.post(
            "/webhooks/github",
            content=develop_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, develop_body),
                "Content-Type": "application/json",
            },
        )
        assert develop_response.status_code == 200

        refactor_payload = {
            "action": "created",
            "issue": issue,
            "comment": {
                "body": "\n".join(
                    [
                        "@ai-harness refactor",
                        "",
                        "- 컨트롤러는 얇게 유지한다.",
                        "- DTO는 별도 파일로 분리한다.",
                    ]
                )
            },
        }
        refactor_body = json.dumps(refactor_payload).encode("utf-8")
        refactor_response = client.post(
            "/webhooks/github",
            content=refactor_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, refactor_body),
                "Content-Type": "application/json",
            },
        )

    assert refactor_response.status_code == 200
    result = refactor_response.json()
    assert result["status"] == "failed"
    assert "refactoring_runner" in result["reason"]

    task_id = result["task_id"]
    dev_status = tmp_path / "artifacts" / task_id / "dev" / "dev-status.md"
    assert "mode: `refactor`" in dev_status.read_text()
    assert "컨트롤러는 얇게 유지한다" in dev_status.read_text()
    assert "DTO는 별도 파일로 분리한다" in dev_status.read_text()


def test_refactor_command_allows_successful_fix_develop_run(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", None)

    from orchestrator.db.models import Run, Task
    from orchestrator.db.session import SessionLocal, create_db
    from orchestrator.services.orchestration import OrchestrationService

    def fake_refactor_agent(self, task, agent_name):
        assert agent_name == "dev"
        run = Run(
            task_id=task.id,
            agent_name=agent_name,
            status="success",
            summary="리팩터링 실행 성공",
        )
        self.db.add(run)
        self.db.flush()
        return run.id

    monkeypatch.setattr(orchestration.OrchestrationService, "_run_agent", fake_refactor_agent)

    create_db()
    issue_number = uuid4().int % 1_000_000_000
    with SessionLocal() as db:
        task = Task(
            title="[FS] [기능 수정] 로그인 아이디 기반 회원가입/로그인 구조를 추가한다.",
            body="로그인 아이디 기반 회원가입/로그인 구조를 추가한다.",
            github_issue_number=issue_number,
            github_issue_url=f"https://github.com/passionryu/targetApp/issues/{issue_number}",
            state="QA Review",
        )
        db.add(task)
        db.flush()
        db.add_all(
            [
                Run(
                    task_id=task.id,
                    agent_name="dev",
                    status="failed",
                    summary="Gradle 테스트 실패",
                    error="Kotlin/Spring 구현 후 Gradle 테스트가 실패했습니다.",
                ),
                Run(
                    task_id=task.id,
                    agent_name="fix_develop",
                    status="success",
                    summary="개발 실패를 복구했습니다.",
                ),
            ]
        )
        db.commit()

        event = OrchestrationService(db).run_refactor_for_github_issue(
            issue_number=issue_number,
            title=task.title,
            body=task.body,
            issue_url=task.github_issue_url or "",
            refactor_request="DDD/Hexagonal 경계를 유지하며 구현을 정리한다.",
            issue_labels=["type: fullstackFeature"],
        )

    assert event.current_state == "Dev Review"
    assert event.message == "리팩터링 요청을 반영했고 Dev Review에서 사람 승인을 기다립니다."


def test_issue_comment_qa_command_runs_system_qa(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(routes.settings, "develop_command", "@ai-harness develop")
    monkeypatch.setattr(routes.settings, "qa_command", "@ai-harness qa")
    monkeypatch.setattr(routes.settings, "reqa_command", "@ai-harness re-qa")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", "test-token")
    monkeypatch.setattr(orchestration.settings, "allow_external_notifications", True)
    monkeypatch.setattr(
        orchestration.settings,
        "google_chat_webhook_url",
        "https://chat.googleapis.com/test-webhook",
    )
    monkeypatch.setattr(
        qa_agent,
        "_run_command",
        lambda command, cwd, timeout_seconds: (0, "회원가입 화면 smoke 검증 통과", ""),
    )
    monkeypatch.setattr(
        qa_agent,
        "_start_frontend_if_needed",
        lambda repo_path, timeout_seconds: (None, "테스트 프론트엔드 서버 사용"),
    )
    monkeypatch.setattr(qa_agent, "_is_frontend_alive", lambda: True)
    monkeypatch.setattr(
        qa_agent,
        "_verify_frontend_page_content",
        lambda timeout_seconds, markers: (
            True,
            f"url=http://localhost:3000, required_markers={markers}, missing_markers=없음",
            "<html>회원가입 로그인</html>",
            0,
            "",
        ),
    )
    captured_comments: list[str] = []
    captured_chat_messages: list[str] = []
    captured_discord_messages: list[str] = []

    class FakeGitHubAdapter:
        def __init__(self, token: str):
            self.token = token

        def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
            captured_comments.append(body)

    class FakeGoogleChatNotifier:
        def __init__(self, webhook_url: str | None):
            self.webhook_url = webhook_url

        def is_configured(self) -> bool:
            return bool(self.webhook_url)

        def send_text(self, text: str) -> None:
            captured_chat_messages.append(text)

    class FakeDiscordNotifier:
        def __init__(self, webhook_url: str | None):
            self.webhook_url = webhook_url

        def is_configured(self) -> bool:
            return bool(self.webhook_url)

        def send_text(self, text: str) -> None:
            captured_discord_messages.append(text)

        def send_text_with_file(self, text: str, file_path: Path, filename: str | None = None) -> None:
            captured_discord_messages.append(text)

    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)
    monkeypatch.setattr(orchestration, "GoogleChatNotifier", FakeGoogleChatNotifier)
    monkeypatch.setattr(orchestration, "DiscordNotifier", FakeDiscordNotifier)
    monkeypatch.setattr(
        orchestration.settings,
        "discord_webhook_url",
        "https://discord.com/api/webhooks/test/token",
    )

    target_repo = tmp_path / "targetApp"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (target_repo / "apps/web").mkdir(parents=True)
    (target_repo / "apps/web/package.json").write_text(
        json.dumps({"name": "@app/web", "private": True, "scripts": {}}),
        encoding="utf-8",
    )
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")
    monkeypatch.setattr(orchestration.settings, "target_repo_path", target_repo)

    original_run_agent = orchestration.OrchestrationService._run_agent

    def fake_dev_success_then_real_qa(self, task, agent_name):
        from orchestrator.db.models import Run

        if agent_name != "dev":
            return original_run_agent(self, task, agent_name)

        branch_name = f"feature(FE)-{task.github_issue_number}"
        if branch_name not in {head.name for head in repo.heads}:
            repo.git.checkout("-b", branch_name)
        else:
            repo.git.checkout(branch_name)
        dev_dir = orchestration.settings.artifact_root / task.id / "dev"
        dev_dir.mkdir(parents=True, exist_ok=True)
        for filename in ["commit-plan.md", "dev-status.md", "implementation.patch", "test-report.md"]:
            (dev_dir / filename).write_text(f"# {filename}\n", encoding="utf-8")
        (target_repo / "apps/web/app/signup").mkdir(parents=True, exist_ok=True)
        (target_repo / "apps/web/components/signup").mkdir(parents=True, exist_ok=True)
        (target_repo / "apps/web/lib").mkdir(parents=True, exist_ok=True)
        (target_repo / "apps/web/scripts").mkdir(parents=True, exist_ok=True)
        (target_repo / "apps/web/app/page.tsx").write_text("회원가입 로그인\n", encoding="utf-8")
        (target_repo / "apps/web/app/signup/page.tsx").write_text("SignupForm\n", encoding="utf-8")
        (target_repo / "apps/web/components/signup/signup-form.tsx").write_text(
            "confirmPassword interests\n",
            encoding="utf-8",
        )
        (target_repo / "apps/web/lib/signup-validation.ts").write_text(
            "비밀번호가 서로 일치하지 않습니다.\n",
            encoding="utf-8",
        )
        (target_repo / "apps/web/scripts/verify-signup-page.mjs").write_text(
            "console.log('회원가입 화면 smoke 검증 통과')\n",
            encoding="utf-8",
        )
        (target_repo / "apps/web/package.json").write_text(
            json.dumps({"name": "@app/web", "private": True, "scripts": {"test:signup": "node scripts/verify-signup-page.mjs"}}),
            encoding="utf-8",
        )
        run = Run(
            task_id=task.id,
            agent_name=agent_name,
            status="success",
            summary="테스트용 Dev Agent 실행 성공",
        )
        self.db.add(run)
        self.db.flush()
        return run.id

    monkeypatch.setattr(
        orchestration.OrchestrationService,
        "_run_agent",
        fake_dev_success_then_real_qa,
    )

    issue_number = uuid4().int % 1_000_000_000
    issue = {
        "number": issue_number,
        "title": "[FE] 회원 가입 기능 구현",
        "body": "회원가입 화면을 추가한다.",
        "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
        "labels": [{"name": "type: feFeature"}],
    }

    with TestClient(app) as client:
        plan_payload = {"action": "created", "issue": issue, "comment": {"body": "@ai-harness plan"}}
        plan_body = json.dumps(plan_payload).encode("utf-8")
        plan_response = client.post(
            "/webhooks/github",
            content=plan_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, plan_body),
                "Content-Type": "application/json",
            },
        )
        assert plan_response.status_code == 200
        _approve_issue_stage(issue_number, "plan")

        develop_payload = {"action": "created", "issue": issue, "comment": {"body": "@ai-harness develop"}}
        develop_body = json.dumps(develop_payload).encode("utf-8")
        develop_response = client.post(
            "/webhooks/github",
            content=develop_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, develop_body),
                "Content-Type": "application/json",
            },
        )
        assert develop_response.status_code == 200
        _approve_issue_stage(issue_number, "dev")

        qa_payload = {"action": "created", "issue": issue, "comment": {"body": "@ai-harness qa"}}
        qa_body = json.dumps(qa_payload).encode("utf-8")
        qa_response = client.post(
            "/webhooks/github",
            content=qa_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, qa_body),
                "Content-Type": "application/json",
            },
        )

        duplicate_qa_response = client.post(
            "/webhooks/github",
            content=qa_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, qa_body),
                "Content-Type": "application/json",
            },
        )

        reqa_payload = {
            "action": "created",
            "issue": issue,
            "comment": {"body": "@ai-harness re-qa"},
        }
        reqa_body = json.dumps(reqa_payload).encode("utf-8")
        reqa_response = client.post(
            "/webhooks/github",
            content=reqa_body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _signature(secret, reqa_body),
                "Content-Type": "application/json",
            },
        )

    assert qa_response.status_code == 200
    result = qa_response.json()
    assert result["previous_state"] == "QA Ready"
    assert result["current_state"] == "QA Review"
    assert result["message"] == "QA Agent 실행이 완료되어 QA Review에서 사람 승인을 기다립니다."
    qa_dir = tmp_path / "artifacts" / result["task_id"] / "qa"
    assert (qa_dir / "qa-report.md").exists()
    assert (qa_dir / "qa-checklist.md").exists()
    assert "test:signup 통과" in (qa_dir / "qa-report.md").read_text()
    assert "## Human QA 체크리스트" in (qa_dir / "qa-report.md").read_text()
    qa_comment = next(comment for comment in captured_comments if "🔎 System QA 통과" in comment)
    human_qa_comment = next(comment for comment in captured_comments if "🧑‍💻 Human QA 요청" in comment)
    assert "### QA 결과" in qa_comment
    assert "- result: `pass`" in qa_comment
    assert "- command:" in qa_comment
    assert "### 검증 항목" in qa_comment
    assert "- [V] test:signup 통과" in qa_comment
    assert "### Human QA 권장 체크" not in qa_comment
    assert "* 작업 내용: [FE] 회원 가입 기능 구현" in human_qa_comment
    assert "* 작업 타입: FE feature" in human_qa_comment
    assert f"* 브랜치 명: feature(FE)-{issue_number}" in human_qa_comment
    assert "* QA 요청 시각:" in human_qa_comment
    assert "1. 브라우저에서 메인 화면에 접속했을 때 회원가입 진입 버튼 또는 링크가 보이는가" in human_qa_comment
    qa_approval_command = f"harness approve --issue {issue_number} --stage qa --approved-by <name>"
    assert "사람 QA 승인 명령:" in human_qa_comment
    assert qa_approval_command in human_qa_comment
    assert duplicate_qa_response.status_code == 200
    assert duplicate_qa_response.json() == {
        "status": "ignored",
        "reason": "현재 작업 상태는 `QA Review`입니다. QA는 `QA Ready`에서만 실행할 수 있습니다. 먼저 dev 승인을 기록하세요.",
    }
    duplicate_qa_comment = next(
        comment for comment in captured_comments if "🔎 System QA를 시작하지 못했습니다" in comment
    )
    assert "@ai-harness re-qa" in duplicate_qa_comment
    assert reqa_response.status_code == 200
    reqa_result = reqa_response.json()
    assert reqa_result["previous_state"] == "QA Review"
    assert reqa_result["current_state"] == "QA Review"
    assert reqa_result["message"] == "QA 재검증이 통과되었고 작업 상태는 QA Review로 유지됩니다."
    assert any("♻️ 🔎 System QA 재검증 통과" in comment for comment in captured_comments)
    assert any("♻️ 🧑‍💻 Human QA Re-QA 요청" in comment for comment in captured_comments)
    assert len(captured_chat_messages) == 2
    assert "🧑‍💻 Human QA 요청" in captured_chat_messages[0]
    assert "♻️ 🧑‍💻 Human QA Re-QA 요청" in captured_chat_messages[1]
    assert "System QA는 통과했습니다." in captured_chat_messages[1]
    assert "1. 브라우저에서 메인 화면에 접속했을 때 회원가입 진입 버튼 또는 링크가 보이는가" in captured_chat_messages[1]
    assert "화면 확인 URL:\nhttp://localhost:3000" in captured_chat_messages[1]
    assert f"GitHub Issue:\n{issue['html_url']}" in captured_chat_messages[1]
    assert "정리 Agent를 호출할까요?" in captured_chat_messages[1]
    assert "`document` 명령" in captured_chat_messages[1]
    assert "`domain-knowledge` 명령" in captured_chat_messages[1]
    assert len(captured_discord_messages) == 2
    assert captured_discord_messages == captured_chat_messages
    assert qa_approval_command in captured_discord_messages[0]
    assert qa_approval_command in captured_discord_messages[1]


def test_issue_comment_qa_command_without_development_is_ignored(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "qa_command", "@ai-harness qa")
    monkeypatch.setattr(orchestration.settings, "github_token", None)

    issue_number = uuid4().int % 1_000_000_000
    payload = {
        "action": "created",
        "issue": {
            "number": issue_number,
            "title": "[FE] 회원 가입 기능 구현",
            "body": "회원가입 화면을 추가한다.",
            "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
            "labels": [{"name": "type: feFeature"}],
        },
        "comment": {"body": "@ai-harness qa"},
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
    assert response.json() == {
        "status": "ignored",
        "reason": "작업을 찾을 수 없습니다. 먼저 plan과 develop을 실행하세요.",
    }


def test_issue_comment_ignores_commands_not_on_first_content_line(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "replan_command", "@ai-harness replan")

    payload = {
        "action": "created",
        "issue": {
            "number": uuid4().int % 1_000_000_000,
            "title": "[FE] 회원 가입 기능 구현",
            "body": "회원가입 화면을 추가한다.",
            "html_url": "https://github.com/passionryu/targetApp/issues/1",
        },
        "comment": {
            "body": "\n".join(
                [
                    "## AI Design이 이미 존재합니다",
                    "",
                    "```markdown",
                    "@ai-harness replan",
                    "",
                    "- 수정하고 싶은 설계 방향을 적습니다.",
                    "```",
                ]
            )
        },
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
    assert response.json() == {"status": "ignored", "reason": "AI Harness 이슈 명령이 아닙니다."}


def test_issue_comment_ignores_ai_harness_generated_comment(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)

    payload = {
        "action": "created",
        "issue": {
            "number": uuid4().int % 1_000_000_000,
            "title": "[FE] 회원 가입 기능 구현",
            "body": "회원가입 화면을 추가한다.",
            "html_url": "https://github.com/passionryu/targetApp/issues/1",
        },
        "comment": {
            "body": "\n".join(
                [
                    "<!-- ai-harness-generated -->",
                    "",
                    "@ai-harness replan",
                    "",
                    "- 이 댓글은 하네스가 작성했다.",
                ]
            )
        },
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
    assert response.json() == {"status": "ignored", "reason": "AI Harness가 생성한 댓글입니다."}
