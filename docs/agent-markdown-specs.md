# Agent Markdown Specs

## 목적

에이전트의 역할, 호출 조건, 판단 기준, 보고서 형식, 금지 사항은 Python 코드가 아니라
`agents/specs/*.md`에서 관리한다.

Python은 여전히 실행기 역할을 담당한다. GitHub, Notion, Discord, DB, git, Playwright, PDF, timeout,
retry, schema validation 같은 실패 처리가 필요한 부분은 코드로 남긴다.

## 파일 위치

```text
agents/specs/design.md
agents/specs/plan.md
agents/specs/dev.md
agents/specs/review.md
agents/specs/qa.md
agents/specs/documentation.md
agents/specs/domain_knowledge.md
agents/specs/planning_assistant.md
```

## 조회 방법

전체 목록:

```bash
harness agent-specs
```

특정 Agent 상세:

```bash
harness agent-specs --name qa
```

Codex 실행 playbook 목록:

```bash
harness playbooks
```

특정 playbook 상세:

```bash
harness playbooks --name qa-verification
```

JSON 출력:

```bash
harness --json agent-specs --name qa
```

## Markdown으로 관리하는 것

- Agent 역할 설명
- 호출 조건
- 작업 단계
- 판단 기준
- QA 체크리스트 생성 규칙
- Fast Path / Strict Path 기준
- 보고서 형식
- 금지 사항
- 사용자에게 물어봐야 하는 조건

## Python 코드로 남기는 것

- GitHub, Notion, Discord API 호출
- DB 상태 변경
- branch checkout, commit, push
- 파일 생성, 수정
- 테스트 명령 실행
- Playwright 실제 조작
- PDF 렌더링
- timeout, retry, error handling
- Markdown spec schema validation

## Codex Playbook

실제 구현, 검증, 문서화 절차는 `agents/playbooks/*.md`에 둔다.
Agent spec이 역할과 호출 조건을 정의한다면, playbook은 Codex가 어떤 파일을 읽고 어떤 순서로 실행하고 어떤 증거를 남길지 정의한다.

대표 playbook:

- `frontend-implementation`
- `backend-kotlin-spring`
- `api-connect`
- `qa-verification`
- `infra-config`
- `documentation`

## 필수 구조

각 spec은 frontmatter와 필수 섹션을 가져야 한다.

```markdown
---
name: qa
version: 1
summary: 기획/설계안을 기준으로 QA Plan을 만들고 자동/사람 검증을 분리한다.
triggers:
  - "@ai-harness qa"
inputs:
  - github_issue
outputs:
  - qa-report.md
---
# Mission
...

# Decision Rules
...

# Hard Rules
...
```

필수 frontmatter:

- `name`
- `version`
- `summary`
- `triggers`
- `inputs`
- `outputs`

필수 섹션:

- `Mission`
- `Decision Rules`
- `Hard Rules`

## 운영 원칙

- Markdown spec은 사람이 읽고 바꾸는 source of truth다.
- 코드가 아직 spec을 읽지 않는 영역은 spec을 운영 기준으로 삼되, 실제 연결 작업을 별도 이슈로 남긴다.
- spec 변경 후에는 `pytest tests/test_agent_spec.py`를 실행한다.
- 실행 판단과 작업 순서는 먼저 `agents/playbooks/*.md`에 추가한다.
- Python runner 변경은 외부 API, 테스트 실행, PDF 렌더링처럼 실제 부작용이 있는 adapter가 필요할 때만 한다.

## 현재 연결 상태

- 모든 주요 Agent의 Markdown spec이 존재한다.
- `harness agent-specs`로 에이전트 역할 목록과 상세를 조회할 수 있다.
- `harness playbooks`로 Codex 실행 playbook 목록과 상세를 조회할 수 있다.
- QA Agent는 `agents/specs/qa.md`를 읽어 QA 산출물에 Mission, Decision Rules, Hard Rules를 포함한다.
- 다른 Agent는 아직 spec을 실제 실행 context로 완전히 사용하지 않는다.
