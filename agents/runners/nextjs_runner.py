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
                summary="Next.js Runner가 선택되었지만 아직 이 프론트엔드 계획은 자동 구현을 지원하지 않습니다.",
                progress=[
                    "- [x] Next.js Runner 선택",
                    "- [ ] 계획 기반 범용 프론트엔드 구현",
                ],
                verification=[
                    "## nextjs_runner",
                    "",
                    "- status: needs_human",
                    "- reason: 현재는 회원가입 화면 자동화만 지원합니다.",
                ],
                error="현재는 회원가입 화면 자동화만 지원합니다.",
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
                f"{self.name}가 {context.branch_name}에서 구현을 완료했습니다. "
                f"커밋 기록 {len(commits)}개가 생성되었습니다."
            ),
            commits=commits,
            progress=progress,
            verification=verification,
        )
