from agents.base import AgentStatus
from agents.runners.base import DevRunnerContext, DevRunnerResult


class DocsRunner:
    name = "docs_runner"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type == "docs"

    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary="Docs runner selected, but automated docs implementation is not enabled yet.",
            progress=["- [ ] Automated docs runner implementation"],
            error="Automated docs runner is not enabled yet.",
        )
