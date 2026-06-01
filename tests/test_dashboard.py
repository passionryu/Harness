from uuid import uuid4

from fastapi.testclient import TestClient

import orchestrator.api.dashboard as dashboard
import orchestrator.services.orchestration as orchestration
from orchestrator.db.models import Task
from orchestrator.db.session import SessionLocal, create_db
from orchestrator.main import app


# 대시보드 테스트용 GitHub task를 DB에 생성한다.
def _create_dashboard_task() -> Task:
    create_db()
    issue_number = uuid4().int % 1_000_000_000
    with SessionLocal() as db:
        task = Task(
            title="[FS] 테스트 대시보드 작업",
            body="\n".join(
                [
                    "대시보드에서 확인할 작업입니다.",
                    "",
                    "## Harness Metadata",
                    f"- issue_number: {issue_number}",
                    "- labels: type: fullstackFeature",
                ]
            ),
            github_issue_number=issue_number,
            github_issue_url=f"https://github.com/passionryu/studyHub/issues/{issue_number}",
            state="Todo",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task


# 대시보드 테스트용 내부 task를 DB에 생성한다.
def _create_internal_dashboard_task() -> Task:
    create_db()
    with SessionLocal() as db:
        task = Task(
            title="Implement deterministic harness",
            body="초기 수동 task입니다.",
            state="Done",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task


# SSR 대시보드 목록이 task 정보를 HTML로 렌더링하는지 검증한다.
def test_dashboard_home_renders_task_list(monkeypatch):
    monkeypatch.setattr(orchestration.settings, "github_token", None)
    task = _create_dashboard_task()

    with TestClient(app) as client:
        response = client.get("/dashboard")

    assert response.status_code == 200
    assert "AI Harness Dashboard" in response.text
    assert task.title in response.text
    assert "@ai-harness develop" in response.text
    assert "Sync All GitHub Issues" in response.text


# 대시보드 기본 목록은 GitHub issue가 없는 내부 task를 숨긴다.
def test_dashboard_home_hides_internal_tasks_by_default(monkeypatch):
    monkeypatch.setattr(orchestration.settings, "github_token", None)
    _create_dashboard_task()
    internal_task = _create_internal_dashboard_task()

    with TestClient(app) as client:
        default_response = client.get("/dashboard")
        internal_response = client.get("/dashboard?include_internal=true")

    assert default_response.status_code == 200
    assert internal_task.title not in default_response.text
    assert internal_task.title in internal_response.text


# SSR 대시보드 상세 화면이 명령 버튼과 실행 이력을 렌더링하는지 검증한다.
def test_dashboard_task_detail_renders_command_panel(monkeypatch):
    monkeypatch.setattr(orchestration.settings, "github_token", None)
    task = _create_dashboard_task()

    with TestClient(app) as client:
        response = client.get(f"/dashboard/tasks/{task.id}")

    assert response.status_code == 200
    assert "명령 실행" in response.text
    assert "Develop" in response.text
    assert "Refactor" in response.text
    assert task.github_issue_url in response.text


# 대시보드 버튼 요청이 기존 하네스 명령 실행 흐름으로 위임되는지 검증한다.
def test_dashboard_status_command_redirects_with_result(monkeypatch):
    monkeypatch.setattr(orchestration.settings, "github_token", None)
    task = _create_dashboard_task()

    with TestClient(app) as client:
        response = client.post(
            f"/dashboard/tasks/{task.id}/commands/status",
            data={"note": "상태 확인"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/dashboard/tasks/{task.id}?message=")


# Sync All GitHub Issues 버튼은 GitHub open issue를 하네스 task로 등록한다.
def test_dashboard_sync_all_github_issues_imports_missing_issues(monkeypatch):
    create_db()
    monkeypatch.setattr(dashboard.settings, "github_token", "token")
    monkeypatch.setattr(dashboard.settings, "github_owner", "passionryu")
    monkeypatch.setattr(dashboard.settings, "github_repo", "studyHub")

    class FakeGitHubAdapter:
        def __init__(self, token: str):
            self.token = token

        # 테스트용 open issue 목록을 반환한다.
        def list_issues(self, owner: str, repo: str) -> list[dict]:
            assert owner == "passionryu"
            assert repo == "studyHub"
            return [
                {
                    "number": 8,
                    "title": "[FS] 기능 구현 로그인 기능 구현",
                    "body": "로그인 기능을 구현한다.",
                    "html_url": "https://github.com/passionryu/studyHub/issues/8",
                    "labels": [{"name": "type: fullstackFeature"}],
                },
                {
                    "number": 9,
                    "title": "[BE] DB 및 도메인 설계",
                    "body": "DB를 설계한다.",
                    "html_url": "https://github.com/passionryu/studyHub/issues/9",
                    "labels": [{"name": "type: beFeature"}],
                },
            ]

    monkeypatch.setattr(dashboard, "GitHubAdapter", FakeGitHubAdapter)

    with TestClient(app) as client:
        response = client.post("/dashboard/sync/github/issues", follow_redirects=False)

    assert response.status_code == 303
    with SessionLocal() as db:
        issue_8 = db.query(Task).filter(Task.github_issue_number == 8).one()
        issue_9 = db.query(Task).filter(Task.github_issue_number == 9).one()

    assert issue_8.state == "Backlog"
    assert issue_9.state == "Backlog"
    assert "type: fullstackFeature" in issue_8.body
