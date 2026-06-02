import pytest

from workflows.state_machine import KanbanState, StateMachine, WorkflowEvent


def test_happy_path_transitions():
    machine = StateMachine()

    decision = machine.decide(KanbanState.BACKLOG.value, WorkflowEvent.TRIAGE.value)
    assert decision.to_state == KanbanState.PLAN_REVIEW
    assert decision.requires_agent == "plan"

    decision = machine.decide(KanbanState.PLAN_REVIEW.value, WorkflowEvent.APPROVE_PLAN.value)
    assert decision.to_state == KanbanState.DEV_READY
    assert decision.requires_human_approval is True

    decision = machine.decide(KanbanState.DEV_READY.value, WorkflowEvent.START_DEV.value)
    assert decision.to_state == KanbanState.DEV_REVIEW
    assert decision.requires_agent == "dev"

    decision = machine.decide(KanbanState.DEV_REVIEW.value, WorkflowEvent.APPROVE_DEV.value)
    assert decision.to_state == KanbanState.QA_READY
    assert decision.requires_human_approval is True

    decision = machine.decide(KanbanState.QA_READY.value, WorkflowEvent.QA_COMPLETE.value)
    assert decision.to_state == KanbanState.QA_REVIEW
    assert decision.requires_agent == "qa"

    decision = machine.decide(KanbanState.QA_REVIEW.value, WorkflowEvent.APPROVE_QA.value)
    assert decision.to_state == KanbanState.READY_TO_DEPLOY
    assert decision.requires_human_approval is True

    decision = machine.decide(KanbanState.READY_TO_DEPLOY.value, WorkflowEvent.APPROVE_DEPLOY.value)
    assert decision.to_state == KanbanState.DONE
    assert decision.requires_human_approval is True


def test_done_cannot_be_reached_from_qa_review():
    machine = StateMachine()

    with pytest.raises(ValueError, match="invalid transition"):
        machine.decide(KanbanState.QA_REVIEW.value, WorkflowEvent.HUMAN_APPROVE.value)


def test_qa_failure_returns_to_dev_and_increments_retry():
    machine = StateMachine()

    decision = machine.decide(KanbanState.QA_REVIEW.value, WorkflowEvent.QA_FAIL.value)

    assert decision.to_state == KanbanState.DEV_READY
    assert decision.requires_agent == "dev"
    assert decision.increments_retry is True
