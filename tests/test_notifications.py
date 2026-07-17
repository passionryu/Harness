from orchestrator.services.orchestration import OrchestrationService


def test_status_for_missing_issue_is_file_system_based(tmp_path, monkeypatch):
    import orchestrator.services.orchestration as orchestration

    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")

    status = OrchestrationService().status_for_github_issue(123, "테스트 이슈")

    assert status["status"] == "not_found"
    assert status["task_id"] == "issue-123"
    assert status["artifacts"] == []
