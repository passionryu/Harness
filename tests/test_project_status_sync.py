from orchestrator.api.schemas import HumanApproval
import orchestrator.services.orchestration as orchestration
from orchestrator.services.orchestration import OrchestrationService


class FakeGitHubAdapter:
    calls: list[tuple[int, int, str]] = []

    def __init__(self, token: str | None, use_gh_cli: bool = False):
        self.token = token
        self.use_gh_cli = use_gh_cli

    def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
        return None

    def move_issue_project_status(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        project_number: int,
        status_name: str,
    ) -> None:
        self.calls.append((issue_number, project_number, status_name))


def test_stateless_events_move_github_project_status(tmp_path, monkeypatch):
    FakeGitHubAdapter.calls = []
    issue_number = 91
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "github_project_number", 7)

    service = OrchestrationService()

    design = service.run_plan_for_github_issue(
        issue_number=issue_number,
        title="[FE] 설정 화면",
        body="설정 화면을 구현한다.",
        issue_url="https://github.com/passionryu/targetApp/issues/91",
        issue_labels=["type: feFeature"],
    )
    plan_approval = service.approve_stage_for_github_issue(
        issue_number=issue_number,
        stage="plan",
        payload=HumanApproval(approved_by="tester"),
    )
    dev = service.run_develop_for_github_issue(
        issue_number=issue_number,
        title="[FE] 설정 화면",
        body="설정 화면을 구현한다.",
        issue_url="https://github.com/passionryu/targetApp/issues/91",
        issue_labels=["type: feFeature"],
    )
    dev_approval = service.approve_stage_for_github_issue(
        issue_number=issue_number,
        stage="dev",
        payload=HumanApproval(approved_by="tester"),
    )
    qa = service.run_qa_for_github_issue(
        issue_number=issue_number,
        title="[FE] 설정 화면",
        body="설정 화면을 구현한다.",
        issue_url="https://github.com/passionryu/targetApp/issues/91",
        issue_labels=["type: feFeature"],
    )
    qa_approval = service.approve_stage_for_github_issue(
        issue_number=issue_number,
        stage="qa",
        payload=HumanApproval(approved_by="tester"),
    )
    deploy_approval = service.approve_stage_for_github_issue(
        issue_number=issue_number,
        stage="deploy",
        payload=HumanApproval(approved_by="tester"),
    )

    assert "moved to Plan Review" in design.message
    assert "moved to Dev Ready" in plan_approval.message
    assert "moved to Dev Review" in dev.message
    assert "moved to QA Ready" in dev_approval.message
    assert "moved to QA Review" in qa.message
    assert "moved to Ready To Deploy" in qa_approval.message
    assert "moved to Done" in deploy_approval.message
    assert [call[2] for call in FakeGitHubAdapter.calls] == [
        "Plan Review",
        "Dev Ready",
        "Dev Review",
        "QA Ready",
        "QA Review",
        "Ready To Deploy",
        "Done",
    ]


def test_manual_completion_moves_to_review_columns(tmp_path, monkeypatch):
    FakeGitHubAdapter.calls = []
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "github_project_number", 7)

    service = OrchestrationService()
    service.record_manual_completion_for_github_issue(
        issue_number=92,
        stage="dev",
        completed_by="tester",
    )
    service.record_manual_completion_for_github_issue(
        issue_number=92,
        stage="qa",
        completed_by="tester",
    )

    assert [call[2] for call in FakeGitHubAdapter.calls] == ["Dev Review", "QA Review"]
