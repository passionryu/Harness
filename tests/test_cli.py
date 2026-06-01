import json
from uuid import uuid4

import ai_harness.cli as cli
import orchestrator.services.orchestration as orchestration
from orchestrator.db.models import Task
from orchestrator.db.session import SessionLocal


# CLI status 명령이 서버 없이 로컬 DB 상태를 조회하는지 검증한다.
def test_cli_status_returns_not_found_for_unknown_issue(capsys):
    issue_number = uuid4().int % 1_000_000_000

    exit_code = cli.main(["--json", "status", "--issue", str(issue_number)])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["status"] == "not_found"
    assert f"#{issue_number}" in payload["reason"]


# CLI sync 명령이 GitHub 이슈를 하네스 DB task로 저장하는지 검증한다.
def test_cli_sync_issue_imports_github_issue(monkeypatch, capsys):
    issue_number = uuid4().int % 1_000_000_000

    class FakeGitHubAdapter:
        def __init__(self, token: str):
            self.token = token

        def get_issue(self, owner: str, repo: str, issue_number: int) -> dict:
            return {
                "number": issue_number,
                "title": "[FS] 로그인 아이디 기반 회원가입/로그인",
                "body": "loginId를 추가한다.",
                "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
                "labels": [{"name": "type: fullstackFeature"}],
            }

    monkeypatch.setattr(cli.settings, "github_token", "token")
    monkeypatch.setattr(cli, "GitHubAdapter", FakeGitHubAdapter)

    exit_code = cli.main(["--json", "sync", "--issue", str(issue_number)])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["status"] == "ok"
    assert payload["issues"] == [issue_number]

    with SessionLocal() as db:
        task = db.query(Task).filter(Task.github_issue_number == issue_number).one()
        assert task.title == "[FS] 로그인 아이디 기반 회원가입/로그인"
        assert task.state == "Backlog"
        assert "type: fullstackFeature" in task.body


# CLI plan 명령이 FastAPI 없이 Plan Agent를 실행하는지 검증한다.
def test_cli_plan_runs_plan_agent_from_github_issue(tmp_path, monkeypatch, capsys):
    issue_number = uuid4().int % 1_000_000_000
    captured_comments: list[str] = []

    class FakeGitHubAdapter:
        def __init__(self, token: str):
            self.token = token

        def get_issue(self, owner: str, repo: str, issue_number: int) -> dict:
            return {
                "number": issue_number,
                "title": "[BE] 회원가입 API 구현",
                "body": "\n".join(
                    [
                        "## 목표",
                        "회원가입 API를 구현한다.",
                        "",
                        "## 완료 기준",
                        "- 회원가입 API 테스트가 통과한다.",
                    ]
                ),
                "html_url": f"https://github.com/passionryu/studyHub/issues/{issue_number}",
                "labels": [{"name": "type: beFeature"}],
            }

        def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
            captured_comments.append(body)

    monkeypatch.setattr(cli.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(cli, "GitHubAdapter", FakeGitHubAdapter)
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    exit_code = cli.main(["--json", "plan", "--issue", str(issue_number)])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["current_state"] == "Todo"
    assert "Plan을 생성했습니다" in payload["message"]
    assert "AI Plan" in captured_comments[-1]
    assert (tmp_path / "artifacts" / payload["task_id"] / "plans" / "architecture.md").exists()
