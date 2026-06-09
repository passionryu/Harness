from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from agents.base import AgentInput, AgentStatus
from orchestrator.core.settings import settings
from orchestrator.db.models import AuditLog, Run, StateTransition, Task

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST)


class AgentRunMixin:
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
