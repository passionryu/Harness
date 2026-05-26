from agents.base import AgentStatus
from agents.runners.base import DevRunnerContext, DevRunnerResult


class NextJsRunner:
    name = "nextjs_runner"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type in {"feFeature", "apiConnect"} and (
            context.repo_path / "apps/web/package.json"
        ).exists()

    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        from agents.dev_agent import _implement_signup_feature, _is_signup_feature

        if not _is_signup_feature(context.issue_type, context.title, context.body):
            return DevRunnerResult(
                status=AgentStatus.NEEDS_HUMAN,
                summary="Next.js runner selected, but this frontend plan is not supported yet.",
                progress=[
                    "- [x] Next.js runner selected",
                    "- [ ] Plan-based generic frontend implementation",
                ],
                verification=[
                    "## nextjs_runner",
                    "",
                    "- status: needs_human",
                    "- reason: only signup frontend automation is enabled yet",
                ],
                error="Only signup frontend automation is enabled yet.",
            )

        commits, progress, verification = _implement_signup_feature(
            repo=context.repo,
            repo_path=context.repo_path,
            feature_name=context.feature_name,
            timeout_seconds=context.timeout_seconds,
        )
        return DevRunnerResult(
            status=AgentStatus.SUCCESS,
            summary=(
                f"{self.name} completed implementation on "
                f"{context.branch_name}. {len(commits)} commit entries recorded."
            ),
            commits=commits,
            progress=progress,
            verification=verification,
        )
