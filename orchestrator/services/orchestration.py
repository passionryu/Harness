import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.base import AgentInput, AgentStatus
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
                message="plan already completed; skipped duplicate trigger",
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
                {"reason": "GITHUB_TOKEN is not configured", "issue_number": issue_number},
            )

        self.db.commit()
        return EventResult(
            task_id=task.id,
            previous_state=previous,
            current_state=task.state,
            message="plan generated from GitHub issue trigger",
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
                "plan not found; run @ai-harness plan first",
            )

        task.title = title
        task.body = self._append_issue_metadata(body, issue_labels or [], issue_number)
        task.github_issue_url = issue_url

        if not self.has_successful_agent_run(task.id, "plan"):
            return self._skip_develop_command(
                issue_number,
                "successful plan not found; run @ai-harness plan first",
                task.id,
            )

        if task.state not in {"Todo", "In Progress"}:
            return self._skip_develop_command(
                issue_number,
                f"task is already in `{task.state}`; develop can run only from `Todo` or `In Progress`",
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

        self._notify_after_qa(task, run_id, rerun=False)
        self.db.commit()
        return EventResult(
            task_id=task.id,
            previous_state=previous,
            current_state=task.state,
            message="plan approved; dev agent started"
            if previous == "Todo"
            else "dev agent continued",
        )

    def run_qa_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
    ) -> EventResult | dict[str, str]:
        task = self.db.scalar(select(Task).where(Task.github_issue_number == issue_number))
        if task is None:
            return self._skip_qa_command(issue_number, "task not found; run plan and develop first")

        task.title = title
        task.body = self._append_issue_metadata(body, issue_labels or [], issue_number)
        task.github_issue_url = issue_url

        if task.state != "In Progress":
            next_command = (
                settings.reqa_command
                if task.state in {"System QA", "Human QA"}
                else settings.develop_command
            )
            return self._skip_qa_command(
                issue_number,
                f"task is in `{task.state}`; QA can run only from `In Progress`",
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

        self.db.commit()
        return EventResult(
            task_id=task.id,
            previous_state=previous,
            current_state=task.state,
            message="qa passed; task moved to System QA",
        )

    def rerun_qa_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
    ) -> EventResult | dict[str, str]:
        task = self.db.scalar(select(Task).where(Task.github_issue_number == issue_number))
        if task is None:
            return self._skip_qa_command(
                issue_number,
                "task not found; run plan and develop first",
                next_command=settings.plan_command,
            )

        task.title = title
        task.body = self._append_issue_metadata(body, issue_labels or [], issue_number)
        task.github_issue_url = issue_url

        if task.state != "System QA":
            next_command = settings.qa_command if task.state == "In Progress" else settings.develop_command
            return self._skip_qa_command(
                issue_number,
                f"task is in `{task.state}`; re-QA can run only from `System QA`",
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
            message="qa rerun passed; task remains in System QA",
        )

    def handle_manual_event(self, payload: ManualEvent) -> EventResult:
        task = self.get_task(payload.task_id)
        if task is None:
            raise ValueError("task not found")

        previous = task.state
        decision = self.state_machine.decide(task.state, payload.event)

        if decision.increments_retry:
            if task.retry_count >= task.retry_limit:
                raise ValueError("retry limit exceeded")
            task.retry_count += 1

        if decision.requires_human_approval:
            raise ValueError("use human approval endpoint for Done transition")

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
            message=f"transitioned by event {payload.event}",
        )

    def approve_human_qa(self, task_id: str, payload: HumanApproval) -> EventResult:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError("task not found")

        previous = task.state
        decision = self.state_machine.decide(task.state, WorkflowEvent.HUMAN_APPROVE.value)
        task.human_approved_at = datetime.now(UTC)
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
            message="human approval recorded",
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
            run.finished_at = datetime.now(UTC)
            self.artifact_store.persist_agent_artifacts(task.id, run.id, result.artifacts)
            if result.status != AgentStatus.SUCCESS:
                raise ValueError(f"agent failed: {agent_name}: {result.error or result.summary}")
            return run.id
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
        implementation_steps = [
            "현재 메인/로그인 진입 화면에서 회원가입 진입 지점을 확인한다.",
            "Next.js App Router 기준으로 `/signup` route를 추가한다.",
            "이름, 이메일, 비밀번호, 전화번호, 관심 영역 입력 폼을 만든다.",
            "submit handler는 실제 API 호출 전까지 TODO 또는 mock-safe 구조로 둔다.",
            "기존 디자인 시스템과 반응형 레이아웃을 유지하며 빌드 검증을 수행한다.",
        ]
        expected_files = [
            "`apps/web/app/page.tsx` 또는 현재 진입 화면",
            "`apps/web/app/signup/page.tsx`",
            "`apps/web/components` 하위 회원가입 폼 컴포넌트",
        ]
        open_questions = [
            "실제 회원가입 API endpoint와 request/response contract",
            "비밀번호 정책과 유효성 메시지",
            "전화번호 인증 여부",
            "관심 영역 option 목록과 복수 선택 허용 여부",
        ]
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
                *(goal or ["StudyHub에 회원가입 진입 흐름과 회원가입 화면을 추가한다."]),
                "",
                *(
                    [
                        "### 반영된 수정 요청",
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
                    ["회원가입 진입 링크, `/signup` 페이지, 폼 UI를 추가한다."],
                ),
                "",
                "### 화면 흐름",
                "```text",
                "현재 진입 화면",
                "-> 회원가입 버튼/링크 클릭",
                "-> /signup",
                "-> 회원가입 폼 입력",
                "-> submit handler scaffold",
                "-> 추후 백엔드 API 연동",
                "```",
                "",
                "### 구현 순서",
                *[f"{index}. {step}" for index, step in enumerate(implementation_steps, start=1)],
                "",
                "### 검증 기준",
                *self._comment_bullets(
                    acceptance,
                    ["회원가입 화면 이동 가능", "폼 표시", "프론트엔드 빌드 통과"],
                ),
                "",
                "### 미결정 사항",
                *self._comment_bullets(open_questions, []),
                "",
                "### 상세 Artifacts",
                f"- `artifacts/{task_id}/plans/architecture.md`",
                f"- `artifacts/{task_id}/plans/flow.md`",
                f"- `artifacts/{task_id}/plans/edge-case-checklist.md`",
                "",
                "사람이 위 미결정 사항을 확인한 뒤 구현 단계로 이동하세요.",
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

    def _issue_type_label(self, issue_type: str) -> str:
        return {
            "beFeature": "BE feature",
            "feFeature": "FE feature",
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

    def _branch_name_for_task(self, task: Task) -> str:
        issue_type = self._extract_issue_type(task.body)
        issue_number = self._extract_issue_number(task.body)
        prefix = {
            "beFeature": "feature(BE)",
            "feFeature": "feature(FE)",
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
                f"## 🏗️ AI Plan already exists: {task.title}",
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
        return "\n".join(
            [
                "<!-- ai-harness-generated -->",
                "",
                f"## 🛠️ Development Started: {task.title}",
                "",
                f"Task ID: `{task.id}`",
                "",
                "Plan has been approved by human command.",
                "",
                "### State",
                f"- previous: `{previous_state}`",
                f"- current: `{task.state}`",
                "",
                "### Branch",
                f"- `{branch_name}`",
                "",
                "### Commit Rule",
                "- 구현 단계 하나가 끝날 때마다 커밋한다.",
                "- 커밋 메시지 형식: `[구현 기능(이슈 제목)] : 내용`",
                "- 각 구현 단위에는 테스트 코드를 포함한다.",
                "",
                "### Dev Artifacts",
                f"- `artifacts/{task.id}/dev/commit-plan.md`",
                f"- `artifacts/{task.id}/dev/dev-status.md`",
                f"- `artifacts/{task.id}/dev/implementation.patch`",
                f"- `artifacts/{task.id}/dev/test-report.md`",
                "",
                "### How to Track",
                "- 이 GitHub 댓글에서 브랜치와 artifact 경로를 확인한다.",
                "- `dev-status.md`에서 현재 단계와 체크리스트를 확인한다.",
                "- `commit-plan.md`에서 실제 커밋 해시와 커밋 단위를 확인한다.",
                "- `test-report.md`에서 자동 검증 결과를 확인한다.",
                "",
                "현재 Dev Agent는 지원되는 작업 타입부터 실제 구현, 단계별 커밋, smoke test를 수행합니다.",
            ]
        )

    def _build_develop_not_ready_comment(self, reason: str, task_id: str | None) -> str:
        lines = [
            "<!-- ai-harness-generated -->",
            "",
            "## 🛠️ Development Not Started",
            "",
        ]
        if task_id:
            lines.extend([f"Task ID: `{task_id}`", ""])
        lines.extend(
            [
                "Cannot start development yet.",
                "",
                "### Reason",
                f"- {reason}",
                "",
                "### Next Command",
                "```markdown",
                settings.plan_command,
                "```",
            ]
        )
        return "\n".join(lines)

    def _build_qa_comment(self, task: Task, previous_state: str, rerun: bool = False) -> str:
        qa_summary = self._build_qa_summary_lines(task.id)
        title = "♻️ 🔎 System QA Re-QA Passed" if rerun else "🔎 System QA Passed"
        return "\n".join(
            [
                "<!-- ai-harness-generated -->",
                "",
                f"## {title}: {task.title}",
                "",
                f"Task ID: `{task.id}`",
                "",
                "### State",
                f"- previous: `{previous_state}`",
                f"- current: `{task.state}`",
                "",
                *qa_summary,
                "",
                "### QA Artifacts",
                f"- `artifacts/{task.id}/qa/qa-report.md`",
                f"- `artifacts/{task.id}/qa/qa-checklist.md`",
                "",
                "### Next Step",
                "- 바로 다음 Human QA 요청 댓글의 체크리스트를 기준으로 사람이 직접 검증하세요.",
            ]
        )

    def _build_qa_summary_lines(self, task_id: str) -> list[str]:
        report_path = settings.artifact_root / task_id / "qa" / "qa-report.md"
        if not report_path.exists():
            return [
                "### QA 결과",
                "- QA report file was not found. Check the artifact path below.",
            ]

        report_lines = report_path.read_text(encoding="utf-8").splitlines()
        metadata: dict[str, str] = {}
        checklist: list[str] = []
        command = "not recorded"
        output = "not recorded"
        in_stdout = False
        in_checklist = False

        for line in report_lines:
            stripped = line.strip()
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
            f"- result: `{metadata.get('result', 'unknown')}`",
            f"- branch: `{metadata.get('branch', 'unknown')}`",
            f"- command: `{command}`",
            f"- output: `{output}`",
            "",
            "### 검증 항목",
        ]
        summary.extend(checklist[:20] or ["- No checklist entries were recorded."])
        if len(checklist) > 20:
            summary.append(f"- ...and {len(checklist) - 20} more checks in `qa-report.md`")
        return summary

    def _build_human_qa_lines(self, task_id: str) -> list[str]:
        report_path = settings.artifact_root / task_id / "qa" / "qa-report.md"
        if not report_path.exists():
            return [
                "### Human QA 권장 체크",
                "- QA report file was not found. Check the artifact path below.",
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
        return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d %H:%M:%S")

    def _build_human_qa_comment(self, task: Task, rerun: bool) -> str:
        return "\n".join(
            [
                "<!-- ai-harness-generated -->",
                "",
                self._build_human_qa_message(task, rerun, github_comment=True),
            ]
        )

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
                "이제 화면에서 아래 항목을 직접 확인해주세요.",
                "",
                *(numbered_items or ["1. 화면과 주요 동작을 직접 확인해주세요."]),
                "",
                "확인 URL:",
                "http://localhost:3000/signup",
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
                {"reason": "ALLOW_EXTERNAL_NOTIFICATIONS is false", "rerun": rerun},
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
                {"reason": "GOOGLE_CHAT_WEBHOOK_URL is not configured"},
            )
            return

        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001 - notification failure must not fail QA
            logger.warning(
                "google chat QA notification failed",
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
                {"reason": "DISCORD_WEBHOOK_URL is not configured"},
            )
            return

        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001 - notification failure must not fail QA
            logger.warning(
                "discord QA notification failed",
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
            "## 🔎 System QA Not Started",
            "",
        ]
        if task_id:
            lines.extend([f"Task ID: `{task_id}`", ""])
        lines.extend(
            [
                "Cannot run QA yet.",
                "",
                "### Reason",
                f"- {reason}",
                "",
                "### Next Command",
                "```markdown",
                next_command,
                "```",
            ]
        )
        return "\n".join(lines)
