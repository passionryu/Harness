from agents.base import AgentStatus
from agents.runners.base import DevRunnerContext, DevRunnerResult


class InfraRunner:
    name = "infra_runner"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type in {"infra", "config"}

    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary="Infra runner selected, but automated infra/config implementation is not enabled yet.",
            progress=["- [ ] Automated infra/config runner implementation"],
            error="Automated infra/config runner is not enabled yet.",
        )
