from __future__ import annotations

from pathlib import Path

from orchestrator.core.settings import settings
from orchestrator.db.models import Task
from orchestrator.services.github_adapter import GitHubAdapter
from workflows.state_machine import KanbanState, WorkflowEvent


class WorkflowCommandMixin:
    # approval stage 문자열을 상태 머신 이벤트로 변환한다.
    def _approval_event_for_stage(self, stage: str) -> WorkflowEvent:
        mapping = {
            "plan": WorkflowEvent.APPROVE_PLAN,
            "dev": WorkflowEvent.APPROVE_DEV,
            "qa": WorkflowEvent.APPROVE_QA,
            "deploy": WorkflowEvent.APPROVE_DEPLOY,
        }
        try:
            return mapping[stage]
        except KeyError as exc:
            raise ValueError(f"지원하지 않는 승인 stage입니다: {stage}") from exc

    # GitHub Project 칸반 상태를 하네스 task 상태와 맞춘다.
    def _move_github_project_status_best_effort(self, task: Task, run_id: str | None) -> bool:
        issue_number = task.github_issue_number
        if not issue_number or not settings.github_project_number:
            self._audit(
                task.id,
                run_id,
                "github.project_status_skipped",
                {
                    "reason": "missing_issue_number_or_project_number",
                    "issue_number": issue_number,
                    "project_number": settings.github_project_number,
                    "target_state": task.state,
                },
            )
            return False

        try:
            GitHubAdapter(settings.github_token, use_gh_cli=settings.github_use_gh_cli).move_issue_project_status(
                settings.github_owner,
                settings.github_repo,
                int(issue_number),
                int(settings.github_project_number),
                self._github_project_status_name(task.state),
            )
            self._audit(
                task.id,
                run_id,
                "github.project_status_moved",
                {
                    "issue_number": issue_number,
                    "project_number": settings.github_project_number,
                    "target_state": task.state,
                },
            )
            return True
        except Exception as exc:  # noqa: BLE001 - GitHub Project 이동 실패는 승인 자체를 막지 않는다.
            self._audit(
                task.id,
                run_id,
                "github.project_status_move_failed",
                {
                    "issue_number": issue_number,
                    "project_number": settings.github_project_number,
                    "target_state": task.state,
                    "error": str(exc),
                },
            )
            return False

    # 하네스 내부 상태명을 GitHub Project의 실제 칸반 컬럼명으로 변환한다.
    def _github_project_status_name(self, state: str) -> str:
        mapping = {
            KanbanState.BACKLOG.value: "Backlog",
            KanbanState.PLAN_REVIEW.value: "Todo",
            KanbanState.DEV_READY.value: "In progress",
            KanbanState.DEV_REVIEW.value: "In progress",
            KanbanState.QA_READY.value: "AI QA",
            KanbanState.QA_REVIEW.value: "Human QA",
            KanbanState.READY_TO_DEPLOY.value: "Stage",
            KanbanState.DONE.value: "Done",
            KanbanState.CANCELLED.value: "Done",
        }
        return mapping.get(state, state)

    def _next_command_for_state(self, state: str) -> str:
        return {
            KanbanState.BACKLOG.value: settings.design_command,
            KanbanState.PLAN_REVIEW.value: "harness approve --stage plan",
            KanbanState.DEV_READY.value: settings.develop_command,
            KanbanState.DEV_REVIEW.value: "harness approve --stage dev",
            KanbanState.QA_READY.value: settings.qa_command,
            KanbanState.QA_REVIEW.value: "harness approve --stage qa",
            KanbanState.READY_TO_DEPLOY.value: "harness approve --stage deploy",
            "Done": "완료됨",
            "Cancelled": "중지됨. 다시 시작하려면 replan 또는 plan부터 판단",
        }.get(state, settings.status_command)

    def _failure_artifact_open_lines(
        self,
        task: Task,
        command: str | None,
        agent_name: str | None,
    ) -> list[str]:
        artifact_path: Path | None = None
        if agent_name == "qa" or command in {settings.qa_command, settings.reqa_command}:
            artifact_path = settings.artifact_root / task.id / "qa" / "qa-report.md"
        elif agent_name == "dev" or command in {
            settings.develop_command,
            settings.refactor_command,
        }:
            artifact_path = settings.artifact_root / task.id / "dev" / "dev-status.md"
        elif agent_name == "fix_develop" or command == settings.fix_develop_command:
            artifact_path = settings.artifact_root / task.id / "dev" / "fix-develop-report.md"
        elif agent_name in {"plan", "design"} or command in {
            settings.design_command,
            settings.redesign_command,
            settings.plan_command,
            settings.replan_command,
        }:
            artifact_path = settings.artifact_root / task.id / "plans" / "architecture.md"

        if artifact_path is None:
            return []

        absolute_path = artifact_path.expanduser().resolve()
        return [
            "### 상세 리포트 바로 열기",
            f"- artifact: `{absolute_path}`",
            "",
            "IntelliJ에서 바로 열려면 아래 명령을 실행하세요.",
            "",
            "```bash",
            f"open -a \"IntelliJ IDEA\" {absolute_path}",
            "```",
        ]

    def _skip_develop_command(
        self, issue_number: int, reason: str, task_id: str | None = None
    ) -> dict[str, str]:
        self._comment_on_github_issue_best_effort(
            issue_number,
            self._build_develop_not_ready_comment(reason, task_id),
        )
        self.db.commit()
        return {"status": "ignored", "reason": reason}

    def _skip_refactor_command(
        self, issue_number: int, reason: str, task_id: str | None = None
    ) -> dict[str, str]:
        self._comment_on_github_issue_best_effort(
            issue_number,
            self._build_refactor_not_ready_comment(reason, task_id),
        )
        self.db.commit()
        return {"status": "ignored", "reason": reason}

    def _skip_qa_command(
        self,
        issue_number: int,
        reason: str,
        task_id: str | None = None,
        next_command: str | None = None,
    ) -> dict[str, str]:
        self._comment_on_github_issue_best_effort(
            issue_number,
            self._build_qa_not_ready_comment(
                reason,
                task_id,
                next_command or settings.develop_command,
            ),
        )
        self.db.commit()
        return {"status": "ignored", "reason": reason}
