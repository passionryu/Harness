import json
import subprocess
from uuid import uuid4

import ai_harness.cli as cli
import orchestrator.services.orchestration as orchestration
from orchestrator.db.models import Run, Task
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
    captured_project_moves: list[tuple[int, str]] = []

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

        def move_issue_project_status(
            self,
            owner: str,
            repo: str,
            issue_number: int,
            project_number: int,
            status_name: str,
        ) -> None:
            captured_project_moves.append((issue_number, status_name))

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
    monkeypatch.setattr(cli.settings, "github_project_number", 4)
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
    assert payload["project_status"] == "Backlog"
    assert payload["notification"] == "sent"
    assert payload["next"] == f"harness design --issue {issue_number}"
    assert captured_project_moves == [(issue_number, "Backlog")]
    assert captured_messages
    assert "이슈 생성 완료" in captured_messages[0]
    assert f"harness design --issue {issue_number}" in captured_messages[0]

    with SessionLocal() as db:
        task = db.query(Task).filter(Task.github_issue_number == issue_number).one()
        assert task.title.startswith("[Config]")
        assert task.state == "Backlog"
        assert "type: config" in task.body


# CLI publish-ui-evidence 명령이 이미지 증거를 커밋하고 stage 브랜치에 병합하는지 검증한다.
def test_cli_publish_ui_evidence_merges_images_to_stage(tmp_path, monkeypatch, capsys):
    repo_path = tmp_path / "target"
    repo_path.mkdir()
    _git(repo_path, "init")
    _git(repo_path, "config", "user.email", "test@example.local")
    _git(repo_path, "config", "user.name", "Harness Test")
    (repo_path / "README.md").write_text("# target\n", encoding="utf-8")
    _git(repo_path, "add", "README.md")
    _git(repo_path, "commit", "-m", "Initial commit")
    _git(repo_path, "checkout", "-b", "stage")

    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake image")

    monkeypatch.setattr(cli.settings, "target_repo_path", repo_path)
    monkeypatch.setattr(cli.settings, "development_base_branch", "stage")

    exit_code = cli.main(
        [
            "--json",
            "publish-ui-evidence",
            "--image",
            str(image_path),
            "--issue",
            "20",
            "--slug",
            "issue-20-ui-evidence-test",
            "--no-push",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "published"
    assert payload["target_branch"] == "stage"
    assert payload["evidence_branch"] == "qa-assets/issue-20-ui-evidence-test"
    assert payload["pushed"] is False
    assert "docs/qa-screenshots/issue-20-ui-evidence-test/screen.png" in payload["files"]
    assert (repo_path / "docs/qa-screenshots/issue-20-ui-evidence-test/screen.png").exists()
    assert _git_output(repo_path, "branch", "--show-current") == "stage"


def _git(repo_path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo_path, check=True, capture_output=True, text=True)


def _git_output(repo_path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


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


# CLI manual-complete 명령이 자동 runner 밖의 구현 완료를 공식 run으로 기록하는지 검증한다.
def test_cli_manual_complete_dev_records_success_run(tmp_path, monkeypatch, capsys):
    issue_number = uuid4().int % 1_000_000_000
    monkeypatch.setattr(cli.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", "")
    monkeypatch.setattr(orchestration.settings, "github_project_number", 0)

    with SessionLocal() as db:
        task = Task(
            title="[FE] 알림 서비스 준비중 처리",
            body="\n".join(
                [
                    "마이페이지 알림 서비스를 준비중 상태로 비활성화한다.",
                    "",
                    "## Harness Metadata",
                    f"- issue_number: {issue_number}",
                    "- labels: type: feFeature",
                ]
            ),
            github_issue_number=issue_number,
            github_issue_url=f"https://github.com/passionryu/myMentalCare/issues/{issue_number}",
            state="Dev Ready",
        )
        db.add(task)
        db.commit()

    exit_code = cli.main(
        [
            "--json",
            "manual-complete",
            "--issue",
            str(issue_number),
            "--stage",
            "dev",
            "--completed-by",
            "passionryu",
            "--notes",
            "Codex가 수동 구현과 테스트를 완료했다.",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["previous_state"] == "Dev Ready"
    assert payload["current_state"] == "Dev Review"

    with SessionLocal() as db:
        task = db.query(Task).filter(Task.github_issue_number == issue_number).one()
        latest_run = (
            db.query(Run)
            .filter(Run.task_id == task.id)
            .order_by(Run.started_at.desc())
            .first()
        )
        assert task.state == "Dev Review"
        assert latest_run.agent_name == "manual_dev"
        assert latest_run.status == "success"
        assert (tmp_path / "artifacts" / task.id / "dev" / "manual-completion.md").exists()


# Human QA 전에 실패성 Dev 댓글을 지우고 구현 보고서를 성공 기준으로 보강하는지 검증한다.
def test_issue_report_repair_deletes_stale_dev_failure_and_updates_dev_report(tmp_path, monkeypatch):
    issue_number = uuid4().int % 1_000_000_000
    deleted_comments: list[int] = []
    updated_comments: list[tuple[int, str]] = []

    class FakeGitHubAdapter:
        def __init__(self, token: str | None, use_gh_cli: bool = False):
            self.token = token
            self.use_gh_cli = use_gh_cli

        def is_configured(self) -> bool:
            return True

        def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict]:
            return [
                {
                    "id": 10,
                    "body": "<!-- ai-harness-generated -->\n\n# ⚠️ Dev Agent 확인 필요: old\n자동 구현을 완료하지 못했습니다",
                },
                {
                    "id": 20,
                    "body": "<!-- ai-harness-generated -->\n\n# 🛠️ 구현 보고서: old",
                },
            ]

        def update_issue_comment(self, owner: str, repo: str, comment_id: int, body: str) -> None:
            updated_comments.append((comment_id, body))

        def delete_issue_comment(self, owner: str, repo: str, comment_id: int) -> None:
            deleted_comments.append(comment_id)

        def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
            raise AssertionError("기존 구현 보고서가 있으므로 새 댓글을 만들면 안 된다.")

    monkeypatch.setattr(cli.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(orchestration.settings, "github_token", "token")
    monkeypatch.setattr(orchestration.settings, "github_owner", "passionryu")
    monkeypatch.setattr(orchestration.settings, "github_repo", "myMentalCare")
    monkeypatch.setattr(orchestration, "GitHubAdapter", FakeGitHubAdapter)

    with SessionLocal() as db:
        task = Task(
            title="[FE] 알림 서비스 준비중 처리",
            body="\n".join(
                [
                    "마이페이지 알림 서비스를 준비중 상태로 비활성화한다.",
                    "",
                    "## Harness Metadata",
                    f"- issue_number: {issue_number}",
                    "- labels: type: feFeature",
                ]
            ),
            github_issue_number=issue_number,
            github_issue_url=f"https://github.com/passionryu/myMentalCare/issues/{issue_number}",
            state="QA Review",
        )
        db.add(task)
        db.flush()
        run = Run(
            task_id=task.id,
            agent_name="manual_dev",
            status="success",
            summary="Codex가 수동 구현과 검증을 완료했다.",
        )
        db.add(run)
        db.commit()

        commit_plan = tmp_path / "artifacts" / task.id / "dev" / "commit-plan.md"
        commit_plan.parent.mkdir(parents=True)
        commit_plan.write_text("- 925f378 알림 설정 준비중 상태 전환\n", encoding="utf-8")

        service = orchestration.OrchestrationService(db)
        service._repair_issue_reports_before_human_qa(task, run.id, issue_number)

    assert deleted_comments == [10]
    assert updated_comments[0][0] == 20
    assert "# 🛠️ 구현 보고서: [FE] 알림 서비스 준비중 처리" in updated_comments[0][1]
    assert "925f378 알림 설정 준비중 상태 전환" in updated_comments[0][1]
