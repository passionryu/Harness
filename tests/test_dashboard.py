from uuid import uuid4

from fastapi.testclient import TestClient

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
