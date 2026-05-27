from pathlib import Path

from agents.base import AgentStatus, ArtifactSpec
from agents.runners.base import DevRunnerContext, DevRunnerResult


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


# 현재 책임 러너의 한계와 필요한 사람 판단을 artifact로 남긴다.
def _write_capability_report(
    context: DevRunnerContext,
    runner_name: str,
    responsibility: str,
) -> Path:
    report = context.task_dir / f"{runner_name}.md"
    report.write_text(
        "\n".join(
            [
                f"# {runner_name}",
                "",
                f"- branch: `{context.branch_name}`",
                f"- issue_type: `{context.issue_type}`",
                f"- responsibility: {responsibility}",
                "",
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
