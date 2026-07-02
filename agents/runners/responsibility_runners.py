import re
import subprocess
from pathlib import Path

from agents.base import AgentStatus, ArtifactSpec
from agents.runners.base import DevRunnerContext, DevRunnerResult
from agents.runners.codebase_inspector import (
    backend_test_commands,
    extract_api_endpoint,
    extract_frontend_route,
    frontend_test_commands,
    inspect_codebase,
    render_codebase_snapshot,
)


FRONTEND_ISSUE_KEYWORDS = [
    "[fe]",
    "frontend",
    "front-end",
    "next.js",
    "nextjs",
    "react",
    "프론트",
    "화면",
    "ui",
    "ux",
    "css",
    "색상",
    "테마",
    "설정",
    "버튼",
    "모달",
    "localstorage",
]

BACKEND_PROMPT_POLICY_KEYWORDS = [
    "openai",
    "gpt",
    "llm",
    "프롬프트",
    "prompt",
    "응답 정책",
    "응답 품질",
    "답변 품질",
    "마음이",
    "ai 마음",
    "챗봇 응답",
    "mindchatresponsepolicy",
    "openaichatclient",
]

BACKEND_ISSUE_KEYWORDS = [
    "[be]",
    "backend",
    "back-end",
    "api",
    "/api/",
    "server",
    "spring",
    "kotlin",
    "jpa",
    "db",
    "database",
    "redis",
    "백엔드",
    "서버",
    "도메인",
    "유스케이스",
    "컨트롤러",
    "데이터베이스",
    *BACKEND_PROMPT_POLICY_KEYWORDS,
]


def is_frontend_change_context(context: DevRunnerContext) -> bool:
    if context.issue_type in {"feFeature", "apiConnect"}:
        return True
    if context.issue_type == "fullstackFeature":
        return False
    if context.issue_type not in {"bugfix", "hotfix"}:
        return False
    haystack = f"{context.title}\n{context.body}".lower()
    if any(keyword in haystack for keyword in BACKEND_PROMPT_POLICY_KEYWORDS):
        return False
    return any(keyword in haystack for keyword in FRONTEND_ISSUE_KEYWORDS) or (
        extract_frontend_route(haystack) is not None
    )


def is_backend_change_context(context: DevRunnerContext) -> bool:
    if context.issue_type in {"beFeature", "fullstackFeature"}:
        return True
    if context.issue_type not in {"bugfix", "hotfix"}:
        return False
    haystack = f"{context.title}\n{context.body}".lower()
    if any(keyword in haystack for keyword in BACKEND_PROMPT_POLICY_KEYWORDS):
        return True
    if is_frontend_change_context(context) and "[be]" not in haystack and "백엔드" not in haystack:
        return False
    if any(keyword in haystack for keyword in BACKEND_ISSUE_KEYWORDS):
        return True
    return extract_api_endpoint(haystack) is not None and not is_frontend_change_context(context)


class ResponsibilityCapabilityRunner:
    name = "responsibility_capability_runner"
    responsibility = "정의되지 않은 책임"
    supported_issue_types: set[str] = set()
    playbook = "frontend-implementation"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type in self.supported_issue_types

    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        report = _write_codex_handoff_report(
            context=context,
            runner_name=self.name,
            responsibility=self.responsibility,
            playbook=self.playbook,
        )
        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary=(
                f"{self.name}가 필요한 책임을 식별했습니다. "
                f"구현은 agents/playbooks/{self.playbook}.md 기준으로 Codex가 수행해야 합니다."
            ),
            progress=[
                f"- [x] {self.name} 필요성 확인",
                f"- [ ] `agents/playbooks/{self.playbook}.md` 기준으로 Codex 구현",
            ],
            verification=[
                f"## {self.name}",
                "",
                "- status: needs_human",
                f"- playbook: `agents/playbooks/{self.playbook}.md`",
                "- reason: runner는 자동 개발자가 아니라 Codex handoff adapter로 동작합니다.",
            ],
            artifacts=[ArtifactSpec(self.name, report)],
            error=(
                f"{self.name}: 자동 구현은 비활성화되었습니다. "
                f"`agents/playbooks/{self.playbook}.md`를 기준으로 Codex가 구현해야 합니다."
            ),
        )


class DDDModelingRunner(ResponsibilityCapabilityRunner):
    name = "ddd_modeling_runner"
    responsibility = "도메인 모델, 정책, 유스케이스 흐름 구현"
    supported_issue_types = {"beFeature", "fullstackFeature", "bugfix", "hotfix"}
    playbook = "backend-kotlin-spring"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return super().can_handle(context) and is_backend_change_context(context)


class DBMigrationRunner(ResponsibilityCapabilityRunner):
    name = "db_migration_runner"
    responsibility = "DB schema, nullable, unique, index, migration 구현"
    supported_issue_types = {"beFeature", "fullstackFeature", "config", "infra"}
    playbook = "backend-kotlin-spring"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type in self.supported_issue_types and _extract_sql_ddl(context) is not None


class APIImplementationRunner(ResponsibilityCapabilityRunner):
    name = "api_implementation_runner"
    responsibility = "API endpoint, request/response, application 연결 구현"
    supported_issue_types = {"beFeature", "fullstackFeature"}
    playbook = "backend-kotlin-spring"


class FrontendImplementationRunner(ResponsibilityCapabilityRunner):
    name = "frontend_implementation_runner"
    responsibility = "화면, 상태, 폼, 사용자 메시지 구현"
    supported_issue_types = {"feFeature", "fullstackFeature", "bugfix", "hotfix"}
    playbook = "frontend-implementation"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return super().can_handle(context) and (
            context.issue_type in {"feFeature", "fullstackFeature"} or is_frontend_change_context(context)
        )


class APIConnectRunner(ResponsibilityCapabilityRunner):
    name = "api_connect_runner"
    responsibility = "프론트엔드 요청과 백엔드 API contract 연결"
    supported_issue_types = {"apiConnect", "fullstackFeature"}
    playbook = "api-connect"


class EventFlowRunner(ResponsibilityCapabilityRunner):
    name = "event_flow_runner"
    responsibility = "비동기 이벤트, 실시간 흐름, 상태 전이 구현"
    supported_issue_types = {"fullstackFeature", "beFeature"}
    playbook = "backend-kotlin-spring"

    def can_handle(self, context: DevRunnerContext) -> bool:
        haystack = f"{context.title}\n{context.body}".lower()
        has_event_flow = any(
            keyword in haystack
            for keyword in ["event", "websocket", "chat", "message", "알림", "채팅", "실시간", "이벤트"]
        )
        return super().can_handle(context) and has_event_flow


class RefactoringRunner(ResponsibilityCapabilityRunner):
    name = "refactoring_runner"
    responsibility = "기존 구현의 책임 분리와 구조 개선"
    supported_issue_types = {
        "beFeature",
        "feFeature",
        "fullstackFeature",
        "apiConnect",
        "bugfix",
        "hotfix",
    }
    playbook = "backend-kotlin-spring"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return super().can_handle(context) and "## Human Refactor Request" in context.body


class TestImplementationRunner(ResponsibilityCapabilityRunner):
    name = "test_implementation_runner"
    responsibility = "단위, 통합, smoke 테스트 실행"
    supported_issue_types = {
        "beFeature",
        "feFeature",
        "fullstackFeature",
        "apiConnect",
        "bugfix",
        "hotfix",
        "config",
        "infra",
    }
    playbook = "qa-verification"

    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        snapshot = inspect_codebase(context)
        commands = _test_commands_for_context(context, snapshot)
        report = context.task_dir / f"{self.name}.md"

        if not commands:
            report.write_text(
                "\n".join(
                    [
                        f"# {self.name}",
                        "",
                        f"- branch: `{context.branch_name}`",
                        f"- issue_type: `{context.issue_type}`",
                        "",
                        *render_codebase_snapshot(snapshot),
                        "## Tool Adapter",
                        "",
                        "- status: needs_human",
                        "- 실행 가능한 테스트 명령을 찾지 못했습니다.",
                    ]
                ),
                encoding="utf-8",
            )
            return DevRunnerResult(
                status=AgentStatus.NEEDS_HUMAN,
                summary="실행 가능한 테스트 명령을 찾지 못했습니다.",
                progress=["- [ ] 테스트 명령 식별"],
                verification=["## test_implementation_runner", "", "- status: needs_human"],
                artifacts=[ArtifactSpec(self.name, report)],
                error=f"{self.name}: 실행 가능한 테스트 명령을 찾지 못했습니다.",
            )

        command_results = [
            _run_command(command, _command_cwd(context, command), context.timeout_seconds)
            for command in commands
        ]
        all_passed = all(exit_code == 0 for _command, exit_code, _stdout, _stderr in command_results)
        report.write_text(
            "\n".join(
                [
                    f"# {self.name}",
                    "",
                    f"- branch: `{context.branch_name}`",
                    f"- issue_type: `{context.issue_type}`",
                    "- role: tool adapter",
                    f"- result: `{'pass' if all_passed else 'fail'}`",
                    "",
                    *render_codebase_snapshot(snapshot),
                    *[
                        line
                        for command, exit_code, stdout, stderr in command_results
                        for line in _format_command_result(command, exit_code, stdout, stderr)
                    ],
                ]
            ),
            encoding="utf-8",
        )
        return DevRunnerResult(
            status=AgentStatus.SUCCESS if all_passed else AgentStatus.FAILED,
            summary=f"테스트 명령 {len(commands)}개를 실행했고 {'통과했습니다' if all_passed else '실패했습니다'}.",
            progress=[f"- [{'x' if all_passed else ' '}] 테스트 명령 {len(commands)}개 실행"],
            verification=[
                "## test_implementation_runner",
                "",
                f"- result: `{'pass' if all_passed else 'fail'}`",
                *[
                    f"- command: `{' '.join(command)}`, exit_code={exit_code}"
                    for command, exit_code, _stdout, _stderr in command_results
                ],
            ],
            artifacts=[ArtifactSpec(self.name, report)],
            error=None if all_passed else f"{self.name}: 테스트 명령이 실패했습니다. {report.name}을 확인하세요.",
        )


def _write_codex_handoff_report(
    context: DevRunnerContext,
    runner_name: str,
    responsibility: str,
    playbook: str,
) -> Path:
    report = context.task_dir / f"{runner_name}.md"
    snapshot = inspect_codebase(context)
    endpoint = extract_api_endpoint(f"{context.title}\n{context.body}")
    route = extract_frontend_route(f"{context.title}\n{context.body}")
    ddl = _extract_sql_ddl(context)
    report.write_text(
        "\n".join(
            [
                f"# {runner_name}",
                "",
                f"- branch: `{context.branch_name}`",
                f"- issue_type: `{context.issue_type}`",
                f"- responsibility: {responsibility}",
                f"- playbook: `agents/playbooks/{playbook}.md`",
                "- role: codex handoff adapter",
                "- repository_changes: none",
                "- commit: none",
                "",
                *render_codebase_snapshot(snapshot),
                "## Detected Inputs",
                "",
                f"- api_endpoint: `{_format_endpoint(endpoint)}`",
                f"- frontend_route: `{route or 'none'}`",
                f"- sql_ddl: `{_summarize_ddl(ddl)}`",
                "",
                "## Codex Handoff",
                "",
                f"- `agents/playbooks/{playbook}.md`를 먼저 읽고 구현한다.",
                "- runner는 앱 코드를 생성하지 않는다.",
                "- 필요한 파일 수정, 테스트 선택, 커밋 단위 판단은 Codex가 수행한다.",
                "- 구현 후 `test_implementation_runner` 또는 QA Agent로 검증한다.",
            ]
        ),
        encoding="utf-8",
    )
    return report


def _format_endpoint(endpoint: tuple[str, str] | None) -> str:
    if endpoint is None:
        return "none"
    method, path = endpoint
    return f"{method} {path}"


def _extract_sql_ddl(context: DevRunnerContext) -> str | None:
    match = re.search(r"```sql\s*(.*?)```", context.body, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    ddl = match.group(1).strip()
    return ddl or None


def _summarize_ddl(ddl: str | None) -> str:
    if not ddl:
        return "none"
    first_line = ddl.splitlines()[0].strip()
    return first_line[:120]


def _test_commands_for_context(context: DevRunnerContext, snapshot) -> list[list[str]]:
    frontend_commands = frontend_test_commands(snapshot)
    backend_commands = backend_test_commands(snapshot)
    if is_frontend_change_context(context):
        return frontend_commands
    if is_backend_change_context(context):
        return backend_commands
    if context.issue_type in {"config", "infra"}:
        return backend_commands or frontend_commands
    if context.issue_type == "apiConnect":
        return frontend_commands + backend_commands
    if context.issue_type == "fullstackFeature":
        return frontend_commands + backend_commands
    return frontend_commands + backend_commands


def _command_cwd(context: DevRunnerContext, command: list[str]) -> Path:
    if command and command[0] == "./gradlew":
        return context.repo_path / "apps/server"
    return context.repo_path


def _run_command(command: list[str], cwd: Path, timeout_seconds: int) -> tuple[list[str], int, str, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return command, completed.returncode, completed.stdout, completed.stderr
    except FileNotFoundError as exc:
        return command, 127, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        return command, 124, exc.stdout or "", exc.stderr or str(exc)


def _format_command_result(command: list[str], exit_code: int, stdout: str, stderr: str) -> list[str]:
    return [
        f"## Command: {' '.join(command)}",
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
        "",
    ]
