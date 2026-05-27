import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.base import AgentInput, AgentStatus
from agents.plan_agent import (
    _flow_chart_for_issue_type,
    _profile_for_issue_type,
    _sequence_diagram_for_issue_type,
)
from orchestrator.api.schemas import EventResult, HumanApproval, ManualEvent, TaskCreate
from orchestrator.core.settings import settings
from orchestrator.db.models import AuditLog, Run, StateTransition, Task
from orchestrator.services.agent_registry import AgentRegistry
from orchestrator.services.artifacts import ArtifactStore
from orchestrator.services.discord import DiscordNotifier
from orchestrator.services.github_adapter import GitHubAdapter
from orchestrator.services.google_chat import GoogleChatNotifier
from workflows.state_machine import StateMachine, WorkflowEvent

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST)


class OrchestrationService:
    def __init__(self, db: Session):
        self.db = db
        self.state_machine = StateMachine()
        self.agent_registry = AgentRegistry()
        self.artifact_store = ArtifactStore(db)

    def create_task(self, payload: TaskCreate) -> Task:
        task = Task(
            title=payload.title,
            body=payload.body,
            github_issue_url=payload.github_issue_url,
            github_issue_number=payload.github_issue_number,
            state="Backlog",
            retry_limit=settings.agent_retry_limit,
        )
        self.db.add(task)
        self.db.flush()
        self._record_transition(task.id, None, task.state, "task created", "human")
        self._audit(task.id, None, "task.created", {"title": task.title})
        self.db.commit()
        self.db.refresh(task)
        return task

    def get_task(self, task_id: str) -> Task | None:
        return self.db.scalar(select(Task).where(Task.id == task_id))

    def upsert_github_issue_task(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
    ) -> Task:
        task = self.db.scalar(select(Task).where(Task.github_issue_number == issue_number))
        if task is None:
            task = Task(
                title=title,
                body=body,
                github_issue_url=issue_url,
                github_issue_number=issue_number,
                state="Todo",
                retry_limit=settings.agent_retry_limit,
            )
            self.db.add(task)
            self.db.flush()
            self._record_transition(task.id, None, task.state, "GitHub issue plan-ready", "system")
            self._audit(
                task.id,
                None,
                "task.created_from_github",
                {"issue_number": issue_number, "issue_url": issue_url},
            )
        else:
            task.title = title
            task.body = body
            task.github_issue_url = issue_url
            if task.state == "Backlog":
                previous = task.state
                task.state = "Todo"
                self._record_transition(
                    task.id,
                    previous,
                    task.state,
                    "GitHub issue plan-ready",
                    "system",
                )
        return task

    def has_successful_agent_run(self, task_id: str, agent_name: str) -> bool:
        return (
            self.db.scalar(
                select(Run.id)
                .where(Run.task_id == task_id)
                .where(Run.agent_name == agent_name)
                .where(Run.status == AgentStatus.SUCCESS.value)
                .limit(1)
            )
            is not None
        )

    def run_plan_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        force: bool = False,
        replan_request: str | None = None,
        comment_on_duplicate: bool = False,
        issue_labels: list[str] | None = None,
    ) -> EventResult:
        body = self._append_issue_metadata(body, issue_labels or [], issue_number)
        if replan_request:
            body = self._append_replan_request(body, replan_request)
        task = self.upsert_github_issue_task(issue_number, title, body, issue_url)
        previous = task.state

        if not force and self.has_successful_agent_run(task.id, "plan"):
            self._audit(
                task.id,
                None,
                "plan.skipped_duplicate",
                {"issue_number": issue_number, "comment_on_duplicate": comment_on_duplicate},
            )
            if settings.github_token and comment_on_duplicate:
                GitHubAdapter(settings.github_token).create_issue_comment(
                    settings.github_owner,
                    settings.github_repo,
                    issue_number,
                    self._build_duplicate_plan_comment(task),
                )
                self._audit(
                    task.id,
                    None,
                    "github.duplicate_plan_commented",
                    {"issue_number": issue_number},
                )
            self.db.commit()
            return EventResult(
                task_id=task.id,
                previous_state=previous,
                current_state=task.state,
                message="이미 Plan이 완료되어 중복 실행을 스킵했습니다.",
            )

        run_id = self._run_agent(task, "plan")
        self._audit(
            task.id,
            run_id,
            "plan.completed" if not force else "plan.replanned",
            {
                "issue_number": issue_number,
                "issue_url": issue_url,
                "force": force,
                "has_replan_request": bool(replan_request),
            },
        )

        if settings.github_token:
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
                issue_number,
                self._build_plan_comment(task),
            )
            self._audit(
                task.id,
                run_id,
                "github.issue_commented",
                {"issue_number": issue_number},
            )
        else:
            self._audit(
                task.id,
                run_id,
                "github.comment_skipped",
                {"reason": "GITHUB_TOKEN이 설정되어 있지 않습니다.", "issue_number": issue_number},
            )

        self.db.commit()
        return EventResult(
            task_id=task.id,
            previous_state=previous,
            current_state=task.state,
            message="GitHub 이슈 트리거로 Plan을 생성했습니다.",
        )

    def run_replan_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        replan_request: str,
        issue_labels: list[str] | None = None,
    ) -> EventResult:
        return self.run_plan_for_github_issue(
            issue_number=issue_number,
            title=title,
            body=body,
            issue_url=issue_url,
            force=True,
            replan_request=replan_request,
            issue_labels=issue_labels,
        )

    def run_develop_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
    ) -> EventResult | dict[str, str]:
        task = self.db.scalar(select(Task).where(Task.github_issue_number == issue_number))
        if task is None:
            return self._skip_develop_command(
                issue_number,
                "Plan을 찾을 수 없습니다. 먼저 @ai-harness plan을 실행하세요.",
            )

        task.title = title
        task.body = self._append_issue_metadata(body, issue_labels or [], issue_number)
        task.github_issue_url = issue_url

        if not self.has_successful_agent_run(task.id, "plan"):
            return self._skip_develop_command(
                issue_number,
                "성공한 Plan 실행 기록이 없습니다. 먼저 @ai-harness plan을 실행하세요.",
                task.id,
            )

        if task.state not in {"Todo", "In Progress"}:
            return self._skip_develop_command(
                issue_number,
                f"현재 작업 상태는 `{task.state}`입니다. develop은 `Todo` 또는 `In Progress`에서만 실행할 수 있습니다.",
                task.id,
            )

        previous = task.state
        run_id: str | None = None
        if task.state == "Todo":
            decision = self.state_machine.decide(task.state, WorkflowEvent.START_DEV.value)
            if decision.requires_agent:
                run_id = self._run_agent(task, decision.requires_agent)
            task.state = decision.to_state.value
            self._record_transition(
                task.id,
                previous,
                task.state,
                f"plan approved by {settings.develop_command}",
                "human",
            )
        else:
            run_id = self._run_agent(task, "dev")

        self._audit(
            task.id,
            run_id,
            "plan.approved_for_development" if previous == "Todo" else "dev.continued",
            {"issue_number": issue_number, "issue_url": issue_url},
        )

        if settings.github_token:
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
                issue_number,
                self._build_develop_comment(task, previous),
            )
            self._audit(
                task.id,
                run_id,
                "github.develop_commented",
                {"issue_number": issue_number},
            )

        self.db.commit()
        return EventResult(
            task_id=task.id,
            previous_state=previous,
            current_state=task.state,
            message="Plan이 승인되어 Dev Agent 실행이 완료되었습니다."
            if previous == "Todo"
            else "Dev Agent 재실행이 완료되었습니다.",
        )

    # 최근 실패한 Dev run을 분석해 자동 복구 가능한 개발 실패를 수정한다.
    def run_fix_develop_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
    ) -> EventResult | dict[str, str]:
        task = self.db.scalar(select(Task).where(Task.github_issue_number == issue_number))
        if task is None:
            return self._skip_develop_command(
                issue_number,
                "작업을 찾을 수 없습니다. 먼저 plan과 develop을 실행하세요.",
            )

        task.title = title
        task.body = self._append_issue_metadata(body, issue_labels or [], issue_number)
        task.github_issue_url = issue_url

        failed_dev_run = self._latest_failed_dev_run(task.id)
        if failed_dev_run is None:
            return self._skip_develop_command(
                issue_number,
                "수리할 실패한 Dev 실행 기록이 없습니다.",
                task.id,
            )

        previous = task.state
        run_id = self._run_agent(task, "fix_develop")
        if task.state != "In Progress":
            task.state = "In Progress"
            self._record_transition(
                task.id,
                previous,
                task.state,
                f"develop failure fixed by {settings.fix_develop_command}",
                "agent",
            )

        self._audit(
            task.id,
            run_id,
            "dev.failure_fixed",
            {"issue_number": issue_number, "failed_run_id": failed_dev_run.id},
        )

        if settings.github_token:
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
                issue_number,
                self._build_fix_develop_comment(task, previous, failed_dev_run.id),
            )
            self._audit(
                task.id,
                run_id,
                "github.fix_develop_commented",
                {"issue_number": issue_number},
            )

        self.db.commit()
        return EventResult(
            task_id=task.id,
            previous_state=previous,
            current_state=task.state,
            message="최근 Dev 실패를 수정했고 QA 실행 가능한 상태로 전환했습니다.",
        )

    def run_refactor_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        refactor_request: str,
        issue_labels: list[str] | None = None,
    ) -> EventResult | dict[str, str]:
        task = self.db.scalar(select(Task).where(Task.github_issue_number == issue_number))
        if task is None:
            return self._skip_refactor_command(
                issue_number,
                "작업을 찾을 수 없습니다. 먼저 plan과 develop을 실행하세요.",
            )

        task.title = title
        task.body = self._append_refactor_request(
            self._append_issue_metadata(body, issue_labels or [], issue_number),
            refactor_request,
        )
        task.github_issue_url = issue_url

        if not self.has_successful_agent_run(task.id, "dev"):
            return self._skip_refactor_command(
                issue_number,
                "성공한 Dev 실행 기록이 없습니다. 먼저 @ai-harness develop을 실행하세요.",
                task.id,
            )

        if task.state not in {"In Progress", "System QA", "Human QA"}:
            return self._skip_refactor_command(
                issue_number,
                f"현재 작업 상태는 `{task.state}`입니다. refactor는 개발이 시작된 이후에만 실행할 수 있습니다.",
                task.id,
            )

        previous = task.state
        run_id = self._run_agent(task, "dev")
        task.state = "In Progress"
        self._record_transition(
            task.id,
            previous,
            task.state,
            f"refactor requested by {settings.refactor_command}",
            "human",
        )
        self._audit(
            task.id,
            run_id,
            "dev.refactored",
            {
                "issue_number": issue_number,
                "issue_url": issue_url,
                "has_refactor_request": bool(refactor_request),
            },
        )

        if settings.github_token:
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
                issue_number,
                self._build_refactor_comment(task, previous),
            )
            self._audit(
                task.id,
                run_id,
                "github.refactor_commented",
                {"issue_number": issue_number},
            )

        self.db.commit()
        return EventResult(
            task_id=task.id,
            previous_state=previous,
            current_state=task.state,
            message="리팩터링 요청을 반영했고 작업 상태를 In Progress로 변경했습니다.",
        )

    def run_qa_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
        qa_request: str | None = None,
    ) -> EventResult | dict[str, str]:
        task = self.db.scalar(select(Task).where(Task.github_issue_number == issue_number))
        if task is None:
            return self._skip_qa_command(issue_number, "작업을 찾을 수 없습니다. 먼저 plan과 develop을 실행하세요.")

        task.title = title
        task.body = self._append_qa_request(
            self._append_issue_metadata(body, issue_labels or [], issue_number),
            qa_request,
        )
        task.github_issue_url = issue_url

        if task.state != "In Progress":
            next_command = (
                settings.reqa_command
                if task.state in {"System QA", "Human QA"}
                else settings.develop_command
            )
            return self._skip_qa_command(
                issue_number,
                f"현재 작업 상태는 `{task.state}`입니다. QA는 `In Progress`에서만 실행할 수 있습니다.",
                task.id,
                next_command,
            )

        previous = task.state
        decision = self.state_machine.decide(task.state, WorkflowEvent.DEV_COMPLETE.value)
        run_id: str | None = None
        if decision.requires_agent:
            run_id = self._run_agent(task, decision.requires_agent)

        task.state = decision.to_state.value
        self._record_transition(
            task.id,
            previous,
            task.state,
            f"system QA requested by {settings.qa_command}",
            "system",
        )
        self._audit(
            task.id,
            run_id,
            "qa.completed",
            {"issue_number": issue_number, "issue_url": issue_url},
        )

        if settings.github_token:
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
                issue_number,
                self._build_qa_comment(task, previous),
            )
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
                issue_number,
                self._build_human_qa_comment(task, rerun=False),
            )
            self._audit(
                task.id,
                run_id,
                "github.qa_commented",
                {"issue_number": issue_number},
            )

        self._notify_after_qa(task, run_id, rerun=False)
        self.db.commit()
        return EventResult(
            task_id=task.id,
            previous_state=previous,
            current_state=task.state,
            message="QA가 통과되어 작업 상태를 System QA로 변경했습니다.",
        )

    def rerun_qa_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
        qa_request: str | None = None,
    ) -> EventResult | dict[str, str]:
        task = self.db.scalar(select(Task).where(Task.github_issue_number == issue_number))
        if task is None:
            return self._skip_qa_command(
                issue_number,
                "작업을 찾을 수 없습니다. 먼저 plan과 develop을 실행하세요.",
                next_command=settings.plan_command,
            )

        task.title = title
        task.body = self._append_qa_request(
            self._append_issue_metadata(body, issue_labels or [], issue_number),
            qa_request,
        )
        task.github_issue_url = issue_url

        if task.state != "System QA":
            next_command = settings.qa_command if task.state == "In Progress" else settings.develop_command
            return self._skip_qa_command(
                issue_number,
                f"현재 작업 상태는 `{task.state}`입니다. re-QA는 `System QA`에서만 실행할 수 있습니다.",
                task.id,
                next_command,
            )

        previous = task.state
        run_id = self._run_agent(task, "qa")
        self._record_transition(
            task.id,
            previous,
            task.state,
            f"system QA rerun requested by {settings.reqa_command}",
            "system",
        )
        self._audit(
            task.id,
            run_id,
            "qa.rerun_completed",
            {"issue_number": issue_number, "issue_url": issue_url},
        )

        if settings.github_token:
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
                issue_number,
                self._build_qa_comment(task, previous, rerun=True),
            )
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
                issue_number,
                self._build_human_qa_comment(task, rerun=True),
            )
            self._audit(
                task.id,
                run_id,
                "github.qa_rerun_commented",
                {"issue_number": issue_number},
            )

        self._notify_after_qa(task, run_id, rerun=True)
        self.db.commit()
        return EventResult(
            task_id=task.id,
            previous_state=previous,
            current_state=task.state,
            message="QA 재검증이 통과되었고 작업 상태는 System QA로 유지됩니다.",
        )

    def comment_status_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
    ) -> dict[str, str]:
        task = self.db.scalar(select(Task).where(Task.github_issue_number == issue_number))
        if task is None:
            task = self.upsert_github_issue_task(
                issue_number=issue_number,
                title=title,
                body=self._append_issue_metadata(body, issue_labels or [], issue_number),
                issue_url=issue_url,
            )
        else:
            task.title = title
            task.body = self._append_issue_metadata(body, issue_labels or [], issue_number)
            task.github_issue_url = issue_url

        if settings.github_token:
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
                issue_number,
                self._build_status_comment(task),
            )
        self._audit(task.id, None, "status.commented", {"issue_number": issue_number})
        self.db.commit()
        return {"status": "ok", "message": "상태 댓글을 생성했습니다.", "task_id": task.id}

    def cancel_github_issue_task(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
        reason: str = "cancel requested",
    ) -> dict[str, str]:
        task = self.db.scalar(select(Task).where(Task.github_issue_number == issue_number))
        if task is None:
            task = self.upsert_github_issue_task(
                issue_number=issue_number,
                title=title,
                body=self._append_issue_metadata(body, issue_labels or [], issue_number),
                issue_url=issue_url,
            )
        else:
            task.title = title
            task.body = self._append_issue_metadata(body, issue_labels or [], issue_number)
            task.github_issue_url = issue_url

        previous = task.state
        running_run = self._latest_running_run(task.id)
        task.state = "Cancelled"
        self._record_transition(task.id, previous, task.state, reason, "human")
        self._audit(
            task.id,
            running_run.id if running_run else None,
            "task.cancelled",
            {
                "issue_number": issue_number,
                "reason": reason,
                "had_running_run": bool(running_run),
            },
        )
        if settings.github_token:
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
                issue_number,
                self._build_cancel_comment(task, previous, reason, bool(running_run)),
            )
        self.db.commit()
        return {"status": "ok", "message": "작업을 중지했습니다.", "task_id": task.id}

    def comment_command_failure(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None,
        command: str | None,
        error: str,
    ) -> dict[str, str]:
        task = self.db.scalar(select(Task).where(Task.github_issue_number == issue_number))
        if task is None:
            task = self.upsert_github_issue_task(
                issue_number=issue_number,
                title=title,
                body=self._append_issue_metadata(body, issue_labels or [], issue_number),
                issue_url=issue_url,
            )
        else:
            task.title = title
            task.body = self._append_issue_metadata(body, issue_labels or [], issue_number)
            task.github_issue_url = issue_url

        latest_run = self._latest_run(task.id)
        self._audit(
            task.id,
            latest_run.id if latest_run else None,
            "command.failed",
            {"issue_number": issue_number, "command": command, "error": error},
        )
        if settings.github_token:
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
                issue_number,
                self._build_command_failure_comment(task, command, error),
            )
        self.db.commit()
        return {"status": "failed", "reason": error, "task_id": task.id}

    def handle_manual_event(self, payload: ManualEvent) -> EventResult:
        task = self.get_task(payload.task_id)
        if task is None:
            raise ValueError("작업을 찾을 수 없습니다.")

        previous = task.state
        decision = self.state_machine.decide(task.state, payload.event)

        if decision.increments_retry:
            if task.retry_count >= task.retry_limit:
                raise ValueError("재시도 한도를 초과했습니다.")
            task.retry_count += 1

        if decision.requires_human_approval:
            raise ValueError("Done 상태 전이는 Human approval endpoint를 사용해야 합니다.")

        run_id: str | None = None
        if decision.requires_agent:
            run_id = self._run_agent(task, decision.requires_agent)

        task.state = decision.to_state.value
        self._record_transition(
            task.id, previous, task.state, payload.reason or payload.event, "system"
        )
        self._audit(
            task.id,
            run_id,
            "task.transitioned",
            {"from": previous, "to": task.state, "event": payload.event},
        )
        self.db.commit()

        return EventResult(
            task_id=task.id,
            previous_state=previous,
            current_state=task.state,
            message=f"이벤트 {payload.event}로 상태가 전이되었습니다.",
        )

    def approve_human_qa(self, task_id: str, payload: HumanApproval) -> EventResult:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError("작업을 찾을 수 없습니다.")

        previous = task.state
        decision = self.state_machine.decide(task.state, WorkflowEvent.HUMAN_APPROVE.value)
        task.human_approved_at = now_kst()
        task.state = decision.to_state.value

        self._record_transition(
            task.id, previous, task.state, f"approved by {payload.approved_by}", "human"
        )
        self._audit(
            task.id,
            None,
            "human.approved",
            {"approved_by": payload.approved_by, "notes": payload.notes},
        )
        self.db.commit()

        return EventResult(
            task_id=task.id,
            previous_state=previous,
            current_state=task.state,
            message="Human QA 승인을 기록했습니다.",
        )

    def _run_agent(self, task: Task, agent_name: str) -> str:
        agent = self.agent_registry.get(agent_name)
        run = Run(
            task_id=task.id,
            agent_name=agent_name,
            status="running",
            timeout_seconds=settings.agent_timeout_seconds,
        )
        self.db.add(run)
        self.db.flush()

        logger.info(
            "agent run started",
            extra={"task_id": task.id, "run_id": run.id, "agent_name": agent_name},
        )

        try:
            result = agent.run(
                AgentInput(
                    task_id=task.id,
                    title=task.title,
                    body=task.body,
                    state=task.state,
                    artifacts_root=settings.artifact_root,
                    timeout_seconds=settings.agent_timeout_seconds,
                    retry_count=task.retry_count,
                    retry_limit=task.retry_limit,
                )
            )
            run.status = result.status.value
            run.summary = result.summary
            run.error = result.error
            run.finished_at = now_kst()
            self.artifact_store.persist_agent_artifacts(task.id, run.id, result.artifacts)
            if result.status != AgentStatus.SUCCESS:
                raise ValueError(f"Agent 실행 실패: {agent_name}: {result.error or result.summary}")
            return run.id
        except Exception as exc:
            if run.status == "running":
                run.status = AgentStatus.FAILED.value
            if not run.error:
                run.error = str(exc)
            run.finished_at = now_kst()
            if not run.summary:
                run.summary = f"{agent_name}가 완료 전에 실패했습니다."
            raise
        finally:
            logger.info(
                "agent run finished",
                extra={"task_id": task.id, "run_id": run.id, "agent_name": agent_name},
            )

    def _record_transition(
        self, task_id: str, from_state: str | None, to_state: str, reason: str, actor: str
    ) -> None:
        self.db.add(
            StateTransition(
                task_id=task_id,
                from_state=from_state,
                to_state=to_state,
                reason=reason,
                actor=actor,
            )
        )

    def _audit(
        self, task_id: str | None, run_id: str | None, event_type: str, payload: dict
    ) -> None:
        self.db.add(AuditLog(task_id=task_id, run_id=run_id, event_type=event_type, payload=payload))

    def _latest_run(self, task_id: str) -> Run | None:
        return self.db.scalar(
            select(Run).where(Run.task_id == task_id).order_by(Run.started_at.desc()).limit(1)
        )

    def _latest_running_run(self, task_id: str) -> Run | None:
        return self.db.scalar(
            select(Run)
            .where(Run.task_id == task_id)
            .where(Run.status == "running")
            .where(Run.finished_at.is_(None))
            .order_by(Run.started_at.desc())
            .limit(1)
        )

    # 가장 최근 실패한 Dev run을 찾아 fix-develop의 입력 기준으로 사용한다.
    def _latest_failed_dev_run(self, task_id: str) -> Run | None:
        return self.db.scalar(
            select(Run)
            .where(Run.task_id == task_id)
            .where(Run.agent_name == "dev")
            .where(Run.status == AgentStatus.FAILED.value)
            .order_by(Run.started_at.desc())
            .limit(1)
        )

    def _latest_transition(self, task_id: str) -> StateTransition | None:
        return self.db.scalar(
            select(StateTransition)
            .where(StateTransition.task_id == task_id)
            .order_by(StateTransition.created_at.desc())
            .limit(1)
        )

    def _format_dt(self, value: datetime | None) -> str:
        if value is None:
            return "not finished"
        if value.tzinfo is None:
            return value.strftime("%Y.%m.%d %H:%M:%S")
        return value.astimezone(KST).strftime("%Y.%m.%d %H:%M:%S")

    def _extract_section(self, markdown: str, heading: str) -> list[str]:
        lines = markdown.splitlines()
        collected: list[str] = []
        in_section = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## ") or stripped.startswith("### "):
                marker = "## " if stripped.startswith("## ") else "### "
                if in_section:
                    break
                in_section = stripped.removeprefix(marker).strip() == heading
                continue
            if in_section and stripped:
                collected.append(stripped)
        return collected

    def _extract_bullets(self, markdown: str, heading: str) -> list[str]:
        return [
            line.removeprefix("-").strip()
            for line in self._extract_section(markdown, heading)
            if line.startswith("-")
        ]

    def _comment_bullets(self, items: list[str], fallback: list[str]) -> list[str]:
        return [f"- {item}" for item in (items or fallback)]

    def _append_replan_request(self, body: str, replan_request: str) -> str:
        return "\n".join(
            [
                body,
                "",
                "## Human Replan Request",
                replan_request.strip(),
            ]
        )

    def _append_refactor_request(self, body: str, refactor_request: str) -> str:
        return "\n".join(
            [
                body,
                "",
                "## Human Refactor Request",
                refactor_request.strip(),
            ]
        )

    def _append_qa_request(self, body: str, qa_request: str | None) -> str:
        if not qa_request:
            return body
        return "\n".join(
            [
                body,
                "",
                "## Human QA Request",
                qa_request.strip(),
            ]
        )

    def _append_issue_metadata(
        self, body: str, issue_labels: list[str], issue_number: int | None = None
    ) -> str:
        if not issue_labels and issue_number is None:
            return body
        labels = ", ".join(sorted(set(issue_labels))) if issue_labels else "none"
        issue_number_value = str(issue_number) if issue_number is not None else "unknown"
        return "\n".join(
            [
                body.rstrip(),
                "",
                "## Harness Metadata",
                f"- issue_number: {issue_number_value}",
                f"- labels: {labels}",
            ]
        )

    def _next_command_for_state(self, state: str) -> str:
        return {
            "Backlog": settings.plan_command,
            "Todo": settings.develop_command,
            "In Progress": settings.qa_command,
            "System QA": settings.reqa_command,
            "Human QA": "사람이 직접 검증 후 human approval",
            "Done": "완료됨",
            "Cancelled": "중지됨. 다시 시작하려면 replan 또는 plan부터 판단",
        }.get(state, settings.status_command)

    def _build_status_comment(self, task: Task) -> str:
        latest_run = self._latest_run(task.id)
        running_run = self._latest_running_run(task.id)
        latest_transition = self._latest_transition(task.id)
        branch_name = self._branch_name_for_task(task)

        run_lines = [
            "- 아직 실행된 Agent run이 없습니다.",
        ]
        if latest_run:
            run_lines = [
                f"- agent: `{latest_run.agent_name}`",
                f"- status: `{latest_run.status}`",
                f"- started_at: `{self._format_dt(latest_run.started_at)}`",
                f"- finished_at: `{self._format_dt(latest_run.finished_at)}`",
                f"- summary: {latest_run.summary or '기록 없음'}",
            ]
            if latest_run.error:
                run_lines.append(f"- error: `{latest_run.error}`")

        transition_lines = ["- 아직 상태 전이 기록이 없습니다."]
        if latest_transition:
            transition_lines = [
                f"- from: `{latest_transition.from_state or '없음'}`",
                f"- to: `{latest_transition.to_state}`",
                f"- reason: {latest_transition.reason}",
                f"- at: `{self._format_dt(latest_transition.created_at)}`",
            ]

        running_text = (
            f"`{running_run.agent_name}` 실행 중"
            if running_run
            else "현재 실행 중인 Agent 없음"
        )
        recommended_command = (
            settings.fix_develop_command
            if latest_run and latest_run.agent_name == "dev" and latest_run.status == AgentStatus.FAILED.value
            else self._next_command_for_state(task.state)
        )

        return "\n".join(
            [
                "<!-- ai-harness-generated -->",
                "",
                f"## 📍 AI Harness Status: {task.title}",
                "",
                f"Task ID: `{task.id}`",
                "",
                "### 현재 상태",
                f"- state: `{task.state}`",
                f"- branch: `{branch_name}`",
                f"- running: {running_text}",
                f"- retry: `{task.retry_count}/{task.retry_limit}`",
                "",
                "### 마지막 Agent 실행",
                *run_lines,
                "",
                "### 마지막 상태 전이",
                *transition_lines,
                "",
                "### 다음 행동",
                f"- 권장 명령: `{recommended_command}`",
                "",
                "### 중지",
                "```markdown",
                settings.cancel_command,
                "```",
            ]
        )

    def _build_cancel_comment(
        self, task: Task, previous_state: str, reason: str, had_running_run: bool
    ) -> str:
        interrupt_note = (
            "실행 중인 Agent run이 감지되었습니다. 현재 구조에서는 이미 시작된 동기 작업을 강제 kill하지 않고, 이후 단계 진행을 중지합니다."
            if had_running_run
            else "현재 실행 중인 Agent는 없었고, 이후 단계 진행을 중지했습니다."
        )
        return "\n".join(
            [
                "<!-- ai-harness-generated -->",
                "",
                f"## 🛑 AI Harness 작업 중지: {task.title}",
                "",
                f"Task ID: `{task.id}`",
                "",
                "### 상태",
                f"- previous: `{previous_state}`",
                f"- current: `{task.state}`",
                "",
                "### 사유",
                f"- {reason}",
                "",
                "### 참고",
                f"- {interrupt_note}",
                "",
                "상태를 다시 확인하려면 아래 명령을 사용하세요.",
                "",
                "```markdown",
                settings.status_command,
                "```",
            ]
        )

    def _build_command_failure_comment(
        self, task: Task, command: str | None, error: str
    ) -> str:
        latest_run = self._latest_run(task.id)
        run_lines = ["- Agent run 기록을 찾지 못했습니다."]
        if latest_run:
            run_lines = [
                f"- agent: `{latest_run.agent_name}`",
                f"- status: `{latest_run.status}`",
                f"- started_at: `{self._format_dt(latest_run.started_at)}`",
                f"- finished_at: `{self._format_dt(latest_run.finished_at)}`",
                f"- summary: {latest_run.summary or '기록 없음'}",
            ]
            if latest_run.error:
                run_lines.append(f"- error: `{latest_run.error}`")

        artifact_lines = self._failure_artifact_open_lines(
            task,
            command,
            latest_run.agent_name if latest_run else None,
        )
        next_command = (
            settings.fix_develop_command
            if latest_run and latest_run.agent_name == "dev"
            else settings.status_command
        )
        next_heading = "### 다음 추천 명령" if next_command == settings.fix_develop_command else "### 다음 확인 명령"

        return "\n".join(
            [
                "<!-- ai-harness-generated -->",
                "",
                f"## ⚠️ AI Harness 명령 실패: {task.title}",
                "",
                f"Task ID: `{task.id}`",
                "",
                "### 명령",
                f"- `{command or '알 수 없음'}`",
                "",
                "### 실패 이유",
                f"- {error}",
                "",
                "### 현재 상태",
                f"- state: `{task.state}`",
                "",
                "### 마지막 Agent 실행",
                *run_lines,
                "",
                *artifact_lines,
                "",
                next_heading,
                "```markdown",
                next_command,
                "```",
            ]
        )

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
        elif agent_name == "plan" or command in {settings.plan_command, settings.replan_command}:
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
        if settings.github_token:
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
                issue_number,
                self._build_develop_not_ready_comment(reason, task_id),
            )
        self.db.commit()
        return {"status": "ignored", "reason": reason}

    def _skip_refactor_command(
        self, issue_number: int, reason: str, task_id: str | None = None
    ) -> dict[str, str]:
        if settings.github_token:
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
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
        if settings.github_token:
            GitHubAdapter(settings.github_token).create_issue_comment(
                settings.github_owner,
                settings.github_repo,
                issue_number,
                self._build_qa_not_ready_comment(
                    reason,
                    task_id,
                    next_command or settings.develop_command,
                ),
            )
        self.db.commit()
        return {"status": "ignored", "reason": reason}

    def _build_plan_comment(self, task: Task) -> str:
        goal = self._extract_section(task.body, "목표")
        scope = self._extract_bullets(task.body, "작업 범위")
        acceptance = self._extract_bullets(task.body, "완료 기준")
        replan_request = self._extract_section(task.body, "Human Replan Request")
        issue_type = self._extract_issue_type(task.body)
        profile = _profile_for_issue_type(issue_type)
        implementation_steps = list(profile["steps"])
        expected_files = list(profile["expected_files"])
        open_questions = list(profile["open_questions"])
        summary_fallback = [str(profile["summary_fallback"])]
        scope_fallback = list(profile["scope_fallback"])
        acceptance_fallback = list(profile["acceptance_fallback"])
        flow_title = str(profile["flow_title"])
        sequence_diagram = _sequence_diagram_for_issue_type(issue_type)
        flow_chart = _flow_chart_for_issue_type(issue_type)
        task_id = task.id

        return "\n".join(
            [
                "<!-- ai-harness-generated -->",
                "",
                f"## {self._plan_title(task)}",
                "",
                f"Task ID: `{task_id}`",
                "",
                "### 이슈 타입",
                issue_type,
                "",
                "### 구현 요약",
                *(goal or summary_fallback),
                "",
                *(
                    [
                        "### 반영된 결정/수정 요청",
                        *replan_request,
                        "",
                    ]
                    if replan_request
                    else []
                ),
                "### 변경 대상",
                *self._comment_bullets(expected_files, []),
                "",
                "### 작업 범위",
                *self._comment_bullets(
                    scope,
                    scope_fallback,
                ),
                "",
                "### 시퀀스 다이어그램",
                "```mermaid",
                *sequence_diagram,
                "```",
                "",
                f"### 플로우 차트 ({flow_title})",
                "```mermaid",
                *flow_chart,
                "```",
                "",
                "### 구현 순서",
                *[f"{index}. {step}" for index, step in enumerate(implementation_steps, start=1)],
                "",
                "### 검증 기준",
                *self._comment_bullets(
                    acceptance,
                    acceptance_fallback,
                ),
                "",
                "### 미결정 사항",
                *self._comment_bullets(open_questions, []),
                "",
                "### 상세 Artifacts",
                f"- `artifacts/{task_id}/plans/architecture.md`",
                f"- `artifacts/{task_id}/plans/sequence-diagram.md`",
                f"- `artifacts/{task_id}/plans/flow.md`",
                f"- `artifacts/{task_id}/plans/flow-chart.md`",
                f"- `artifacts/{task_id}/plans/edge-case-checklist.md`",
                "",
                "### 다음 추천 명령어",
                f"- 계획이 충분하면 `{settings.develop_command}`",
                f"- 계획을 수정하고 싶으면 `{settings.replan_command}` 아래에 수정 요청을 적어 다시 논의하세요.",
            ]
        )

    def _extract_issue_type(self, markdown: str) -> str:
        metadata = self._extract_section(markdown, "Harness Metadata")
        for line in metadata:
            if not line.startswith("- labels:"):
                continue
            labels = [item.strip() for item in line.removeprefix("- labels:").split(",")]
            for label in labels:
                if label.startswith("type: "):
                    return label.removeprefix("type: ").strip()
        return "unspecified"

    # GitHub 댓글과 알림에 표시할 이슈 타입명을 사람이 읽기 좋게 변환한다.
    def _issue_type_label(self, issue_type: str) -> str:
        return {
            "beFeature": "BE feature",
            "feFeature": "FE feature",
            "fullstackFeature": "Full Stack feature",
            "apiConnect": "API connect",
            "bugfix": "bugfix",
            "hotfix": "hotfix",
            "infra": "infra",
            "config": "config",
            "docs": "docs",
        }.get(issue_type, issue_type or "unspecified")

    def _extract_issue_number(self, markdown: str) -> str:
        metadata = self._extract_section(markdown, "Harness Metadata")
        for line in metadata:
            if line.startswith("- issue_number:"):
                return line.removeprefix("- issue_number:").strip()
        return "unknown"

    # 작업의 이슈 타입과 번호를 기준으로 표준 브랜치명을 만든다.
    def _branch_name_for_task(self, task: Task) -> str:
        issue_type = self._extract_issue_type(task.body)
        issue_number = self._extract_issue_number(task.body)
        prefix = {
            "beFeature": "feature(BE)",
            "feFeature": "feature(FE)",
            "fullstackFeature": "feature(FS)",
            "apiConnect": "api-connect",
            "bugfix": "bugfix",
            "hotfix": "hotfix",
            "infra": "infra",
            "config": "config",
            "docs": "docs",
        }.get(issue_type, "task")
        number = issue_number if issue_number and issue_number != "unknown" else "no-issue"
        return f"{prefix}-{number}"

    def _build_duplicate_plan_comment(self, task: Task) -> str:
        return "\n".join(
            [
                "<!-- ai-harness-generated -->",
                "",
                f"## 🏗️ AI Plan이 이미 존재합니다: {task.title}",
                "",
                f"Task ID: `{task.id}`",
                "",
                "이미 Plan Agent가 성공한 기록이 있습니다.",
                "",
                "기존 설계를 수정하고 싶다면 아래 명령을 새 댓글로 작성하세요.",
                "",
                "```markdown",
                f"{settings.replan_command}",
                "",
                "- 수정하고 싶은 설계 방향을 적습니다.",
                "```",
            ]
        )

    def _build_develop_comment(self, task: Task, previous_state: str = "Todo") -> str:
        branch_name = self._branch_name_for_task(task)
        latest_run = self._latest_run(task.id)
        run_status = latest_run.status if latest_run else "unknown"
        run_summary = latest_run.summary if latest_run else "Dev Agent 실행 기록을 찾지 못했습니다."
        run_error = latest_run.error if latest_run and latest_run.error else None
        return "\n".join(
            [
                "<!-- ai-harness-generated -->",
                "",
                f"## 🛠️ 개발 완료: {task.title}",
                "",
                f"Task ID: `{task.id}`",
                "",
                "사람의 명령으로 Plan이 승인되었고 Dev Agent 실행이 끝났습니다.",
                "",
                "### 상태",
                f"- previous: `{previous_state}`",
                f"- current: `{task.state}`",
                f"- dev status: `{run_status}`",
                "",
                "### 브랜치",
                f"- `{branch_name}`",
                "",
                "### 실행 결과",
                f"- {run_summary}",
                *(["", "### 실패 이유", f"- {run_error}"] if run_error else []),
                "",
                "### 커밋 규칙",
                "- 구현 단계 하나가 끝날 때마다 커밋한다.",
                "- 커밋 메시지 형식: `[구현 기능(이슈 제목)] : 내용`",
                "- 각 구현 단위에는 테스트 코드를 포함한다.",
                "",
                "### Dev 산출물",
                f"- `artifacts/{task.id}/dev/commit-plan.md`",
                f"- `artifacts/{task.id}/dev/dev-status.md`",
                f"- `artifacts/{task.id}/dev/implementation.patch`",
                f"- `artifacts/{task.id}/dev/test-report.md`",
                "",
                "### 확인 방법",
                "- 이 GitHub 댓글에서 브랜치와 artifact 경로를 확인한다.",
                "- `dev-status.md`에서 현재 단계와 체크리스트를 확인한다.",
                "- `commit-plan.md`에서 실제 커밋 해시와 커밋 단위를 확인한다.",
                "- `test-report.md`에서 자동 검증 결과를 확인한다.",
                "",
                "### 다음 단계",
                "개발 결과를 System QA로 검증하세요.",
                "",
                "```markdown",
                settings.qa_command,
                "```",
            ]
        )

    # fix-develop 결과와 다음 QA 명령을 GitHub 댓글로 요약한다.
    def _build_fix_develop_comment(
        self, task: Task, previous_state: str, failed_run_id: str
    ) -> str:
        branch_name = self._branch_name_for_task(task)
        latest_run = self._latest_run(task.id)
        run_summary = latest_run.summary if latest_run else "Fix Develop Agent 실행 기록을 찾지 못했습니다."
        run_error = latest_run.error if latest_run and latest_run.error else None
        return "\n".join(
            [
                "<!-- ai-harness-generated -->",
                "",
                f"## 🛠️ Dev 실패 수정 완료: {task.title}",
                "",
                f"Task ID: `{task.id}`",
                "",
                "최근 실패한 Dev 실행을 분석했고 자동 수리 가능한 문제를 수정했습니다.",
                "",
                "### 상태",
                f"- previous: `{previous_state}`",
                f"- current: `{task.state}`",
                f"- failed_dev_run: `{failed_run_id}`",
                "",
                "### 브랜치",
                f"- `{branch_name}`",
                "",
                "### 실행 결과",
                f"- {run_summary}",
                *(["", "### 남은 문제", f"- {run_error}"] if run_error else []),
                "",
                "### Fix 산출물",
                f"- `artifacts/{task.id}/dev/fix-develop-report.md`",
                f"- `artifacts/{task.id}/dev/test-report.md`",
                f"- `artifacts/{task.id}/dev/dev-status.md`",
                "",
                "### 다음 단계",
                "수정된 개발 결과를 System QA로 검증하세요.",
                "",
                "```markdown",
                settings.qa_command,
                "```",
            ]
        )

    def _build_refactor_comment(self, task: Task, previous_state: str) -> str:
        branch_name = self._branch_name_for_task(task)
        refactor_request = self._extract_section(task.body, "Human Refactor Request")
        return "\n".join(
            [
                "<!-- ai-harness-generated -->",
                "",
                f"## 🛠️ 리팩터링 완료: {task.title}",
                "",
                f"Task ID: `{task.id}`",
                "",
                "사람이 요청한 리팩터링 내용을 Dev Agent가 반영했습니다.",
                "",
                "### 상태",
                f"- previous: `{previous_state}`",
                f"- current: `{task.state}`",
                "",
                "### 브랜치",
                f"- `{branch_name}`",
                "",
                "### 반영 요청",
                *(self._comment_bullets(refactor_request, ["추가 상세 내용 없이 리팩터링이 요청되었습니다."])),
                "",
                "### Dev 산출물",
                f"- `artifacts/{task.id}/dev/commit-plan.md`",
                f"- `artifacts/{task.id}/dev/dev-status.md`",
                f"- `artifacts/{task.id}/dev/backend-style-checklist.md`",
                f"- `artifacts/{task.id}/dev/implementation.patch`",
                f"- `artifacts/{task.id}/dev/test-report.md`",
                "",
                "### 다음 단계",
                "리팩터링으로 코드가 변경되었으므로 System QA를 다시 실행하세요.",
                "",
                "```markdown",
                settings.qa_command,
                "```",
            ]
        )

    def _build_develop_not_ready_comment(self, reason: str, task_id: str | None) -> str:
        lines = [
            "<!-- ai-harness-generated -->",
            "",
            "## 🛠️ 개발을 시작하지 못했습니다",
            "",
        ]
        if task_id:
            lines.extend([f"Task ID: `{task_id}`", ""])
        lines.extend(
            [
                "아직 개발을 시작할 수 없습니다.",
                "",
                "### 사유",
                f"- {reason}",
                "",
                "### 다음 명령",
                "```markdown",
                settings.plan_command,
                "```",
            ]
        )
        return "\n".join(lines)

    def _build_refactor_not_ready_comment(self, reason: str, task_id: str | None) -> str:
        lines = [
            "<!-- ai-harness-generated -->",
            "",
            "## 🛠️ 리팩터링을 시작하지 못했습니다",
            "",
        ]
        if task_id:
            lines.extend([f"Task ID: `{task_id}`", ""])
        lines.extend(
            [
                "아직 리팩터링을 시작할 수 없습니다.",
                "",
                "### 사유",
                f"- {reason}",
                "",
                "### 다음 명령",
                "```markdown",
                settings.develop_command,
                "```",
            ]
        )
        return "\n".join(lines)

    def _build_qa_comment(self, task: Task, previous_state: str, rerun: bool = False) -> str:
        qa_summary = self._build_qa_summary_lines(task.id)
        title = "♻️ 🔎 System QA 재검증 통과" if rerun else "🔎 System QA 통과"
        return "\n".join(
            [
                "<!-- ai-harness-generated -->",
                "",
                f"## {title}: {task.title}",
                "",
                f"Task ID: `{task.id}`",
                "",
                "### 상태",
                f"- previous: `{previous_state}`",
                f"- current: `{task.state}`",
                "",
                *qa_summary,
                "",
                "### QA 산출물",
                f"- `artifacts/{task.id}/qa/qa-report.md`",
                f"- `artifacts/{task.id}/qa/qa-checklist.md`",
                "",
                "### 다음 단계",
                "- 바로 다음 Human QA 요청 댓글의 체크리스트를 기준으로 사람이 직접 검증하세요.",
            ]
        )

    def _build_qa_summary_lines(self, task_id: str) -> list[str]:
        report_path = settings.artifact_root / task_id / "qa" / "qa-report.md"
        if not report_path.exists():
            return [
                "### QA 결과",
                "- QA report 파일을 찾지 못했습니다. 아래 artifact 경로를 확인하세요.",
            ]

        report_lines = report_path.read_text(encoding="utf-8").splitlines()
        metadata: dict[str, str] = {}
        checklist: list[str] = []
        api_smoke_lines: list[str] = []
        command = "기록 없음"
        output = "기록 없음"
        in_stdout = False
        in_checklist = False
        in_api_smoke = False

        for line in report_lines:
            stripped = line.strip()
            if stripped == "## API Smoke Test 결과":
                in_api_smoke = True
                in_checklist = False
                continue
            if in_api_smoke and stripped.startswith("## "):
                in_api_smoke = False
            if in_api_smoke:
                api_smoke_lines.append(line)
                continue
            if stripped == "## 검증 체크리스트":
                in_checklist = True
                continue
            if stripped.startswith("## Command:"):
                command = stripped.removeprefix("## Command:").strip()
                in_checklist = False
                continue
            if in_checklist and stripped.startswith("## "):
                in_checklist = False
                continue
            if in_checklist and stripped.startswith("- ["):
                checklist.append(stripped)
                continue
            if stripped.startswith("- ") and ": `" in stripped and stripped.endswith("`"):
                key, value = stripped.removeprefix("- ").split(": `", 1)
                metadata[key] = value.removesuffix("`")
                continue
            if stripped.startswith("- ") and ": " in stripped:
                key, value = stripped.removeprefix("- ").split(": ", 1)
                metadata[key] = value
                continue
            if stripped == "### stdout":
                in_stdout = True
                continue
            if stripped.startswith("### ") and stripped != "### stdout":
                in_stdout = False
                continue
            if in_stdout and stripped and stripped != "```text" and stripped != "```":
                output = stripped

        summary = [
            "### QA 결과",
            f"- result: `{metadata.get('result', '알 수 없음')}`",
            f"- branch: `{metadata.get('branch', '알 수 없음')}`",
            f"- command: `{command}`",
            f"- output: `{output}`",
            "",
            "### 검증 항목",
        ]
        summary.extend(checklist[:20] or ["- 기록된 체크리스트 항목이 없습니다."])
        if len(checklist) > 20:
            summary.append(f"- `qa-report.md`에 추가 검증 항목 {len(checklist) - 20}개가 더 있습니다.")
        if api_smoke_lines:
            summary.extend(["", "### API Smoke Test 결과", *api_smoke_lines])
        return summary

    def _build_human_qa_lines(self, task_id: str) -> list[str]:
        report_path = settings.artifact_root / task_id / "qa" / "qa-report.md"
        if not report_path.exists():
            return [
                "### Human QA 권장 체크",
                "- QA report 파일을 찾지 못했습니다. 아래 artifact 경로를 확인하세요.",
            ]

        report_lines = report_path.read_text(encoding="utf-8").splitlines()
        checklist: list[str] = []
        in_section = False
        for line in report_lines:
            stripped = line.strip()
            if stripped == "## Human QA 체크리스트":
                in_section = True
                continue
            if in_section and stripped.startswith("## "):
                break
            if in_section and stripped.startswith("- ["):
                checklist.append(stripped)

        return [
            "### Human QA 권장 체크",
            *(checklist[:10] or ["- 사람이 화면과 동작을 직접 확인하세요."]),
        ]

    def _extract_human_qa_items(self, task_id: str) -> list[str]:
        lines = self._build_human_qa_lines(task_id)
        items: list[str] = []
        for line in lines:
            if line.startswith("- [ ] "):
                items.append(line.removeprefix("- [ ] "))
        return items

    def _plan_title(self, task: Task) -> str:
        if self._extract_section(task.body, "Human Replan Request"):
            return f"♻️ 🏗️ AI Re-Plan: {task.title}"
        return f"🏗️ AI Plan: {task.title}"

    def _qa_requested_at(self) -> str:
        return now_kst().strftime("%Y.%m.%d %H:%M:%S")

    def _build_human_qa_comment(self, task: Task, rerun: bool) -> str:
        return "\n".join(
            [
                "<!-- ai-harness-generated -->",
                "",
                self._build_human_qa_message(task, rerun, github_comment=True),
            ]
        )

    # Human QA 담당자가 확인할 수 있는 댓글과 외부 알림 메시지를 만든다.
    def _build_human_qa_message(self, task: Task, rerun: bool, github_comment: bool) -> str:
        title_prefix = "♻️ 🧑‍💻 Human QA Re-QA 요청" if rerun else "🧑‍💻 Human QA 요청"
        title = f"{title_prefix}: {task.title}"
        title_line = f"## {title}" if github_comment else title
        issue_type = self._extract_issue_type(task.body)
        branch_name = self._branch_name_for_task(task)
        human_qa_items = self._extract_human_qa_items(task.id)
        numbered_items = [
            f"{index}. {item}" for index, item in enumerate(human_qa_items[:7], start=1)
        ]
        check_target_lines = (
            [
                "화면 확인 URL:",
                "http://localhost:3000/signup",
                "",
                "Swagger 주소:",
                settings.studyhub_swagger_url,
                "",
                "API 확인 URL:",
                settings.studyhub_api_base_url,
            ]
            if issue_type in {"beFeature", "apiConnect", "fullstackFeature"}
            else [
                "화면 확인 URL:",
                "http://localhost:3000/signup",
            ]
        )
        return "\n".join(
            [
                title_line,
                "",
                f"* 작업 내용: {task.title}",
                f"* 작업 타입: {self._issue_type_label(issue_type)}",
                f"* 브랜치 명: {branch_name}",
                f"* QA 요청 시각: {self._qa_requested_at()}",
                "",
                "System QA는 통과했습니다.",
                "이제 아래 항목을 직접 확인해주세요.",
                "",
                *(numbered_items or ["1. 화면과 주요 동작을 직접 확인해주세요."]),
                "",
                *check_target_lines,
                "",
                "GitHub Issue:",
                task.github_issue_url or "",
            ]
        )

    def _build_qa_notification_message(self, task: Task, rerun: bool) -> str:
        return self._build_human_qa_message(task, rerun, github_comment=False)

    def _notify_after_qa(self, task: Task, run_id: str | None, rerun: bool) -> None:
        if not settings.allow_external_notifications:
            self._audit(
                task.id,
                run_id,
                "external_notifications.skipped",
                {"reason": "ALLOW_EXTERNAL_NOTIFICATIONS가 false입니다.", "rerun": rerun},
            )
            return

        message = self._build_qa_notification_message(task, rerun)
        self._notify_google_chat_after_qa(task, run_id, rerun, message)
        self._notify_discord_after_qa(task, run_id, rerun, message)

    def _notify_google_chat_after_qa(
        self, task: Task, run_id: str | None, rerun: bool, message: str
    ) -> None:
        notifier = GoogleChatNotifier(settings.google_chat_webhook_url)
        if not notifier.is_configured():
            self._audit(
                task.id,
                run_id,
                "google_chat.qa_notification_skipped",
                {"reason": "GOOGLE_CHAT_WEBHOOK_URL이 설정되어 있지 않습니다."},
            )
            return

        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001 - notification failure must not fail QA
            logger.warning(
                "Google Chat QA 알림 전송 실패",
                extra={"task_id": task.id, "run_id": run_id, "error": str(exc)},
            )
            self._audit(
                task.id,
                run_id,
                "google_chat.qa_notification_failed",
                {"error": str(exc)},
            )
            return

        self._audit(
            task.id,
            run_id,
            "google_chat.qa_notified",
            {"rerun": rerun},
        )

    def _notify_discord_after_qa(
        self, task: Task, run_id: str | None, rerun: bool, message: str
    ) -> None:
        notifier = DiscordNotifier(settings.discord_webhook_url)
        if not notifier.is_configured():
            self._audit(
                task.id,
                run_id,
                "discord.qa_notification_skipped",
                {"reason": "DISCORD_WEBHOOK_URL이 설정되어 있지 않습니다."},
            )
            return

        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001 - notification failure must not fail QA
            logger.warning(
                "Discord QA 알림 전송 실패",
                extra={"task_id": task.id, "run_id": run_id, "error": str(exc)},
            )
            self._audit(
                task.id,
                run_id,
                "discord.qa_notification_failed",
                {"error": str(exc)},
            )
            return

        self._audit(
            task.id,
            run_id,
            "discord.qa_notified",
            {"rerun": rerun},
        )

    def _build_qa_not_ready_comment(
        self, reason: str, task_id: str | None, next_command: str
    ) -> str:
        lines = [
            "<!-- ai-harness-generated -->",
            "",
            "## 🔎 System QA를 시작하지 못했습니다",
            "",
        ]
        if task_id:
            lines.extend([f"Task ID: `{task_id}`", ""])
        lines.extend(
            [
                "아직 QA를 실행할 수 없습니다.",
                "",
                "### 사유",
                f"- {reason}",
                "",
                "### 다음 명령",
                "```markdown",
                next_command,
                "```",
            ]
        )
        return "\n".join(lines)
