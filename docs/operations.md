# Operations Guide

## Deterministic Operation

- All workflow state changes go through `workflows/state_machine.py`.
- Agents suggest outcomes; the orchestrator applies valid transitions.
- Artifact files are versioned by task and run id.
- Human approval is represented by a persisted timestamp and audit event.

## Retry Safety

- Every retry creates a new run.
- Old artifacts are never overwritten.
- QA failure loops back to `Dev Ready` only while retry limit remains.
- Exceeding retry limit stops the workflow and requires human intervention.

## Crash Recovery

On restart:

1. Load task state from DB.
2. Inspect latest run.
3. If a run has `started_at` but no `finished_at`, mark it failed or expired.
4. Resume only from the last persisted state.
5. Never infer success from missing artifacts.

## Context Management

Use artifacts as context boundaries:

- Plan Agent creates architecture/API/checklist artifacts.
- Dev Agent consumes plan artifacts, not the full conversation.
- QA Agent consumes plan, patch, and test report artifacts.
- Summaries are stored separately from raw logs.

## Observability

Each run should emit:

- timeline event
- structured JSON log
- artifact index
- status summary
- failure reason if present

The final answer to a user should cite the task id, current state, latest artifacts, and verification result.
