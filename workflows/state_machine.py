from dataclasses import dataclass
from enum import StrEnum


class KanbanState(StrEnum):
    BACKLOG = "Backlog"
    PLAN_REVIEW = "Plan Review"
    DEV_READY = "Dev Ready"
    DEV_REVIEW = "Dev Review"
    QA_READY = "QA Ready"
    QA_REVIEW = "QA Review"
    READY_TO_DEPLOY = "Ready To Deploy"
    DONE = "Done"
    CANCELLED = "Cancelled"


class WorkflowEvent(StrEnum):
    TRIAGE = "triage"
    PLAN_COMPLETE = "plan_complete"
    APPROVE_PLAN = "approve_plan"
    START_DEV = "start_dev"
    DEV_COMPLETE = "dev_complete"
    APPROVE_DEV = "approve_dev"
    START_QA = "start_qa"
    QA_COMPLETE = "qa_complete"
    QA_PASS = "qa_pass"
    QA_FAIL = "qa_fail"
    APPROVE_QA = "approve_qa"
    APPROVE_DEPLOY = "approve_deploy"
    HUMAN_REJECT = "human_reject"
    HUMAN_APPROVE = "human_approve"


@dataclass(frozen=True)
class TransitionDecision:
    from_state: KanbanState
    to_state: KanbanState
    requires_agent: str | None = None
    requires_human_approval: bool = False
    increments_retry: bool = False


class StateMachine:
    _transitions: dict[tuple[KanbanState, WorkflowEvent], TransitionDecision] = {
        (KanbanState.BACKLOG, WorkflowEvent.TRIAGE): TransitionDecision(
            KanbanState.BACKLOG, KanbanState.PLAN_REVIEW, requires_agent="plan"
        ),
        (KanbanState.BACKLOG, WorkflowEvent.PLAN_COMPLETE): TransitionDecision(
            KanbanState.BACKLOG, KanbanState.PLAN_REVIEW
        ),
        (KanbanState.PLAN_REVIEW, WorkflowEvent.PLAN_COMPLETE): TransitionDecision(
            KanbanState.PLAN_REVIEW, KanbanState.PLAN_REVIEW
        ),
        (KanbanState.PLAN_REVIEW, WorkflowEvent.APPROVE_PLAN): TransitionDecision(
            KanbanState.PLAN_REVIEW,
            KanbanState.DEV_READY,
            requires_human_approval=True,
        ),
        (KanbanState.DEV_READY, WorkflowEvent.START_DEV): TransitionDecision(
            KanbanState.DEV_READY, KanbanState.DEV_REVIEW, requires_agent="dev"
        ),
        (KanbanState.DEV_REVIEW, WorkflowEvent.DEV_COMPLETE): TransitionDecision(
            KanbanState.DEV_REVIEW, KanbanState.DEV_REVIEW
        ),
        (KanbanState.DEV_REVIEW, WorkflowEvent.APPROVE_DEV): TransitionDecision(
            KanbanState.DEV_REVIEW,
            KanbanState.QA_READY,
            requires_human_approval=True,
        ),
        (KanbanState.QA_READY, WorkflowEvent.START_QA): TransitionDecision(
            KanbanState.QA_READY, KanbanState.QA_REVIEW, requires_agent="qa"
        ),
        (KanbanState.QA_READY, WorkflowEvent.QA_COMPLETE): TransitionDecision(
            KanbanState.QA_READY, KanbanState.QA_REVIEW, requires_agent="qa"
        ),
        (KanbanState.QA_REVIEW, WorkflowEvent.QA_COMPLETE): TransitionDecision(
            KanbanState.QA_REVIEW, KanbanState.QA_REVIEW, requires_agent="qa"
        ),
        (KanbanState.QA_REVIEW, WorkflowEvent.QA_FAIL): TransitionDecision(
            KanbanState.QA_REVIEW,
            KanbanState.DEV_READY,
            requires_agent="dev",
            increments_retry=True,
        ),
        (KanbanState.QA_REVIEW, WorkflowEvent.QA_PASS): TransitionDecision(
            KanbanState.QA_REVIEW, KanbanState.QA_REVIEW
        ),
        (KanbanState.QA_REVIEW, WorkflowEvent.APPROVE_QA): TransitionDecision(
            KanbanState.QA_REVIEW,
            KanbanState.READY_TO_DEPLOY,
            requires_human_approval=True,
        ),
        (KanbanState.DEV_REVIEW, WorkflowEvent.HUMAN_REJECT): TransitionDecision(
            KanbanState.DEV_REVIEW,
            KanbanState.DEV_READY,
            requires_agent="dev",
            increments_retry=True,
        ),
        (KanbanState.QA_REVIEW, WorkflowEvent.HUMAN_REJECT): TransitionDecision(
            KanbanState.QA_REVIEW,
            KanbanState.DEV_READY,
            requires_agent="dev",
            increments_retry=True,
        ),
        (KanbanState.READY_TO_DEPLOY, WorkflowEvent.APPROVE_DEPLOY): TransitionDecision(
            KanbanState.READY_TO_DEPLOY,
            KanbanState.DONE,
            requires_human_approval=True,
        ),
        (KanbanState.READY_TO_DEPLOY, WorkflowEvent.HUMAN_APPROVE): TransitionDecision(
            KanbanState.READY_TO_DEPLOY,
            KanbanState.DONE,
            requires_human_approval=True,
        ),
    }

    def decide(self, current_state: str, event: str) -> TransitionDecision:
        try:
            state = KanbanState(current_state)
            workflow_event = WorkflowEvent(event)
        except ValueError as exc:
            raise ValueError(f"unknown state or event: state={current_state}, event={event}") from exc

        decision = self._transitions.get((state, workflow_event))
        if decision is None:
            raise ValueError(f"invalid transition: {state.value} + {workflow_event.value}")
        return decision
