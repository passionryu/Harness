# ai-harness

`ai-harness`는 완전 자율 개발 AI가 아니라, 사람이 승인하고 통제하는 AI 개발 조직을 만들기 위한 로컬 우선 하네스입니다.
Codex를 주 입력 인터페이스로 사용하고, GitHub Issue/Kanban, 로컬 artifact, SQLite 실행 이력, Notion, Obsidian을 연결해 작업 흐름을 기록합니다.
목표는 “AI가 알아서 다 하는 개발”이 아니라, 설계·개발·검증·문서화를 재현 가능한 단계로 나누고 사람이 중요한 지점마다 승인하는 것입니다.
각 Agent는 결과를 산출물과 댓글/문서로 남기며, 자동화가 불확실한 작업은 성공한 척하지 않고 사람에게 넘깁니다.

## How It Works

하네스는 GitHub Issue를 하나의 작업 단위로 보고, GitHub Kanban의 상태 흐름에 맞춰 Agent를 호출합니다.
Agent는 직접 최종 결정을 내리지 않고 설계안, 구현 결과, 리뷰 결과, QA 리포트 같은 evidence를 남깁니다.
사람은 각 gate에서 결과를 검토하고 승인하거나 수정 지시를 내립니다.

-> 하네스 워크 플로우
<img width="1672" height="941" alt="image" src="https://github.com/user-attachments/assets/434b84bc-a344-4403-a9cc-d0a6a1e9a8e0" />

-> 사전에 정의된 칸반 기반의 워크 플로우
<img width="1703" height="769" alt="image" src="https://github.com/user-attachments/assets/fff6007e-2b5a-400b-82df-4c223ebce090" />
-> 위 하네스로 개발중인 토이 프로젝트     
* 레포지토리 : https://github.com/passionryu/myMentalCare     
* RailWay를 통한 간단한 MVP 배포 : https://my-mental-careweb-production.up.railway.app/   

## Agents

### 🧭 Planning Assistant Agent

기획 보조 Agent입니다.
서비스 아이디어, 사용자 문제, 다음 기능 후보를 함께 정리합니다.
Obsidian에 쌓인 기획 메모와 도메인 지식을 참고해 “무엇을 만들면 좋을지”를 제안합니다.
이 Agent의 결과는 바로 구현 명령이 아니라, GitHub Issue로 만들기 전의 기획 대화 재료입니다.

### 🏗️ Design Agent

기획안을 개발 가능한 설계로 바꾸는 Agent입니다.
요구사항을 읽고 변경 대상, 구현 단위, API/DB/화면 흐름, QA 기준을 정리합니다.
시퀀스 다이어그램은 개발자가 이해할 수 있게 기술적으로 작성하고, 플로우 차트는 사용자와 도메인 관점에서 작성합니다.
미결정 사항이 있으면 바로 구현으로 넘기지 않고 사람에게 질문해야 합니다.

### 🛠️ Dev Agent

설계가 승인된 작업을 실제 코드 변경으로 옮기는 Agent입니다.
브랜치를 만들고, 구현 단위를 나누고, 각 단위마다 커밋을 남깁니다.
내부적으로 DDD Modeling, DB Migration, API Implementation, Frontend Implementation, API Connect, Test Implementation runner를 사용합니다.
자동 구현 능력이 부족한 작업은 `needs_human`으로 멈추고, 어떤 runner capability가 부족한지 보고합니다.

### 🧐 Review Agent

Dev 완료 후 QA 전에 코드 품질을 검토하는 Agent입니다.
DDD/hexagonal boundary, 테스트 이름, 에러 메시지, 로깅 규칙, 불필요한 scaffold, 이상한 커밋을 확인합니다.
리뷰 결과가 수정 필요라면 Dev 단계로 되돌릴 근거를 남깁니다.
이 Agent는 “테스트 통과 여부”보다 “코드가 장기적으로 유지보수 가능한가”를 보는 역할입니다.

### 🔎 QA Agent

시스템 검증을 담당하는 Agent입니다.
단위/통합 테스트, curl 시나리오, 브라우저 화면 확인, DB 저장 상태, 인증/인가 경계, 회귀 여부를 확인합니다.
자동으로 확인할 수 있는 것은 직접 검증하고, 사람이 봐야 하는 것은 Human QA 체크리스트로 넘깁니다.
QA가 끝나면 GitHub Issue와 Discord에 사람이 확인할 URL, Swagger 주소, 검증 항목을 남깁니다.

### 📝 Documentation Agent

Human QA 이후 구현 이력을 Notion에 정리하는 Agent입니다.
이슈별 설계, 개발, QA 요약을 서비스 구현 기록 표에 남깁니다.
문서는 길게 쓰기보다 “무엇이 추가되었고, 어떻게 동작하며, 어느 이슈와 연결되는지”를 빠르게 회고할 수 있게 정리합니다.
항상 자동 실행하지 않고, 사람이 필요하다고 판단할 때 호출합니다.

### 🧠 Domain Knowledge Agent

서비스 지식과 도메인 결정을 Obsidian에 정리하는 Agent입니다.
구현된 기능의 정책, 사용자 흐름, 확정된 결정사항을 기획 보조 Agent가 나중에 참고할 수 있는 형태로 남깁니다.
Notion이 작업 이력이라면, Obsidian은 서비스가 어떤 의미와 정책을 갖는지 보관하는 지식 저장소입니다.
항상 정리할 필요는 없고, 서비스 방향에 영향을 주는 기능일 때 호출합니다.

## Repository Map

```text
ai_harness/    CLI entrypoint used by Codex and local operators
orchestrator/  DB models, orchestration services, legacy HTTP adapters
agents/        Agent abstraction and Design/Dev/Review/QA/Docs implementations
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
harness sync --issue 13
harness design --issue 13
harness approve --issue 13 --stage plan --approved-by rsy
harness develop --issue 13
harness approve --issue 13 --stage dev --approved-by rsy
harness qa --issue 13
harness approve --issue 13 --stage qa --approved-by rsy
harness document --issue 13
harness domain-knowledge --issue 13
harness approve --issue 13 --stage deploy --approved-by rsy
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
GITHUB_TOKEN=...
GITHUB_WEBHOOK_SECRET=
ENABLE_GITHUB_COMMENT_COMMANDS=false
ALLOW_EXTERNAL_NOTIFICATIONS=false
DISCORD_WEBHOOK_URL=
NOTION_API_TOKEN=
NOTION_FEATURE_DATA_SOURCE_ID=
NOTION_HARNESS_HISTORY_DATA_SOURCE_ID=
OBSIDIAN_VAULT_PATH=/Users/rsy/Documents/myMentalCare Obsidian Vault
```

GitHub issue comments are not used as human command input anymore:

- Use Codex as the primary human input interface.
- Use the CLI as the deterministic execution interface.
- Use GitHub issue comments as generated progress records only.
- Keep `ENABLE_GITHUB_COMMENT_COMMANDS=false` unless intentionally testing legacy webhook input.

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

The Design Agent reads the `type:*` label from the GitHub issue payload and uses it to choose a planning profile.
Replan, refactor, QA, and cancel requests should be passed through CLI `--note` or `--note-file`.

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

Dev Agent creates a commit plan before implementation.
Each implementation unit should be committed separately with this message format:

```text
[구현 기능(이슈 제목)] : 내용
```

Example:

```text
[AI 마음 대화 MVP 구현] : 채팅 도메인 모델 추가
[AI 마음 대화 MVP 구현] : 채팅 화면과 API 연동 추가
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
- deterministic Kanban state machine
- Design, Dev, Review, QA, Documentation, Domain Knowledge agent abstractions
- GitHub issue sync and generated progress comments
- artifact store for plans, patches, reports, and documentation
- SQLite run and state transition history
- Notion service history publishing
- Obsidian domain knowledge capture
- Discord notification support
- pytest coverage for workflow rules

Legacy FastAPI server mode remains optional and is no longer the primary input interface:

```bash
uvicorn orchestrator.main:app --reload --host 0.0.0.0 --port 3002
```

Live OpenAI, GitHub Projects mutation, server mode, and Docker execution are intentionally kept behind interfaces so they can be enabled safely after local validation.
