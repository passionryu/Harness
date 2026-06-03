# ai-harness

AI-native software development harness for a human-controlled multi-agent development workflow.

This repository is an MVP foundation, not a fully autonomous developer. It is designed as a deterministic, auditable, reproducible, human-in-the-loop local orchestration system around Codex, GitHub Kanban records, artifacts, and a local SQLite run history.

## Principles

- Deterministic workflow over autonomous improvisation
- Human approval before irreversible transitions
- Isolated agent execution
- Artifact-first context management
- Retry-safe state machine
- Local-first development
- Small components that can be replaced later

## Kanban Flow

```text
Backlog
-> Plan Review
-> Dev Ready
-> Dev Review
-> QA Ready
-> QA Review
-> Ready To Deploy
-> Done
```

Each agent run stops at a review gate. A human must approve Plan, Dev, QA, and Deploy before the next stage can proceed.

## Repository Map

```text
ai_harness/    CLI entrypoint used by Codex and local operators
orchestrator/  DB models, orchestration services, legacy HTTP adapters
agents/        Agent abstraction and Plan/Dev/QA runner implementations
prompts/       Prompt templates and model-facing instructions
workflows/     State machine and event workflow definitions
rules/         Project and safety rules
sandbox/       Docker sandbox execution abstraction
mcp/           MCP tool abstraction layer
memory/        Task-scoped and summarized memory helpers
artifacts/     Generated plans, patches, QA reports, timelines
logs/          Local structured logs
tests/         pytest test suite
docs/          Architecture, operations, MVP documentation
```

## Quick Start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pytest
```

Run harness commands without starting a server:

```bash
harness sync --issue 8
harness plan --issue 8
harness approve --issue 8 --stage plan --approved-by rsy
harness develop --issue 8
harness approve --issue 8 --stage dev --approved-by rsy
harness qa --issue 8
harness approve --issue 8 --stage qa --approved-by rsy
harness approve --issue 8 --stage deploy --approved-by rsy
harness status --issue 8
```

Detailed CLI usage is documented in [`docs/cli-usage-guide.md`](docs/cli-usage-guide.md).

If the console script is not installed yet, use the module form:

```bash
python -m ai_harness.cli status --issue 8
```

Legacy FastAPI server mode is optional and no longer the primary input interface:

```bash
uvicorn orchestrator.main:app --reload --host 0.0.0.0 --port 3002
```

## CLI-first GitHub Issue Workflow

Configure `.env` with:

```env
GITHUB_OWNER=passionryu
GITHUB_REPO=studyHub
GITHUB_TOKEN=...
GITHUB_WEBHOOK_SECRET=...
ENABLE_GITHUB_COMMENT_COMMANDS=false
PLAN_TRIGGER_LABEL=ai-plan-ready
ALLOW_EXTERNAL_NOTIFICATIONS=false
GOOGLE_CHAT_WEBHOOK_URL=
DISCORD_WEBHOOK_URL=
```

Codex or a local operator should call the CLI:

```bash
harness create-issue --type config --title "[인증 기반 설정] Spring Security + JWT + Redis 인증 기반 설정" --body-file ./notes/config-issue.md
harness sync --issue 1
harness plan --issue 1
harness replan --issue 1 --note "기존 설계에서 로그인 정책을 다시 반영한다."
harness approve --issue 1 --stage plan --approved-by rsy --notes "설계를 확인했다."
harness develop --issue 1
harness refactor --issue 1 --note-file ./notes/refactor.md
harness approve --issue 1 --stage dev --approved-by rsy --notes "구현 결과를 확인했다."
harness qa --issue 1 --note "로그인 실패 케이스와 DB 저장 상태를 함께 확인한다."
harness re-qa --issue 1
harness approve --issue 1 --stage qa --approved-by rsy --notes "QA 결과를 확인했다."
harness approve --issue 1 --stage deploy --approved-by rsy --notes "배포 가능 상태로 승인한다."
harness status --issue 1
```

`harness fix-develop`은 deprecated된 호환 명령입니다. 개발 실패 복구는 Codex 대화형 수정 또는 Dev Agent 내부 runner 확장으로 처리합니다.

GitHub issue comments are not used as human command input anymore:

- GitHub issue comments are no longer used as a command input channel.
- `ENABLE_GITHUB_COMMENT_COMMANDS=false` keeps `issue_comment` webhook events ignored even if GitHub sends them.
- Use Codex as the primary human input interface; use GitHub issue comments as generated progress records only.
- GitHub webhook support is legacy/optional and should not be required for local development.

External notifications are blocked by default. Set `ALLOW_EXTERNAL_NOTIFICATIONS=true` only when you intentionally want real Google Chat or Discord messages to be sent. When enabled, `GOOGLE_CHAT_WEBHOOK_URL` or `DISCORD_WEBHOOK_URL` receives a notification after System QA or re-QA passes.

For the current StudyHub frontend, run the web app locally from the target repository:

```bash
cd /Users/rsy/Desktop/myPlayGround/studyHub
pnpm --dir apps/web dev
```

Then open the local Next.js URL shown by the command, usually `http://localhost:3000`.

Manual Human QA should check:

- 메인 화면에서 회원가입 진입 버튼 또는 링크가 보이는지
- 회원가입 진입 후 `/signup` 화면으로 이동하는지
- 이름, 이메일, 비밀번호, 전화번호, 관심 영역 입력 필드가 보이는지
- 모바일/데스크톱에서 레이아웃이 깨지지 않는지
- 필수값, 이메일 형식, 비밀번호 길이 검증이 사용자에게 자연스럽게 보이는지
- 정상 입력 후 제출 시 현재 단계에 맞는 안내 또는 mock-safe 동작이 보이는지

Development branch naming follows the issue type and issue number:

```text
type: beFeature   -> feature(BE)-1
type: feFeature   -> feature(FE)-2
type: bugfix      -> bugfix-3
type: apiConnect  -> api-connect-4
type: infra       -> infra-5
type: config      -> config-6
type: docs        -> docs-7
type: hotfix      -> hotfix-8
```

Dev Agent creates a commit plan before implementation. Each implementation unit must be committed separately with this message format:

```text
[구현 기능(이슈 제목)] : 내용
```

Example:

```text
[회원 가입 기능 화면 구현] : 버튼 추가
[회원 가입 기능 화면 구현] : validation 테스트 추가
```

Issue templates in the target repository should attach one of these labels:

```text
type: feFeature
type: beFeature
type: apiConnect
type: docs
type: infra
type: config
type: bugfix
type: hotfix
```

The Plan Agent reads the `type:*` label from the GitHub issue payload and uses it to choose a planning profile. Replan, refactor, QA, and cancel requests should be passed through CLI `--note` or `--note-file`.

## MVP Scope

The current MVP provides:

- CLI-first local harness entrypoint
- optional legacy FastAPI server skeleton
- PostgreSQL-ready SQLAlchemy models
- deterministic Kanban state machine
- Plan, Dev, QA agent abstractions with safe placeholder runners
- artifact store
- audit log model
- retry and timeout policy model
- Docker compose with Postgres for optional server deployments
- pytest coverage for workflow rules
- GitHub issue sync through the CLI
- GitHub issue comments as generated progress records only

Live OpenAI, GitHub Projects mutation, server mode, and Docker execution are intentionally abstracted behind interfaces so they can be enabled safely after local validation.
