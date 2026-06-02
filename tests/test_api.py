from pathlib import Path

from fastapi.testclient import TestClient
from git import Repo

import orchestrator.services.orchestration as orchestration
from orchestrator.main import app


def test_task_lifecycle(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    target_repo = tmp_path / "studyHub"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")
    monkeypatch.setattr(orchestration.settings, "artifact_root", artifact_root)
    monkeypatch.setattr(orchestration.settings, "target_repo_path", target_repo)

    with TestClient(app) as client:
        create_response = client.post(
            "/tasks",
            json={"title": "Implement deterministic harness", "body": "Build the MVP."},
        )
        assert create_response.status_code == 200
        task = create_response.json()
        task_id = task["id"]
        assert task["state"] == "Backlog"

        triage_response = client.post(
            "/events/manual",
            json={"task_id": task_id, "event": "triage", "reason": "test"},
        )
        assert triage_response.status_code == 200
        assert triage_response.json()["current_state"] == "Plan Review"

        dev_response = client.post(
            "/events/manual",
            json={"task_id": task_id, "event": "start_dev", "reason": "test"},
        )
        assert dev_response.status_code == 400
        assert "invalid transition" in dev_response.json()["detail"]

    task_artifact_root = Path(artifact_root) / task_id
    assert task_artifact_root.exists()
