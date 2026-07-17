from fastapi.testclient import TestClient

from orchestrator.main import app


def test_dashboard_shows_stateless_artifact_notice():
    with TestClient(app) as client:
        response = client.get("/dashboard")

    assert response.status_code == 200
    assert "상태 저장 dashboard는 제거되었습니다" in response.text
    assert "GitHub Issue와 Markdown artifact" in response.text
