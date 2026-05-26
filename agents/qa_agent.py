import json
import subprocess
from pathlib import Path

from git import Repo

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec
from orchestrator.core.settings import settings

HUMAN_QA_CHECKLIST = [
    "브라우저에서 메인 화면에 접속했을 때 회원가입 진입 버튼 또는 링크가 보이는가",
    "회원가입 진입 버튼을 클릭하면 `/signup` 화면으로 정상 이동하는가",
    "이름, 이메일, 비밀번호, 전화번호, 관심 영역 입력 필드가 의도한 순서와 형태로 보이는가",
    "모바일/데스크톱 화면에서 폼 레이아웃이 깨지거나 텍스트가 겹치지 않는가",
    "필수 입력값을 비웠을 때 사용자가 이해할 수 있는 검증 메시지가 보이는가",
    "잘못된 이메일 또는 너무 짧은 비밀번호 입력 시 제출이 막히는가",
    "정상 입력 후 제출했을 때 현재 단계에 맞는 안내 또는 mock-safe 동작이 보이는가",
    "로그인/메인 화면으로 돌아가는 흐름이 어색하지 않은가",
]


CHECK_NAME_KO = {
    "target repository exists": "대상 저장소 존재",
    "expected branch is checked out": "예상 브랜치 체크아웃 상태",
    "test:signup script exists": "test:signup 스크립트 존재",
    "test:signup passes": "test:signup 통과",
}


def _translate_check_name(name: str) -> str:
    if name.startswith("artifact exists: "):
        return f"산출물 존재: {name.removeprefix('artifact exists: ')}"
    if name.startswith("signup file exists: "):
        return f"회원가입 파일 존재: {name.removeprefix('signup file exists: ')}"
    return CHECK_NAME_KO.get(name, name)


def _extract_section(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    collected: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            marker = "## " if stripped.startswith("## ") else "### "
            if in_section:
                break
            in_section = stripped.removeprefix(marker).strip() == heading
            continue
        if in_section and stripped:
            collected.append(stripped)
    return collected


def _extract_metadata_value(markdown: str, key: str) -> str | None:
    for line in _extract_section(markdown, "Harness Metadata"):
        prefix = f"- {key}:"
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def _extract_issue_type(markdown: str) -> str:
    labels = _extract_metadata_value(markdown, "labels") or ""
    for label in [item.strip() for item in labels.split(",")]:
        if label.startswith("type: "):
            return label.removeprefix("type: ").strip()
    return "미지정"


def _branch_prefix(issue_type: str) -> str:
    return {
        "beFeature": "feature(BE)",
        "feFeature": "feature(FE)",
        "apiConnect": "api-connect",
        "bugfix": "bugfix",
        "hotfix": "hotfix",
        "infra": "infra",
        "config": "config",
        "docs": "docs",
    }.get(issue_type, "task")


def _branch_name(issue_type: str, issue_number: str) -> str:
    number = issue_number if issue_number and issue_number != "unknown" else "no-issue"
    return f"{_branch_prefix(issue_type)}-{number}"


def _run_command(command: list[str], cwd: Path, timeout_seconds: int) -> tuple[int, str, str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _package_has_script(package_json: Path, script_name: str) -> bool:
    if not package_json.exists():
        return False
    data = json.loads(package_json.read_text(encoding="utf-8"))
    return script_name in data.get("scripts", {})


class QAAgent:
    name = "qa"

    def run(self, input_data: AgentInput) -> AgentResult:
        task_dir = input_data.artifacts_root / input_data.task_id / "qa"
        task_dir.mkdir(parents=True, exist_ok=True)

        issue_type = _extract_issue_type(input_data.body)
        issue_number = _extract_metadata_value(input_data.body, "issue_number") or "unknown"
        branch_name = _branch_name(issue_type, issue_number)
        repo_path = settings.target_repo_path.expanduser().resolve()

        checks: list[tuple[str, bool, str]] = []
        command_sections: list[str] = []

        repo_exists = repo_path.exists()
        checks.append(("target repository exists", repo_exists, str(repo_path)))

        current_branch = "알 수 없음"
        if repo_exists:
            repo = Repo(repo_path)
            if branch_name in {head.name for head in repo.heads}:
                repo.git.checkout(branch_name)
            current_branch = repo.active_branch.name
            checks.append(
                (
                    "expected branch is checked out",
                    current_branch == branch_name,
                    f"expected={branch_name}, actual={current_branch}",
                )
            )

        plan_dir = input_data.artifacts_root / input_data.task_id / "plans"
        dev_dir = input_data.artifacts_root / input_data.task_id / "dev"
        required_artifacts = [
            plan_dir / "architecture.md",
            plan_dir / "edge-case-checklist.md",
            dev_dir / "commit-plan.md",
            dev_dir / "dev-status.md",
            dev_dir / "implementation.patch",
            dev_dir / "test-report.md",
        ]
        for artifact in required_artifacts:
            checks.append((f"artifact exists: {artifact.name}", artifact.exists(), str(artifact)))

        if issue_type == "feFeature":
            signup_files = [
                repo_path / "apps/web/app/signup/page.tsx",
                repo_path / "apps/web/components/signup/signup-form.tsx",
                repo_path / "apps/web/lib/signup-validation.ts",
                repo_path / "apps/web/scripts/verify-signup-page.mjs",
            ]
            for path in signup_files:
                checks.append((f"signup file exists: {path.name}", path.exists(), str(path)))

            package_json = repo_path / "apps/web/package.json"
            has_signup_test = _package_has_script(package_json, "test:signup")
            checks.append(("test:signup script exists", has_signup_test, str(package_json)))
            if has_signup_test:
                exit_code, stdout, stderr = _run_command(
                    ["pnpm", "--dir", "apps/web", "test:signup"],
                    repo_path,
                    input_data.timeout_seconds,
                )
                checks.append(("test:signup passes", exit_code == 0, f"exit_code={exit_code}"))
                command_sections.extend(
                    [
                        "## Command: pnpm --dir apps/web test:signup",
                        "",
                        f"- exit_code: {exit_code}",
                        "",
                        "### stdout",
                        "```text",
                        stdout.strip() or "(비어 있음)",
                        "```",
                        "",
                        "### stderr",
                        "```text",
                        stderr.strip() or "(비어 있음)",
                        "```",
                    ]
                )

        passed = all(passed for _, passed, _ in checks)
        checklist_lines = [
            f"- [{'x' if passed else ' '}] {_translate_check_name(name)} ({detail})"
            for name, passed, detail in checks
        ]
        human_qa_lines = [f"- [ ] {item}" for item in HUMAN_QA_CHECKLIST]

        report = task_dir / "qa-report.md"
        report.write_text(
            "\n".join(
                [
                    "# System QA Report",
                    "",
                    f"- issue_type: `{issue_type}`",
                    f"- issue_number: `{issue_number}`",
                    f"- branch: `{branch_name}`",
                    f"- current_branch: `{current_branch}`",
                    f"- result: {'pass' if passed else 'fail'}",
                    "",
                    "## 검증 체크리스트",
                    *checklist_lines,
                    "",
                    *(command_sections or ["## Commands", "", "- 이 이슈 타입에는 실행된 명령이 없습니다."]),
                    "",
                    "## Human QA 체크리스트",
                    *human_qa_lines,
                ]
            ),
            encoding="utf-8",
        )

        checklist = task_dir / "qa-checklist.md"
        checklist.write_text(
            "\n".join(
                [
                    "# QA 체크리스트",
                    "",
                    *checklist_lines,
                    "",
                    "## Human QA 체크리스트",
                    *human_qa_lines,
                ]
            ),
            encoding="utf-8",
        )

        return AgentResult(
            status=AgentStatus.SUCCESS if passed else AgentStatus.FAILED,
            summary=f"{branch_name} QA {'통과' if passed else '실패'}.",
            artifacts=[
                ArtifactSpec("qa-report", Path(report)),
                ArtifactSpec("qa-checklist", Path(checklist)),
            ],
            error=None if passed else "QA 검증이 실패했습니다. qa-report.md를 확인하세요.",
        )
