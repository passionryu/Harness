# ai-harness

AI-native software development harness for a human-controlled multi-agent development workflow.

This repository is an MVP foundation, not a fully autonomous developer. It is designed as a deterministic, auditable, reproducible, human-in-the-loop orchestration system around GitHub Kanban states.

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
Backlog -> Todo -> In Progress -> System QA -> Human QA -> Done
```

Only the orchestrator can move system-controlled states. `Done` requires explicit human approval.

## Repository Map

```text
orchestrator/  FastAPI app, DB models, orchestration services
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
uvicorn orchestrator.main:app --reload --host 0.0.0.0 --port 3002
```

Docker:

```bash
docker compose up --build
```

Health check:

```bash
curl http://localhost:3002/health
```

ngrok:

```bash
ngrok http --url=uproot-relax-retaliate.ngrok-free.dev --web-addr=localhost:3003 3002
```

## GitHub Issue Plan Workflow

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

Initial planning can be triggered manually through the harness API:

```bash
curl -X POST http://localhost:3002/sync/github/issues/1/plan
```

GitHub webhook support is now limited to issue metadata/state triggers:

- Webhook URL: `POST /webhooks/github`
- Required event: `Issues`
- Initial plan trigger: add the `ai-plan-ready` label to an issue
- `Issue comments` are intentionally not required.
- GitHub issue comments are no longer used as a command input channel.
- `ENABLE_GITHUB_COMMENT_COMMANDS=false` keeps `issue_comment` webhook events ignored even if GitHub sends them.
- Use Codex as the primary human input interface; use GitHub issue comments as generated progress records only.

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

The Plan Agent reads the `type:*` label from the GitHub issue payload and uses it to choose a planning profile.

Example replan comment:

```markdown
@ai-harness replan

- 회원가입은 별도 페이지가 아니라 모달로 만든다.
- 전화번호 필드는 제외한다.
```

The harness records the replan request in the generated plan artifacts and writes a new reviewable GitHub issue comment.

## MVP Scope

The current MVP provides:

- FastAPI server skeleton
- PostgreSQL-ready SQLAlchemy models
- deterministic Kanban state machine
- Plan, Dev, QA agent abstractions with safe placeholder runners
- artifact store
- audit log model
- retry and timeout policy model
- Docker compose with Postgres
- pytest coverage for workflow rules
- GitHub issue label trigger for Plan Agent
- GitHub issue comment trigger for initial Plan Agent execution
- GitHub issue comment trigger for human-requested replan
- GitHub issue comment trigger for System QA execution

Live OpenAI, GitHub Projects mutation, and Docker execution are intentionally abstracted behind interfaces so they can be enabled safely after local validation.
