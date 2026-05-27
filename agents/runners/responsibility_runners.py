from pathlib import Path
import subprocess

from agents.base import AgentStatus, ArtifactSpec
from agents.runners.base import DevRunnerContext, DevRunnerResult
from agents.runners.codebase_inspector import (
    backend_test_commands,
    extract_frontend_route,
    frontend_test_commands,
    inspect_codebase,
    next_page_path,
    render_codebase_snapshot,
)


class ResponsibilityCapabilityRunner:
    name = "responsibility_capability_runner"
    responsibility = "정의되지 않은 책임"
    supported_issue_types: set[str] = set()

    # 이 책임 러너가 현재 이슈 타입에서 필요한지 판단한다.
    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type in self.supported_issue_types

    # 현재 책임 러너의 자동 구현 가능 여부를 보고하고 안전하게 중단한다.
    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        report = _write_capability_report(
            context=context,
            runner_name=self.name,
            responsibility=self.responsibility,
        )
        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary=f"{self.name}가 필요한 책임을 식별했지만 아직 자동 구현 capability가 없습니다.",
            progress=[
                f"- [x] {self.name} 필요성 확인",
                f"- [ ] {self.responsibility} 자동 구현 capability 확보",
            ],
            verification=[
                f"## {self.name}",
                "",
                "- status: needs_human",
                f"- responsibility: {self.responsibility}",
                "- reason: 아직 이 책임 러너는 자동 구현 대신 capability gate로만 동작합니다.",
            ],
            artifacts=[ArtifactSpec(self.name, report)],
            error=f"{self.name}: 아직 자동 구현 capability가 없습니다. {report.name}을 확인하세요.",
        )


class DDDModelingRunner(ResponsibilityCapabilityRunner):
    name = "ddd_modeling_runner"
    responsibility = "도메인 모델, 정책, 유스케이스 흐름 구현"
    supported_issue_types = {"beFeature", "fullstackFeature", "bugfix", "hotfix"}


class DBMigrationRunner(ResponsibilityCapabilityRunner):
    name = "db_migration_runner"
    responsibility = "DB schema, nullable, unique, index, migration 구현"
    supported_issue_types = {"beFeature", "fullstackFeature", "config", "infra"}


class APIImplementationRunner(ResponsibilityCapabilityRunner):
    name = "api_implementation_runner"
    responsibility = "API endpoint, request/response, application 연결 구현"
    supported_issue_types = {"beFeature", "fullstackFeature", "apiConnect"}


class FrontendImplementationRunner(ResponsibilityCapabilityRunner):
    name = "frontend_implementation_runner"
    responsibility = "화면, 상태, 폼, 사용자 메시지 구현"
    supported_issue_types = {"feFeature", "fullstackFeature", "apiConnect"}

    # route가 명확한 프론트엔드 작업은 안전한 page scaffold까지 생성한다.
    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        route = extract_frontend_route(f"{context.title}\n{context.body}")
        if route is None:
            return super().run(context)

        page_path = next_page_path(context.repo_path, route)
        report = context.task_dir / f"{self.name}.md"
        snapshot = inspect_codebase(context)
        changed_paths: list[str] = []
        commits: list[str] = []

        if not page_path.exists():
            _write_text(page_path, _frontend_page_scaffold(context, route))
            relative = _relative(context, page_path)
            changed_paths.append(relative)
            commit_hash = _stage_and_commit(
                context,
                changed_paths,
                f"[{context.feature_name}] : {route} 화면 scaffold 추가",
            )
            commits.append(f"1. {commit_hash} [{context.feature_name}] : {route} 화면 scaffold 추가")

        report.write_text(
            "\n".join(
                [
                    f"# {self.name}",
                    "",
                    f"- branch: `{context.branch_name}`",
                    f"- issue_type: `{context.issue_type}`",
                    f"- responsibility: {self.responsibility}",
                    f"- route: `{route}`",
                    f"- page_path: `{page_path}`",
                    f"- changed_paths: `{', '.join(changed_paths) if changed_paths else 'none'}`",
                    "",
                    *render_codebase_snapshot(snapshot),
                    "## Capability",
                    "",
                    "- status: partial",
                    "- 명확한 route가 있는 경우 Next.js page scaffold를 생성합니다.",
                    "- 세부 UI, 상태, API 연동은 아직 사람이 검토해야 합니다.",
                ]
            ),
            encoding="utf-8",
        )

        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary=f"{self.name}가 {route} 화면 scaffold를 점검했습니다.",
            commits=commits,
            progress=[
                f"- [x] {self.name} route 분석",
                f"- [{'x' if changed_paths else ' '}] {route} page scaffold 생성",
                "- [ ] 세부 UI/상태/API 연동 구현",
            ],
            verification=[
                f"## {self.name}",
                "",
                "- status: needs_human",
                f"- route: `{route}`",
                "- reason: scaffold 이후 상세 화면 구현은 아직 사람 검토가 필요합니다.",
            ],
            artifacts=[ArtifactSpec(self.name, report)],
            error=f"{self.name}: scaffold 이후 상세 구현 capability가 부족합니다. {report.name}을 확인하세요.",
        )


class APIConnectRunner(ResponsibilityCapabilityRunner):
    name = "api_connect_runner"
    responsibility = "프론트엔드 요청과 백엔드 API contract 연결"
    supported_issue_types = {"apiConnect", "fullstackFeature"}


class EventFlowRunner(ResponsibilityCapabilityRunner):
    name = "event_flow_runner"
    responsibility = "비동기 이벤트, 실시간 흐름, 상태 전이 구현"
    supported_issue_types = {"fullstackFeature", "beFeature"}

    # 이벤트성 키워드가 있는 경우에만 이 책임 러너를 활성화한다.
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

    # 사람의 리팩터링 요청이 있는 경우에만 이 책임 러너를 활성화한다.
    def can_handle(self, context: DevRunnerContext) -> bool:
        return super().can_handle(context) and "## Human Refactor Request" in context.body


class TestImplementationRunner(ResponsibilityCapabilityRunner):
    name = "test_implementation_runner"
    responsibility = "단위, 통합, smoke 테스트 작성과 실행"
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

    # 현재 코드베이스에 존재하는 테스트 명령을 선택해 실제 검증을 실행한다.
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
                        "## Test Capability",
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

        command_results = [_run_command(command, _command_cwd(context, command), context.timeout_seconds) for command in commands]
        all_passed = all(exit_code == 0 for command, exit_code, _, _ in command_results)
        report.write_text(
            "\n".join(
                [
                    f"# {self.name}",
                    "",
                    f"- branch: `{context.branch_name}`",
                    f"- issue_type: `{context.issue_type}`",
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
                    for command, exit_code, _, _ in command_results
                ],
            ],
            artifacts=[ArtifactSpec(self.name, report)],
            error=None if all_passed else f"{self.name}: 테스트 명령이 실패했습니다. {report.name}을 확인하세요.",
        )


# 현재 책임 러너의 한계와 필요한 사람 판단을 artifact로 남긴다.
def _write_capability_report(
    context: DevRunnerContext,
    runner_name: str,
    responsibility: str,
) -> Path:
    report = context.task_dir / f"{runner_name}.md"
    snapshot = inspect_codebase(context)
    report.write_text(
        "\n".join(
            [
                f"# {runner_name}",
                "",
                f"- branch: `{context.branch_name}`",
                f"- issue_type: `{context.issue_type}`",
                f"- responsibility: {responsibility}",
                "",
                *render_codebase_snapshot(snapshot),
                "## Capability Gate",
                "",
                "- status: needs_human",
                "- 현재 이 책임 러너는 범용 구조상 필요한 책임을 식별하지만 자동 구현은 아직 수행하지 않습니다.",
                "- 가짜 성공을 만들지 않기 위해 구현을 중단합니다.",
                "",
                "## 다음 업그레이드 방향",
                "",
                "- 이 책임의 입력 artifact 형식을 고정한다.",
                "- 코드베이스 분석 규칙을 추가한다.",
                "- 수정 가능한 파일 범위와 테스트 명령을 명확히 한다.",
                "- 성공/실패 판정 기준을 테스트로 고정한다.",
            ]
        ),
        encoding="utf-8",
    )
    return report


# UTF-8 텍스트 파일을 생성하고 상위 디렉토리를 보장한다.
def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# 저장소 기준 상대 경로를 반환한다.
def _relative(context: DevRunnerContext, path: Path) -> str:
    return str(path.relative_to(context.repo_path))


# 변경 파일을 스테이징하고 실제 변경이 있을 때만 커밋한다.
def _stage_and_commit(context: DevRunnerContext, paths: list[str], message: str) -> str:
    existing_paths = [path for path in paths if (context.repo_path / path).exists()]
    if not existing_paths:
        return "no commit"
    context.repo.index.add(existing_paths)
    if not context.repo.index.diff("HEAD"):
        return "스킵: 스테이징된 변경사항 없음"
    commit = context.repo.index.commit(message)
    return commit.hexsha[:12]


# route 기반 Next.js page scaffold 내용을 만든다.
def _frontend_page_scaffold(context: DevRunnerContext, route: str) -> str:
    return "\n".join(
        [
            "export default function HarnessGeneratedPage() {",
            "  return (",
            '    <main className="min-h-screen bg-background px-6 py-10 text-foreground">',
            '      <section className="mx-auto flex w-full max-w-3xl flex-col gap-4">',
            f'        <p className="text-sm font-medium text-muted-foreground">{route}</p>',
            f'        <h1 className="text-3xl font-semibold tracking-normal">{context.feature_name}</h1>',
            '        <p className="text-muted-foreground">',
            "          이 화면은 AI Harness가 route를 기준으로 생성한 초기 scaffold입니다.",
            "          실제 UX, 상태 관리, API 연동은 후속 구현에서 구체화해야 합니다.",
            "        </p>",
            "      </section>",
            "    </main>",
            "  )",
            "}",
            "",
        ]
    )


# 이슈 타입에 맞는 테스트 명령 목록을 결정한다.
def _test_commands_for_context(context: DevRunnerContext, snapshot) -> list[list[str]]:
    if context.issue_type == "feFeature":
        return frontend_test_commands(snapshot)
    if context.issue_type == "beFeature":
        return backend_test_commands(snapshot)
    if context.issue_type in {"fullstackFeature", "apiConnect"}:
        return backend_test_commands(snapshot) + frontend_test_commands(snapshot)
    if context.issue_type in {"config", "infra", "bugfix", "hotfix"}:
        return backend_test_commands(snapshot) + frontend_test_commands(snapshot)
    return []


# 테스트 명령을 실행할 작업 디렉토리를 결정한다.
def _command_cwd(context: DevRunnerContext, command: list[str]) -> Path:
    if command and command[0] == "./gradlew":
        return context.repo_path / "apps/server"
    return context.repo_path


# 외부 명령을 실행하고 표준 출력과 오류를 반환한다.
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


# 명령 실행 결과를 Markdown 섹션으로 변환한다.
def _format_command_result(command: list[str], exit_code: int, stdout: str, stderr: str) -> list[str]:
    return [
        f"## Command: {' '.join(command)}",
        "",
        f"- exit_code: `{exit_code}`",
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
