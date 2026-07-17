import json
from uuid import uuid4

import ai_harness.cli as cli


def test_cli_status_reads_artifact_state(tmp_path, monkeypatch, capsys):
    issue_number = uuid4().int % 1_000_000_000
    monkeypatch.setattr(cli.settings, "artifact_root", tmp_path / "artifacts")

    exit_code = cli.main(["--json", "status", "--issue", str(issue_number)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "not_found"
    assert payload["task_id"] == f"issue-{issue_number}"


def test_cli_agent_specs_lists_markdown_specs(capsys):
    exit_code = cli.main(["--json", "agent-specs"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    names = {item["name"] for item in payload["specs"]}
    assert {"design", "dev", "qa", "documentation"} <= names


def test_cli_playbooks_returns_specific_playbook(capsys):
    exit_code = cli.main(["--json", "playbooks", "--name", "frontend-implementation"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["name"] == "frontend-implementation"
    assert "프론트엔드" in payload["summary"]
    assert "백엔드 DDD 작업으로 오분류하지 않는다" in payload["hard_rules"]


def test_cli_sync_issue_writes_context_artifact(tmp_path, monkeypatch, capsys):
    issue_number = uuid4().int % 1_000_000_000

    class FakeGitHubAdapter:
        def __init__(self, token: str, use_gh_cli: bool = False):
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
    monkeypatch.setattr(cli.settings, "artifact_root", tmp_path / "artifacts")
    monkeypatch.setattr(cli, "GitHubAdapter", FakeGitHubAdapter)

    exit_code = cli.main(["--json", "sync", "--issue", str(issue_number)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    context_file = tmp_path / "artifacts" / f"issue-{issue_number}" / "sync" / "issue-context.md"
    assert context_file.exists()
    assert "type: fullstackFeature" in context_file.read_text(encoding="utf-8")


def test_cli_manual_complete_writes_artifact(tmp_path, monkeypatch, capsys):
    issue_number = uuid4().int % 1_000_000_000
    monkeypatch.setattr(cli.settings, "artifact_root", tmp_path / "artifacts")

    exit_code = cli.main(
        [
            "--json",
            "manual-complete",
            "--issue",
            str(issue_number),
            "--stage",
            "dev",
            "--completed-by",
            "tester",
            "--notes",
            "stage 브랜치 병합 완료",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["task_id"] == f"issue-{issue_number}"
    artifact = tmp_path / "artifacts" / f"issue-{issue_number}" / "dev" / "manual-completion.md"
    assert artifact.exists()
    assert "stage 브랜치 병합 완료" in artifact.read_text(encoding="utf-8")
