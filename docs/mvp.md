# MVP Plan

## MVP Goal

Build a local-first harness that can model a GitHub Kanban workflow and run deterministic placeholder agents while preserving artifacts, audit trail, retry history, and human approval gates.

## Phase 1: Local Orchestrator

- FastAPI server
- PostgreSQL schema
- manual task creation
- manual event injection
- deterministic state machine
- placeholder Plan/Dev/QA agents
- local artifact store
- pytest validation

## Phase 2: GitHub Integration

- GitHub webhook signature verification
- issue/card state sync
- issue comments for artifacts
- branch and PR metadata capture

## Phase 3: Real Agent Execution

- OpenAI API-backed agent runner
- prompt templates
- MCP tool abstraction
- Docker sandbox execution
- patch generation and test execution

## Phase 4: Human QA Platform

- Human QA approval endpoint
- report UI or static report artifacts
- Google Chat/Notion notifications through MCP or webhook adapters

## Non-Goals For MVP

- Autonomous production deployment
- Write access to production systems
- unbounded self-retry
- hidden state mutation by agents
- broad repo crawling without scoped context

