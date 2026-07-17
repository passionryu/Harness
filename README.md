# ai-harness

이 하네스는 GitHub Issue를 Codex 작업 단위로 바꾸고, Markdown 에이전트 정의와 실행 요청 artifact를 남기는 local-first 제어층입니다.
DB, 장기 상태 머신, Python 구현 실행기는 제거되었습니다.

목적은 Python 코드가 자동 개발자를 흉내 내는 것이 아니라, 사람이 읽고 수정하기 쉬운 Markdown 규칙을 기준으로 Codex가 직접 구현, 검증, 문서화를 수행하게 만드는 것입니다.

## How It Works

하네스는 GitHub Issue를 하나의 작업 단위로 보고, CLI 또는 GitHub webhook 요청에 따라 Agent artifact를 생성합니다.

- Agent 역할, 호출 조건, 판단 기준: `agents/specs/*.md`
- 실제 구현, 검증, 문서화 절차: `agents/playbooks/*.md`
- Issue별 산출물: `artifacts/issue-{number}/...`
- 실제 코드 수정, 테스트, 커밋, 푸시: Codex가 직접 수행

Python 코드는 GitHub/Notion/Discord 호출, artifact 생성, CLI/webhook adapter처럼 반복 가능한 도구 호출만 담당합니다.

## Agents

### Planning Assistant Agent

확정 전 기획 대화를 돕는 Agent입니다.
서비스 아이디어, 사용자 문제, 다음 기능 후보를 정리하고 GitHub Issue 생성 전의 기획 재료를 만듭니다.

### Design Agent

GitHub Issue를 개발 가능한 설계로 바꾸는 Agent입니다.
요구사항, 변경 대상, 구현 단위, API/DB/화면 흐름, QA 기준을 artifact로 남깁니다.

### UI/UX Designer Agent

UI/UX 방향성이 확정되지 않은 작업에서 먼저 호출하는 독립형 Agent입니다.
사용자와 대화하며 화면 방향성, 흐름, 상호작용, 검증 기준을 잡고 Design Agent로 넘길 재료를 만듭니다.

### Dev Agent

앱 코드를 직접 수정하지 않습니다.
`codex-implementation-request.md`와 `commit-plan.md`를 만들고, Codex가 어떤 playbook을 읽어야 하는지 지정합니다.

### QA Agent

고정 smoke checklist를 재사용하지 않습니다.
기획/설계 artifact와 변경 diff를 바탕으로 이슈 맞춤 QA Plan, 체크리스트, 보고서 초안을 만듭니다.
자동 검증하지 않은 항목은 pass로 표시하지 않습니다.

### Documentation Agent

Human QA 이후 구현 이력을 Notion에 정리합니다.
문서는 길게 쓰기보다 무엇이 추가되었고, 어떻게 동작하며, 어느 이슈와 연결되는지 빠르게 회고할 수 있게 정리합니다.

### Domain Knowledge Agent

서비스 정책과 도메인 결정을 Obsidian에 정리합니다.
Notion이 작업 이력이라면, Obsidian은 서비스가 어떤 의미와 정책을 갖는지 보관하는 지식 저장소입니다.

## Repository Map

```text
ai_harness/    CLI entrypoint used by Codex and local operators
orchestrator/  Stateless orchestration services and API adapters
agents/        Agent adapters, Markdown specs, Codex playbooks
workflows/     Legacy workflow notes retained for reference
rules/         Project and safety rules
sandbox/       Tool execution abstraction
mcp/           MCP tool abstraction layer
memory/        Task-scoped and summarized memory helpers
artifacts/     Generated issue context, handoff, QA, approval records
logs/          Local structured logs
tests/         pytest test suite
docs/          Architecture, operations, CLI documentation
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
harness sync --issue 13
harness agent-specs
harness playbooks
harness design --issue 13
harness develop --issue 13
harness qa --issue 13
harness approve --issue 13 --stage qa --approved-by rsy
harness document --issue 13
harness domain-knowledge --issue 13
harness status --issue 13
```

Detailed CLI usage is documented in [`docs/cli-usage-guide.md`](docs/cli-usage-guide.md).

If the console script is not installed yet, use the module form:

```bash
python -m ai_harness.cli status --issue 13
```

## Configuration

Configure `.env` with:

```env
GITHUB_OWNER=passionryu
GITHUB_REPO=myMentalCare
GITHUB_TOKEN=
GITHUB_WEBHOOK_SECRET=
ENABLE_GITHUB_COMMENT_COMMANDS=false
ALLOW_EXTERNAL_NOTIFICATIONS=false
DISCORD_WEBHOOK_URL=
NOTION_API_TOKEN=
NOTION_FEATURE_DATA_SOURCE_ID=
NOTION_HARNESS_HISTORY_DATA_SOURCE_ID=
OBSIDIAN_VAULT_PATH=/Users/rsy/Documents/myMentalCare Obsidian Vault
TARGET_REPO_PATH=/Users/rsy/Desktop/myPlayGround/myMentalCare
```

GitHub issue comments are disabled by default as human command input.
Use Codex as the primary human input interface and the CLI as the deterministic artifact generation interface.

External notifications are blocked by default.
Set `ALLOW_EXTERNAL_NOTIFICATIONS=true` only when you intentionally want real Discord messages to be sent.

## Issue Type Labels

Issue templates in the target repository should attach one of these labels:

```text
type: feFeature
type: beFeature
type: fullstackFeature
type: apiConnect
type: docs
type: infra
type: config
type: bugfix
type: hotfix
```

The Design and Dev agents use the `type:*` label plus issue content to choose the right Markdown playbook.

## Branch And Commit Rule

Development branch naming follows the issue type and issue number:

```text
type: beFeature        -> feature(BE)-1
type: feFeature        -> feature(FE)-2
type: fullstackFeature -> feature(FS)-3
type: bugfix           -> bugfix-4
type: apiConnect       -> api-connect-5
type: infra            -> infra-6
type: config           -> config-7
type: docs             -> docs-8
type: hotfix           -> hotfix-9
```

Commit messages use:

```text
[구현 기능(이슈 제목)] : 내용
```

## Local Target App

For the current target service frontend:

```bash
cd /Users/rsy/Desktop/myPlayGround/myMentalCare
pnpm --dir apps/web dev
```

For the current target service backend:

```bash
cd /Users/rsy/Desktop/myPlayGround/myMentalCare/apps/server
./gradlew :modules:bootstrap:mymentalcare:bootRun
```

Typical local URLs:

```text
Frontend: http://localhost:3000
Backend:  http://localhost:3001
Swagger:  http://localhost:3001/swagger-ui/index.html
```

## MVP Scope

The current MVP provides:

- CLI-first local harness entrypoint
- Design, Dev, QA, Documentation, Domain Knowledge agent adapters
- Markdown specs/playbooks as the source of agent behavior
- GitHub issue sync and generated progress comments
- artifact store for issue context, handoff, reports, and approvals
- Notion service history publishing
- Obsidian domain knowledge capture
- Discord notification support when explicitly enabled
- pytest coverage for CLI/API/agent adapter behavior

Legacy FastAPI server mode remains optional:

```bash
uvicorn orchestrator.main:app --reload --host 0.0.0.0 --port 3002
```
