from fastapi.testclient import TestClient

from orchestrator.main import app


def test_health_reports_stateless_mode():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "stateless"}


def test_dashboard_is_stateless_notice():
    with TestClient(app) as client:
        response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Stateless Mode" in response.text
    assert "상태 저장 dashboard는 제거되었습니다" in response.text
