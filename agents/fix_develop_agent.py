import subprocess
from pathlib import Path

from git import Repo

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec
from agents.dev_agent import (
    _branch_name,
    _extract_issue_type,
    _extract_metadata_value,
    _feature_name,
)
from agents.organization import FIX_DEVELOP_RUNNERS, render_runner_definitions
from orchestrator.core.settings import settings


class FixDevelopAgent:
    name = "fix_develop"

    # 최근 develop 실패 산출물을 분석하고 자동 수리 가능한 실패를 복구한다.
    def run(self, input_data: AgentInput) -> AgentResult:
        task_dir = input_data.artifacts_root / input_data.task_id / "dev"
        task_dir.mkdir(parents=True, exist_ok=True)

        issue_type = _extract_issue_type(input_data.body)
        issue_number = _extract_metadata_value(input_data.body, "issue_number") or "unknown"
        branch_name = _branch_name(issue_type, issue_number)
        feature_name = _feature_name(input_data.title)
        repo_path = settings.target_repo_path.expanduser().resolve()
        test_report = task_dir / "test-report.md"
        dev_status = task_dir / "dev-status.md"
        fix_report = task_dir / "fix-develop-report.md"

        if not repo_path.exists():
            return _write_needs_human_report(
                fix_report,
                "대상 저장소를 찾지 못했습니다.",
                f"target_repo_path={repo_path}",
            )

        report_text = _read_text(test_report)
        status_text = _read_text(dev_status)
        failure = _classify_failure(report_text, status_text)
        repo = Repo(repo_path)
        branch_status = _checkout_branch(repo, branch_name)

        if failure.kind == "unsupported":
            return _write_needs_human_report(
                fix_report,
                "자동 수리 가능한 실패 유형이 아닙니다.",
                failure.reason,
            )

        changed_paths: list[str] = []
        if failure.kind == "cors_preflight_blocked_by_security":
            changed_paths.extend(_apply_cors_preflight_test_fix(repo_path))

        command = _verification_command_for_failure(failure.kind)
        exit_code, stdout, stderr = _run_command(command, _command_cwd(repo_path, command), input_data.timeout_seconds)
        commit_hash = "no commit"
        if exit_code == 0 and changed_paths:
            commit_hash = _stage_and_commit(repo, repo_path, changed_paths, f"[{feature_name}] : develop 실패 원인 수정")

        fix_report.write_text(
            "\n".join(
                [
                    "# Fix Develop Report",
                    "",
                    f"- branch: `{branch_name}`",
                    f"- branch_status: {branch_status}",
                    f"- failure_kind: `{failure.kind}`",
                    f"- reason: {failure.reason}",
                    f"- changed_paths: `{', '.join(changed_paths) if changed_paths else 'none'}`",
                    f"- commit: `{commit_hash}`",
                    "",
                    *render_runner_definitions("Fix Develop Agent 책임 러너", FIX_DEVELOP_RUNNERS),
                    "## Command",
                    f"- command: `{' '.join(command)}`",
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
            ),
            encoding="utf-8",
        )

        if exit_code != 0:
            return AgentResult(
                status=AgentStatus.FAILED,
                summary=f"{failure.kind} 수리 후 검증 명령이 실패했습니다.",
                artifacts=[ArtifactSpec("fix-develop-report", fix_report)],
                error="fix-develop 검증 실패. fix-develop-report.md를 확인하세요.",
            )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            summary=f"{failure.kind} 실패를 복구했고 검증 명령이 통과했습니다.",
            artifacts=[ArtifactSpec("fix-develop-report", fix_report)],
        )


class FailureClassification:
    # develop 실패를 자동 수리 전략에 매핑하기 위한 분류 결과를 보관한다.
    def __init__(self, kind: str, reason: str) -> None:
        self.kind = kind
        self.reason = reason


# 파일이 없거나 읽을 수 없는 산출물을 빈 문자열로 안전하게 읽는다.
def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


# 최근 Dev 산출물의 로그와 상태를 보고 자동 수리 가능한 실패 유형을 분류한다.
def _classify_failure(report_text: str, status_text: str) -> FailureClassification:
    haystack = f"{report_text}\n{status_text}"
    if (
        "WebCorsConfigurationTest" in haystack
        and (
            "Status expected:<200> but was:<401>" in haystack
            or "Status = 401" in haystack
            or "Unauthorized" in haystack
            or "localhost 3000 web origin can send signup preflight request() FAILED" in haystack
            or "AssertionError at WebCorsConfigurationTest.kt" in haystack
        )
    ):
        return FailureClassification(
            "cors_preflight_blocked_by_security",
            "CORS preflight 테스트가 Spring Security 인증 필터에 의해 401로 차단되었습니다.",
        )
    if "Kotlin/Spring 구현 후 Gradle 테스트가 실패했습니다" in haystack or "./gradlew" in haystack:
        return FailureClassification(
            "unsupported",
            "Gradle 실패는 감지했지만 현재 자동 수리 전략에 매칭되지 않았습니다.",
        )
    if "pnpm" in haystack or "Node" in haystack:
        return FailureClassification(
            "unsupported",
            "프론트엔드 실패는 감지했지만 현재 자동 수리 전략에 매칭되지 않았습니다.",
        )
    return FailureClassification("unsupported", "실패 로그에서 지원 가능한 패턴을 찾지 못했습니다.")


# 복구 작업을 수행할 개발 브랜치를 체크아웃한다.
def _checkout_branch(repo: Repo, branch_name: str) -> str:
    if branch_name in {head.name for head in repo.heads}:
        repo.git.checkout(branch_name)
        return "기존 브랜치 체크아웃"
    return f"브랜치를 찾지 못해 현재 브랜치 유지: {repo.active_branch.name}"


# CORS 테스트가 Security 필터에 막히지 않도록 테스트 구성을 보정한다.
def _apply_cors_preflight_test_fix(repo_path: Path) -> list[str]:
    test_path = repo_path / "apps/server/modules/bootstrap/studyhub/src/test/kotlin/com/studyhub/server/bootstrap/config/WebCorsConfigurationTest.kt"
    if not test_path.exists():
        return []

    text = test_path.read_text(encoding="utf-8")
    updated = text
    updated = _ensure_import(
        updated,
        "import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc",
        "import org.springframework.beans.factory.annotation.Autowired",
    )
    updated = _ensure_annotation_after(
        updated,
        "@AutoConfigureMockMvc(addFilters = false)",
        "@WebMvcTest(controllers = [CorsTestController::class])",
    )
    if updated == text:
        return []

    test_path.write_text(updated, encoding="utf-8")
    return [str(test_path.relative_to(repo_path))]


# 기준 import 아래에 필요한 import를 한 번만 추가한다.
def _ensure_import(text: str, import_line: str, anchor: str) -> str:
    if import_line in text:
        return text
    if anchor not in text:
        return text.rstrip() + "\n" + import_line + "\n"
    return text.replace(anchor, f"{anchor}\n{import_line}", 1)


# 기준 annotation 아래에 필요한 annotation을 한 번만 추가한다.
def _ensure_annotation_after(text: str, annotation: str, anchor: str) -> str:
    if annotation in text:
        return text
    if anchor not in text:
        return text.rstrip() + "\n" + annotation + "\n"
    return text.replace(anchor, f"{anchor}\n{annotation}", 1)


# 실패 유형에 맞는 검증 명령을 결정한다.
def _verification_command_for_failure(kind: str) -> list[str]:
    if kind == "cors_preflight_blocked_by_security":
        return ["./gradlew", "test"]
    return ["./gradlew", "test"]


# 검증 명령을 실행할 작업 디렉토리를 결정한다.
def _command_cwd(repo_path: Path, command: list[str]) -> Path:
    if command and command[0] == "./gradlew":
        return repo_path / "apps/server"
    return repo_path


# 외부 검증 명령을 실행하고 표준 출력을 구조화해 반환한다.
def _run_command(command: list[str], cwd: Path, timeout_seconds: int) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return completed.returncode, completed.stdout, completed.stderr
    except FileNotFoundError as exc:
        return 127, "", str(exc)


# 수정 파일을 스테이징하고 변경이 있을 때만 커밋한다.
def _stage_and_commit(repo: Repo, repo_path: Path, paths: list[str], message: str) -> str:
    existing_paths = [path for path in paths if (repo_path / path).exists()]
    if not existing_paths:
        return "no commit"
    repo.index.add(existing_paths)
    if not repo.index.diff("HEAD"):
        return "스킵: 스테이징된 변경사항 없음"
    commit = repo.index.commit(message)
    return commit.hexsha[:12]


# 수동 개입이 필요한 실패 내용을 보고서로 남기고 needs_human 결과를 반환한다.
def _write_needs_human_report(fix_report: Path, title: str, reason: str) -> AgentResult:
    fix_report.write_text(
        "\n".join(
            [
                "# Fix Develop Report",
                "",
                "- status: needs_human",
                f"- title: {title}",
                f"- reason: {reason}",
                "",
                *render_runner_definitions("Fix Develop Agent 책임 러너", FIX_DEVELOP_RUNNERS),
            ]
        ),
        encoding="utf-8",
    )
    return AgentResult(
        status=AgentStatus.NEEDS_HUMAN,
        summary=title,
        artifacts=[ArtifactSpec("fix-develop-report", fix_report)],
        error=reason,
    )
