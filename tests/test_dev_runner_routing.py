import json

from git import Repo

import agents.runners.responsibility_runners as responsibility_runners
from agents.base import AgentStatus
from agents.dev_agent import _backend_style_lines, _select_runners
from agents.runners.base import DevRunnerContext
from agents.runners.responsibility_runners import TestImplementationRunner


def _context(tmp_path, issue_type: str, title: str, body: str) -> DevRunnerContext:
    repo_path = tmp_path / "targetApp"
    repo_path.mkdir()
    (repo_path / "README.md").write_text("# target\n", encoding="utf-8")
    (repo_path / "apps/web").mkdir(parents=True)
    (repo_path / "apps/web/package.json").write_text(
        json.dumps(
            {
                "name": "@app/web",
                "private": True,
                "scripts": {
                    "test:main-auth": "node scripts/verify-main-auth-screen.mjs",
                    "build": "next build",
                },
            }
        ),
        encoding="utf-8",
    )
    (repo_path / "apps/server").mkdir(parents=True)
    (repo_path / "apps/server/build.gradle.kts").write_text("plugins { kotlin(\"jvm\") }\n", encoding="utf-8")
    repo = Repo.init(repo_path)
    repo.index.add(["README.md", "apps/web/package.json", "apps/server/build.gradle.kts"])
    repo.index.commit("Initial commit")
    task_dir = tmp_path / "artifacts" / "task-1" / "dev"
    task_dir.mkdir(parents=True)
    return DevRunnerContext(
        task_id="task-1",
        title=title,
        body=body,
        issue_type=issue_type,
        issue_number="22",
        branch_name="bugfix-22",
        feature_name="설정 색상 선택 반영",
        repo=repo,
        repo_path=repo_path,
        task_dir=task_dir,
        timeout_seconds=30,
    )


def test_frontend_bugfix_does_not_select_backend_ddd_runner(tmp_path):
    context = _context(
        tmp_path,
        "bugfix",
        "[FE] 설정 색상 선택값이 메인 화면 테마에 반영되지 않는다",
        "노을빛 / 크림빛 / 우드빛 선택값을 localStorage에 저장하고 화면 색감에 반영한다.",
    )

    runner_names = [runner.name for runner in _select_runners(context)]

    assert runner_names == ["frontend_implementation_runner", "test_implementation_runner"]
    assert "ddd_modeling_runner" not in runner_names
    assert "backend orchestration style skill: 이 이슈 타입에는 필수가 아닙니다." in "\n".join(
        _backend_style_lines(context)
    )


def test_backend_bugfix_can_still_select_backend_runner(tmp_path):
    context = _context(
        tmp_path,
        "bugfix",
        "[BE] 로그인 API 오류 응답 코드가 잘못 반환된다",
        "Spring Controller와 application usecase의 인증 실패 응답을 수정한다.",
    )

    runner_names = [runner.name for runner in _select_runners(context)]

    assert "ddd_modeling_runner" in runner_names
    assert "frontend_implementation_runner" not in runner_names
    assert "backend orchestration style skill: required" in "\n".join(_backend_style_lines(context))


def test_frontend_bugfix_test_runner_runs_only_frontend_commands(tmp_path, monkeypatch):
    context = _context(
        tmp_path,
        "bugfix",
        "[FE] 설정 색상 선택값이 메인 화면 테마에 반영되지 않는다",
        "노을빛 / 크림빛 / 우드빛 선택값을 localStorage에 저장하고 화면 색감에 반영한다.",
    )
    commands: list[list[str]] = []

    def fake_run_command(command, cwd, timeout_seconds):
        commands.append(command)
        return command, 0, "ok", ""

    monkeypatch.setattr(responsibility_runners, "_run_command", fake_run_command)

    result = TestImplementationRunner().run(context)

    assert result.status == AgentStatus.SUCCESS
    assert commands == [
        ["pnpm", "--dir", "apps/web", "test:main-auth"],
        ["pnpm", "--dir", "apps/web", "build"],
    ]
