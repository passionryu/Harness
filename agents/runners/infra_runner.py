from agents.base import AgentStatus
from agents.runners.base import DevRunnerContext, DevRunnerResult


class InfraRunner:
    name = "infra_runner"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type in {"infra", "config"}

    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary="Infra Runner가 선택되었지만 아직 인프라/config 자동 구현은 활성화되어 있지 않습니다.",
            progress=["- [ ] 인프라/config 자동 구현"],
            error="Infra Runner는 아직 활성화되어 있지 않습니다.",
        )
