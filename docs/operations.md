# Operations Guide

## Operating Model

This harness is stateless.
Each command reads current inputs, creates or updates artifacts, and exits.
The artifact tree is the source of operational truth.

## Standard Flow

```bash
harness sync --issue 13
harness design --issue 13
harness develop --issue 13
harness qa --issue 13
harness approve --issue 13 --stage qa --approved-by rsy
harness document --issue 13
harness status --issue 13
```

## Recovery

There is no stored workflow state to repair.
If a command fails:

1. Read the command error.
2. Check `artifacts/issue-{number}/...`.
3. Fix the input, environment, or Markdown spec/playbook.
4. Re-run the command.

Old artifacts may be overwritten by the same command when the output path is deterministic.
Important human decisions should be preserved in approval notes or commits.

## Context Management

Use artifacts as context boundaries:

- Design Agent creates architecture/API/checklist artifacts.
- Dev Agent consumes issue/design artifacts and creates Codex implementation requests.
- QA Agent consumes issue/design/dev artifacts and creates a QA Plan.
- Documentation Agent summarizes completed work for Notion.

## Notifications

External notifications are disabled by default.
Enable them only when needed:

```env
ALLOW_EXTERNAL_NOTIFICATIONS=true
DISCORD_WEBHOOK_URL=...
```

QA messages should be sent only after QA work is complete and must include the human QA approval command.

## Observability

The final answer to a user should cite:

- issue number
- artifact path
- performed verification
- commit hash and push status, if code changed
- remaining risk, if any
