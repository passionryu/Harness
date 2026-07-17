# MVP Plan

## MVP Goal

Build a local-first harness that turns GitHub issues into Codex-readable planning, implementation, QA, and documentation artifacts.
The MVP avoids persistent workflow state and keeps the source of agent behavior in Markdown.

## Current MVP Scope

- CLI-first local entrypoint
- GitHub issue context sync
- Markdown Agent specs
- Markdown Codex playbooks
- Design, Dev, QA, Documentation, Domain Knowledge adapters
- artifact-based status and approval records
- optional GitHub comments
- optional Discord/Notion/Obsidian integrations
- pytest validation for CLI/API/agent adapter behavior

## Non-Goals

- autonomous production deployment
- hidden state mutation by agents
- Python implementation logic for app code
- persistent workflow database
- unbounded self-retry
- broad repo crawling without scoped context

## Next MVP Hardening

1. Keep QA Plan generation tied to the issue design, not fixed smoke tests.
2. Keep Dev routing tied to issue type and content, not backend-first defaults.
3. Keep artifacts short enough for a human to understand immediately.
