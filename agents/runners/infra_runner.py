from agents.base import AgentStatus, ArtifactSpec
from agents.runners.base import DevRunnerContext, DevRunnerResult


class InfraRunner:
    name = "infra_runner"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type in {"infra", "config"}

    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        report = context.task_dir / "infra-runner.md"
        report.write_text(
            "\n".join(
                [
                    "# Infra Runner",
                    "",
                    f"- runner: `{self.name}`",
                    f"- issue_type: `{context.issue_type}`",
                    f"- branch: `{context.branch_name}`",
                    "- role: codex handoff adapter",
                    "- repository_changes: none",
                    "- commit: none",
                    "",
                    "## Codex Playbook",
                    "",
                    "- `agents/playbooks/infra-config.md`를 기준으로 Codex가 직접 구현한다.",
                    "- runner는 Spring Security, JWT, Redis, Grafana, Loki 설정 파일을 생성하지 않는다.",
                    "- runner는 infra/config 작업을 감지하고 artifact로 넘기는 역할만 한다.",
                    "",
                    "## Tool Adapter Boundary",
                    "",
                    "- 코드로 남길 수 있는 영역: 명령 실행, health check, 로그 수집, artifact 저장",
                    "- Markdown으로 관리할 영역: 설정 설계, 파일 수정 순서, 검증 기준, rollback 기준",
                    "",
                    "## 다음 실행",
                    "",
                    "1. Codex가 `agents/playbooks/infra-config.md`를 읽는다.",
                    "2. 대상 설정 파일과 배포 환경을 확인한다.",
                    "3. 필요한 변경을 직접 구현하고 테스트한다.",
                    "4. Dev/QA artifact에 검증 결과와 rollback notes를 남긴다.",
                ]
            ),
            encoding="utf-8",
        )
        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary="Infra Runner는 자동 설정 생성을 중단하고 Codex infra-config playbook handoff만 남겼습니다.",
            progress=[
                "- [x] infra/config 작업 감지",
                "- [x] Codex playbook handoff 생성",
                "- [ ] Codex가 infra-config playbook 기준으로 직접 구현",
            ],
            verification=[
                "## infra_runner",
                "",
                "- status: needs_human",
                "- playbook: `agents/playbooks/infra-config.md`",
                "- reason: runner는 자동 개발자가 아니라 도구/인수인계 adapter로만 동작합니다.",
            ],
            artifacts=[ArtifactSpec("infra-runner-report", report)],
            error="infra/config 자동 구현은 비활성화되었습니다. Codex가 infra-config playbook 기준으로 구현해야 합니다.",
        )
