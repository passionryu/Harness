import pytest

from workflows.state_machine import KanbanState, StateMachine, WorkflowEvent


def test_happy_path_transitions():
    machine = StateMachine()

    decision = machine.decide(KanbanState.BACKLOG.value, WorkflowEvent.TRIAGE.value)
    assert decision.to_state == KanbanState.TODO
    assert decision.requires_agent == "plan"

    decision = machine.decide(KanbanState.TODO.value, WorkflowEvent.START_DEV.value)
    assert decision.to_state == KanbanState.IN_PROGRESS
    assert decision.requires_agent == "dev"

    decision = machine.decide(KanbanState.IN_PROGRESS.value, WorkflowEvent.DEV_COMPLETE.value)
    assert decision.to_state == KanbanState.SYSTEM_QA
    assert decision.requires_agent == "qa"

    decision = machine.decide(KanbanState.SYSTEM_QA.value, WorkflowEvent.QA_PASS.value)
    assert decision.to_state == KanbanState.HUMAN_QA

    decision = machine.decide(KanbanState.HUMAN_QA.value, WorkflowEvent.HUMAN_APPROVE.value)
    assert decision.to_state == KanbanState.DONE
    assert decision.requires_human_approval is True


def test_done_cannot_be_reached_from_system_qa():
    machine = StateMachine()

    with pytest.raises(ValueError, match="invalid transition"):
        machine.decide(KanbanState.SYSTEM_QA.value, WorkflowEvent.HUMAN_APPROVE.value)


def test_qa_failure_returns_to_dev_and_increments_retry():
    machine = StateMachine()

    decision = machine.decide(KanbanState.SYSTEM_QA.value, WorkflowEvent.QA_FAIL.value)

    assert decision.to_state == KanbanState.IN_PROGRESS
    assert decision.requires_agent == "dev"
    assert decision.increments_retry is True

