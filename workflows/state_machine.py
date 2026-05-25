from dataclasses import dataclass
from enum import StrEnum


class KanbanState(StrEnum):
    BACKLOG = "Backlog"
    TODO = "Todo"
    IN_PROGRESS = "In Progress"
    SYSTEM_QA = "System QA"
    HUMAN_QA = "Human QA"
    DONE = "Done"


class WorkflowEvent(StrEnum):
    TRIAGE = "triage"
    START_DEV = "start_dev"
    DEV_COMPLETE = "dev_complete"
    QA_PASS = "qa_pass"
    QA_FAIL = "qa_fail"
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
            KanbanState.BACKLOG, KanbanState.TODO, requires_agent="plan"
        ),
        (KanbanState.TODO, WorkflowEvent.START_DEV): TransitionDecision(
            KanbanState.TODO, KanbanState.IN_PROGRESS, requires_agent="dev"
        ),
        (KanbanState.IN_PROGRESS, WorkflowEvent.DEV_COMPLETE): TransitionDecision(
            KanbanState.IN_PROGRESS, KanbanState.SYSTEM_QA, requires_agent="qa"
        ),
        (KanbanState.SYSTEM_QA, WorkflowEvent.QA_FAIL): TransitionDecision(
            KanbanState.SYSTEM_QA,
            KanbanState.IN_PROGRESS,
            requires_agent="dev",
            increments_retry=True,
        ),
        (KanbanState.SYSTEM_QA, WorkflowEvent.QA_PASS): TransitionDecision(
            KanbanState.SYSTEM_QA, KanbanState.HUMAN_QA
        ),
        (KanbanState.HUMAN_QA, WorkflowEvent.HUMAN_REJECT): TransitionDecision(
            KanbanState.HUMAN_QA,
            KanbanState.IN_PROGRESS,
            requires_agent="dev",
            increments_retry=True,
        ),
        (KanbanState.HUMAN_QA, WorkflowEvent.HUMAN_APPROVE): TransitionDecision(
            KanbanState.HUMAN_QA,
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

