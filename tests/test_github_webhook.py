import hashlib
import hmac
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from git import Repo

import orchestrator.api.routes as routes
import orchestrator.services.orchestration as orchestration
import agents.qa_agent as qa_agent
from orchestrator.main import app


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


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
            "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
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
    assert result["current_state"] == "Todo"
    assert "Plan을 생성했습니다" in result["message"]

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
    monkeypatch.setattr(orchestration.settings, "github_repo", "studyHub")
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
            issue_url=f"https://github.com/passionryu/studyHub/issues/{issue_number}",
        )

    assert event.message == "GitHub 이슈 트리거로 Plan을 생성했습니다."
    assert "### 구현 요약" in captured["body"]
    assert "### 변경 대상" in captured["body"]
    assert "### 구현 순서" in captured["body"]
    assert "### 검증 기준" in captured["body"]
    assert "### 미결정 사항" in captured["body"]
    assert "### 시퀀스 다이어그램" in captured["body"]
    assert "### 플로우 차트" in captured["body"]


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
            "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
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
    assert "Plan을 생성했습니다" in result["message"]

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
            "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
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
    assert "Plan을 생성했습니다" in result["message"]
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
    monkeypatch.setattr(orchestration.settings, "github_repo", "studyHub")
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    issue_number = uuid4().int % 1_000_000_000
    issue = {
        "number": issue_number,
        "title": "[FE] 회원 가입 기능 구현",
        "body": "회원가입 화면을 추가한다.",
        "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
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
    assert "- state: `Todo`" in captured_comments[-1]
    assert "마지막 Agent 실행" in captured_comments[-1]
    assert "@ai-harness develop" in captured_comments[-1]


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
    monkeypatch.setattr(orchestration.settings, "github_repo", "studyHub")
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    issue_number = uuid4().int % 1_000_000_000
    issue = {
        "number": issue_number,
        "title": "[BE] 회원가입 API 구현",
        "body": "회원가입 API를 추가한다.",
        "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
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
            "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
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
    assert "Controller" in sequence
    assert "UseCase" in sequence


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
    monkeypatch.setattr(orchestration.settings, "github_repo", "studyHub")
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
            issue_url=f"https://github.com/passionryu/studyHub/issues/{issue_number}",
            issue_labels=["type: beFeature"],
        )

    assert "### 이슈 타입\nbeFeature" in captured["body"]
    assert "apps/server/modules/application 하위 usecase" in captured["body"]
    assert "Controller" in captured["body"]
    assert "UseCase" in captured["body"]
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
    monkeypatch.setattr(orchestration.settings, "github_repo", "studyHub")
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    issue_number = uuid4().int % 1_000_000_000
    payload = {
        "action": "created",
        "issue": {
            "number": issue_number,
            "title": "[FE] 회원 가입 기능 구현",
            "body": "회원가입 화면을 추가한다.",
            "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
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
    assert "Plan을 생성했습니다" in first_response.json()["message"]
    assert second_response.json()["message"] == "이미 Plan이 완료되어 중복 실행을 스킵했습니다."
    assert len(captured_comments) == 2
    assert "AI Plan이 이미 존재합니다" in captured_comments[-1]
    assert "@ai-harness replan" in captured_comments[-1]


def test_issue_comment_develop_command_approves_plan_and_runs_dev(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(routes.settings, "develop_command", "@ai-harness develop")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", None)
    target_repo = tmp_path / "studyHub"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (target_repo / "apps/web").mkdir(parents=True)
    (target_repo / "apps/web/package.json").write_text(
        json.dumps({"name": "@studyhub/web", "private": True, "scripts": {}}),
        encoding="utf-8",
    )
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")
    monkeypatch.setattr(orchestration.settings, "target_repo_path", target_repo)

    issue_number = uuid4().int % 1_000_000_000
    expected_branch = f"feature(FE)-{issue_number}"
    issue = {
        "number": issue_number,
        "title": "[FE] 회원 가입 기능 구현",
        "body": "회원가입 화면을 추가한다.",
        "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
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
    assert result["previous_state"] == "Todo"
    assert result["current_state"] == "In Progress"
    assert result["message"] == "Plan이 승인되어 Dev Agent를 실행했습니다."
    assert repo.active_branch.name == expected_branch
    commit_plan = tmp_path / "artifacts" / result["task_id"] / "dev" / "commit-plan.md"
    dev_status = tmp_path / "artifacts" / result["task_id"] / "dev" / "dev-status.md"
    assert commit_plan.exists()
    assert dev_status.exists()
    assert expected_branch in commit_plan.read_text()
    assert "[회원 가입 기능 구현] : 버튼/라우팅 추가" in commit_plan.read_text()
    assert "[회원 가입 기능 구현] : 프론트엔드 테스트 코드 추가" in commit_plan.read_text()
    assert "회원가입 화면 smoke 검증 통과" in (
        tmp_path / "artifacts" / result["task_id"] / "dev" / "test-report.md"
    ).read_text()
    assert (tmp_path / "artifacts" / result["task_id"] / "dev" / "implementation.patch").exists()
    assert (tmp_path / "artifacts" / result["task_id"] / "dev" / "test-report.md").exists()


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
            "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
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
        "reason": "Plan을 찾을 수 없습니다. 먼저 @ai-harness plan을 실행하세요.",
    }


def test_backend_develop_uses_kotlin_runner_and_generates_member_signup_files(
    tmp_path, monkeypatch
):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(routes.settings, "develop_command", "@ai-harness develop")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", None)
    target_repo = tmp_path / "studyHub"
    (target_repo / "apps/server").mkdir(parents=True)
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (target_repo / "apps/server/build.gradle.kts").write_text(
        "plugins { kotlin(\"jvm\") version \"2.0.0\" }\n",
        encoding="utf-8",
    )
    (target_repo / "apps/server/modules/bootstrap/studyhub").mkdir(parents=True)
    (target_repo / "apps/server/modules/bootstrap/studyhub/build.gradle.kts").write_text(
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
            "apps/server/modules/bootstrap/studyhub/build.gradle.kts",
        ]
    )
    repo.index.commit("Initial commit")
    monkeypatch.setattr(orchestration.settings, "target_repo_path", target_repo)

    issue_number = uuid4().int % 1_000_000_000
    issue = {
        "number": issue_number,
        "title": "[BE] 회원가입 API 구현",
        "body": "회원가입 API를 추가한다.",
        "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
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
    assert "Kotlin/Spring 구현 후 Gradle 테스트가 실패했습니다." in result["reason"]

    task_id = plan_response.json()["task_id"]
    dev_dir = tmp_path / "artifacts" / task_id / "dev"
    assert "selected_runner: `kotlin_spring_runner`" in (dev_dir / "commit-plan.md").read_text()
    assert (dev_dir / "kotlin-spring-runner.md").exists()
    assert (
        target_repo
        / "apps/server/modules/application/src/main/kotlin/com/studyhub/server/application/member/RegisterMemberService.kt"
    ).exists()
    assert (
        target_repo
        / "apps/server/modules/bootstrap/studyhub/src/main/kotlin/com/studyhub/server/bootstrap/presentation/member/MemberSignupController.kt"
    ).exists()
    controller = (
        target_repo
        / "apps/server/modules/bootstrap/studyhub/src/main/kotlin/com/studyhub/server/bootstrap/presentation/member/MemberSignupController.kt"
    ).read_text()
    request_dto = target_repo / (
        "apps/server/modules/bootstrap/studyhub/src/main/kotlin/"
        "com/studyhub/server/bootstrap/presentation/member/MemberSignupRequest.kt"
    )
    response_dto = target_repo / (
        "apps/server/modules/bootstrap/studyhub/src/main/kotlin/"
        "com/studyhub/server/bootstrap/presentation/member/MemberSignupResponse.kt"
    )
    assert "@Operation(" in controller
    assert "summary = \"회원가입\"" in controller
    assert "description = \"이름, 이메일, 비밀번호" in controller
    assert "ApiResponse" not in controller
    assert "Schema" not in request_dto.read_text()
    assert "Schema" not in response_dto.read_text()


def test_issue_comment_develop_command_continues_from_in_progress(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(routes.settings, "develop_command", "@ai-harness develop")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", None)
    target_repo = tmp_path / "studyHub"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (target_repo / "apps/web").mkdir(parents=True)
    (target_repo / "apps/web/package.json").write_text(
        json.dumps({"name": "@studyhub/web", "private": True, "scripts": {}}),
        encoding="utf-8",
    )
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")
    monkeypatch.setattr(orchestration.settings, "target_repo_path", target_repo)

    issue_number = uuid4().int % 1_000_000_000
    issue = {
        "number": issue_number,
        "title": "[FE] 회원 가입 기능 구현",
        "body": "회원가입 화면을 추가한다.",
        "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
        "labels": [{"name": "type: feFeature"}],
    }

    with TestClient(app) as client:
        for command in ["@ai-harness plan", "@ai-harness develop"]:
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
    assert result["previous_state"] == "In Progress"
    assert result["current_state"] == "In Progress"
    assert result["message"] == "Dev Agent를 다시 실행했습니다."


def test_issue_comment_refactor_command_applies_human_request(tmp_path, monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(routes.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(routes.settings, "plan_command", "@ai-harness plan")
    monkeypatch.setattr(routes.settings, "develop_command", "@ai-harness develop")
    monkeypatch.setattr(routes.settings, "refactor_command", "@ai-harness refactor")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", None)
    target_repo = tmp_path / "studyHub"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (target_repo / "apps/web").mkdir(parents=True)
    (target_repo / "apps/web/package.json").write_text(
        json.dumps({"name": "@studyhub/web", "private": True, "scripts": {}}),
        encoding="utf-8",
    )
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")
    monkeypatch.setattr(orchestration.settings, "target_repo_path", target_repo)

    issue_number = uuid4().int % 1_000_000_000
    issue = {
        "number": issue_number,
        "title": "[FE] 회원 가입 기능 구현",
        "body": "회원가입 화면을 추가한다.",
        "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
        "labels": [{"name": "type: feFeature"}],
    }

    with TestClient(app) as client:
        for command in ["@ai-harness plan", "@ai-harness develop"]:
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
    assert result["previous_state"] == "In Progress"
    assert result["current_state"] == "In Progress"
    assert result["message"] == "리팩터링 요청을 반영했고 작업 상태를 In Progress로 변경했습니다."

    dev_status = tmp_path / "artifacts" / result["task_id"] / "dev" / "dev-status.md"
    assert "mode: `refactor`" in dev_status.read_text()
    assert "컨트롤러는 얇게 유지한다" in dev_status.read_text()
    assert "DTO는 별도 파일로 분리한다" in dev_status.read_text()


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

    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)
    monkeypatch.setattr(orchestration, "GoogleChatNotifier", FakeGoogleChatNotifier)
    monkeypatch.setattr(orchestration, "DiscordNotifier", FakeDiscordNotifier)
    monkeypatch.setattr(
        orchestration.settings,
        "discord_webhook_url",
        "https://discord.com/api/webhooks/test/token",
    )

    target_repo = tmp_path / "studyHub"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (target_repo / "apps/web").mkdir(parents=True)
    (target_repo / "apps/web/package.json").write_text(
        json.dumps({"name": "@studyhub/web", "private": True, "scripts": {}}),
        encoding="utf-8",
    )
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")
    monkeypatch.setattr(orchestration.settings, "target_repo_path", target_repo)

    issue_number = uuid4().int % 1_000_000_000
    issue = {
        "number": issue_number,
        "title": "[FE] 회원 가입 기능 구현",
        "body": "회원가입 화면을 추가한다.",
        "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
        "labels": [{"name": "type: feFeature"}],
    }

    with TestClient(app) as client:
        for command in ["@ai-harness plan", "@ai-harness develop"]:
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
    assert result["previous_state"] == "In Progress"
    assert result["current_state"] == "System QA"
    assert result["message"] == "QA가 통과되어 작업 상태를 System QA로 변경했습니다."
    qa_dir = tmp_path / "artifacts" / result["task_id"] / "qa"
    assert (qa_dir / "qa-report.md").exists()
    assert (qa_dir / "qa-checklist.md").exists()
    assert "test:signup 통과" in (qa_dir / "qa-report.md").read_text()
    assert "## Human QA 체크리스트" in (qa_dir / "qa-report.md").read_text()
    qa_comment = next(comment for comment in captured_comments if "🔎 System QA 통과" in comment)
    human_qa_comment = next(comment for comment in captured_comments if "🧑‍💻 Human QA 요청" in comment)
    assert "### QA 결과" in qa_comment
    assert "- result: `pass`" in qa_comment
    assert "- command: `pnpm --dir apps/web test:signup`" in qa_comment
    assert "### 검증 항목" in qa_comment
    assert "- [x] test:signup 통과" in qa_comment
    assert "### Human QA 권장 체크" not in qa_comment
    assert "* 작업 내용: [FE] 회원 가입 기능 구현" in human_qa_comment
    assert "* 작업 타입: FE feature" in human_qa_comment
    assert f"* 브랜치 명: feature(FE)-{issue_number}" in human_qa_comment
    assert "* QA 요청 시각:" in human_qa_comment
    assert "1. 브라우저에서 메인 화면에 접속했을 때 회원가입 진입 버튼 또는 링크가 보이는가" in human_qa_comment
    assert duplicate_qa_response.status_code == 200
    assert duplicate_qa_response.json() == {
        "status": "ignored",
        "reason": "현재 작업 상태는 `System QA`입니다. QA는 `In Progress`에서만 실행할 수 있습니다.",
    }
    duplicate_qa_comment = next(
        comment for comment in captured_comments if "🔎 System QA를 시작하지 못했습니다" in comment
    )
    assert "@ai-harness re-qa" in duplicate_qa_comment
    assert reqa_response.status_code == 200
    reqa_result = reqa_response.json()
    assert reqa_result["previous_state"] == "System QA"
    assert reqa_result["current_state"] == "System QA"
    assert reqa_result["message"] == "QA 재검증이 통과되었고 작업 상태는 System QA로 유지됩니다."
    assert any("♻️ 🔎 System QA 재검증 통과" in comment for comment in captured_comments)
    assert any("♻️ 🧑‍💻 Human QA Re-QA 요청" in comment for comment in captured_comments)
    assert len(captured_chat_messages) == 2
    assert "🧑‍💻 Human QA 요청" in captured_chat_messages[0]
    assert "♻️ 🧑‍💻 Human QA Re-QA 요청" in captured_chat_messages[1]
    assert "System QA는 통과했습니다." in captured_chat_messages[1]
    assert "1. 브라우저에서 메인 화면에 접속했을 때 회원가입 진입 버튼 또는 링크가 보이는가" in captured_chat_messages[1]
    assert "확인 URL:\nhttp://localhost:3000/signup" in captured_chat_messages[1]
    assert f"GitHub Issue:\n{issue['html_url']}" in captured_chat_messages[1]
    assert len(captured_discord_messages) == 2
    assert captured_discord_messages == captured_chat_messages


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
            "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
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
            "html_url": "https://github.com/passionryu/studyHub/issues/1",
        },
        "comment": {
            "body": "\n".join(
                [
                    "## AI Plan이 이미 존재합니다",
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
            "html_url": "https://github.com/passionryu/studyHub/issues/1",
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
