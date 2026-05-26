from agents.base import AgentStatus
from agents.runners.base import DevRunnerContext, DevRunnerResult


class DocsRunner:
    name = "docs_runner"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type == "docs"

    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary="Docs Runner가 선택되었지만 아직 문서 자동 구현은 활성화되어 있지 않습니다.",
            progress=["- [ ] 문서 자동 구현"],
            error="Docs Runner는 아직 활성화되어 있지 않습니다.",
        )
