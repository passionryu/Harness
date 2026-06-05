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
                "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
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


# CLI create-issue 명령이 GitHub issue 생성, DB 동기화, Discord 알림을 수행하는지 검증한다.
def test_cli_create_issue_syncs_task_and_notifies_discord(tmp_path, monkeypatch, capsys):
    issue_number = uuid4().int % 1_000_000_000
    body_file = tmp_path / "issue.md"
    body_file.write_text("## 목표\n\n인증 기반 설정을 추가한다.\n", encoding="utf-8")
    captured_messages: list[str] = []

    class FakeGitHubAdapter:
        def __init__(self, token: str):
            self.token = token

        def create_issue(self, owner: str, repo: str, title: str, body: str, labels: list[str] | None = None) -> dict:
            return {
                "number": issue_number,
                "title": title,
                "body": body,
                "html_url": f"https://github.com/passionryu/myMentalCare/issues/{issue_number}",
                "labels": [],
            }

    class FakeDiscordNotifier:
        def __init__(self, webhook_url: str | None):
            self.webhook_url = webhook_url

        def is_configured(self) -> bool:
            return bool(self.webhook_url)

        def send_text(self, text: str) -> None:
            captured_messages.append(text)

    monkeypatch.setattr(cli.settings, "github_token", "token")
    monkeypatch.setattr(cli.settings, "github_owner", "passionryu")
    monkeypatch.setattr(cli.settings, "github_repo", "myMentalCare")
    monkeypatch.setattr(cli.settings, "allow_external_notifications", True)
    monkeypatch.setattr(cli.settings, "discord_webhook_url", "https://discord.example/webhook")
    monkeypatch.setattr(cli, "GitHubAdapter", FakeGitHubAdapter)
    monkeypatch.setattr(cli, "DiscordNotifier", FakeDiscordNotifier)

    exit_code = cli.main(
        [
            "--json",
            "create-issue",
            "--type",
            "config",
            "--title",
            "[인증 기반 설정] Spring Security + JWT + Redis 인증 기반 설정",
            "--body-file",
            str(body_file),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["status"] == "created"
    assert payload["issue_number"] == issue_number
    assert payload["title"].startswith("[Config]")
    assert payload["notification"] == "sent"
    assert payload["next"] == f"harness design --issue {issue_number}"
    assert captured_messages
    assert "이슈 생성 완료" in captured_messages[0]
    assert f"harness design --issue {issue_number}" in captured_messages[0]

    with SessionLocal() as db:
        task = db.query(Task).filter(Task.github_issue_number == issue_number).one()
        assert task.title.startswith("[Config]")
        assert task.state == "Backlog"
        assert "type: config" in task.body


# CLI design 명령이 FastAPI 없이 Design Agent를 실행하는지 검증한다.
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
                "html_url": f"https://github.com/passionryu/targetApp/issues/{issue_number}",
                "labels": [{"name": "type: beFeature"}],
            }

        def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
            captured_comments.append(body)

    monkeypatch.setattr(cli.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(cli, "GitHubAdapter", FakeGitHubAdapter)
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    exit_code = cli.main(["--json", "design", "--issue", str(issue_number)])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["current_state"] == "Plan Review"
    assert "Design Agent 실행이 완료" in payload["message"]
    assert "AI Design" in captured_comments[-1]
    assert (tmp_path / "artifacts" / payload["task_id"] / "plans" / "architecture.md").exists()


# CLI approve 명령이 Plan 승인 gate를 통과시켜 Dev Ready로 전환하는지 검증한다.
def test_cli_approve_plan_moves_task_to_dev_ready(tmp_path, monkeypatch, capsys):
    issue_number = uuid4().int % 1_000_000_000

    with SessionLocal() as db:
        task = Task(
            title="[BE] 승인 테스트",
            body="승인 gate 테스트입니다.",
            github_issue_number=issue_number,
            github_issue_url=f"https://github.com/passionryu/targetApp/issues/{issue_number}",
            state="Plan Review",
        )
        db.add(task)
        db.commit()

    exit_code = cli.main(
        [
            "--json",
            "approve",
            "--issue",
            str(issue_number),
            "--stage",
            "plan",
            "--approved-by",
            "rsy",
            "--notes",
            "설계를 확인했다.",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["previous_state"] == "Plan Review"
    assert payload["current_state"] == "Dev Ready"

    with SessionLocal() as db:
        task = db.query(Task).filter(Task.github_issue_number == issue_number).one()
        assert task.state == "Dev Ready"
