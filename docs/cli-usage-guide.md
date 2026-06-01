# AI Harness CLI 사용 설명서

## 목적

이 문서는 FastAPI 서버, GitHub 댓글 명령, ngrok 없이 `ai-harness`를 로컬 CLI로 사용하는 방법을 설명한다.

현재 하네스의 기본 방향은 다음과 같다.

```text
사용자
-> Codex 대화
-> harness CLI
-> Agent / Runner
-> SQLite DB / artifacts / GitHub 기록
```

즉, 사용자는 복잡한 요구사항과 판단은 Codex와 대화하고, Codex 또는 로컬 운영자는 필요한 시점에 `harness` 명령을 실행한다.

## 핵심 원칙

- Codex가 사람과 상호작용하는 기본 입력 인터페이스다.
- GitHub 댓글은 더 이상 명령 입력 채널로 사용하지 않는다.
- FastAPI 서버는 선택적인 legacy 모드이며, 평소에는 띄울 필요가 없다.
- GitHub issue와 Kanban은 공식 작업 기록으로 사용한다.
- SQLite DB는 실행 이력과 상태 전이를 저장한다.
- `artifacts/`는 설계, 개발, QA 산출물을 저장한다.
- 자동화가 확실하지 않으면 성공한 척하지 않고 `needs_human` 또는 실패 상태로 멈춘다.

## 사전 준비

### 1. 위치 이동

```bash
cd /Users/rsy/Desktop/myPlayGround/harness
```

### 2. 가상환경 활성화

```bash
source .venv/bin/activate
```

### 3. 패키지 설치

처음 설치하거나 `pyproject.toml`이 바뀐 뒤에는 한 번 실행한다.

```bash
pip install -e ".[dev]"
```

설치가 끝나면 아래 명령이 생긴다.

```bash
harness --help
```

만약 `harness` 명령이 바로 잡히지 않으면 module 방식으로 실행할 수 있다.

```bash
python -m ai_harness.cli --help
```

### 4. 환경변수 확인

`.env`에는 최소한 다음 값이 필요하다.

```env
DATABASE_URL=sqlite:///./ai_harness.db
ARTIFACT_ROOT=artifacts
TARGET_REPO_PATH=/Users/rsy/Desktop/myPlayGround/studyHub

GITHUB_OWNER=passionryu
GITHUB_REPO=studyHub
GITHUB_TOKEN=...

ENABLE_GITHUB_COMMENT_COMMANDS=false
ALLOW_EXTERNAL_NOTIFICATIONS=false
```

중요한 점:

- `ENABLE_GITHUB_COMMENT_COMMANDS=false`가 기본이다.
- GitHub issue 댓글에 명령을 적어도 하네스는 실행하지 않는다.
- Discord/Google Chat 알림은 `ALLOW_EXTERNAL_NOTIFICATIONS=true`일 때만 실제로 전송된다.

## 전체 작업 흐름

일반적인 기능 개발 흐름은 다음 순서로 진행한다.

```bash
harness sync --issue 8
harness plan --issue 8
harness develop --issue 8
harness qa --issue 8
harness status --issue 8
```

설계를 다시 하고 싶으면:

```bash
harness replan --issue 8 --note "loginId 정책을 추가하고 email은 선택값으로 바꿔라."
```

개발 실패를 자동 복구하고 싶으면:

```bash
harness fix-develop --issue 8
```

개발 결과를 사람 요청에 맞춰 고치고 싶으면:

```bash
harness refactor --issue 8 --note "Controller 내부 DTO를 별도 파일로 분리하고, 에러 메시지는 한국어로 유지해라."
```

QA를 다시 돌리고 싶으면:

```bash
harness re-qa --issue 8 --note "내가 수정한 커밋 이후 흐름을 기준으로 다시 검증해라."
```

## 명령어 상세

### `harness sync`

GitHub issue를 하네스 DB로 가져온다.

```bash
harness sync --issue 8
```

전체 open issue를 가져오려면:

```bash
harness sync --all
```

동작:

- GitHub issue title, body, labels, URL을 읽는다.
- 로컬 SQLite `tasks` 테이블에 저장한다.
- 새 task의 상태는 `Backlog`로 둔다.
- 이미 존재하는 task는 title/body/URL만 최신화한다.

언제 쓰는가:

- GitHub에 새 이슈를 만들었고 하네스 DB에 아직 없을 때
- Kanban과 하네스 DB를 맞추고 싶을 때

주의:

- `sync`는 Agent를 실행하지 않는다.
- `sync`만으로 설계/개발/QA가 시작되지 않는다.

### `harness plan`

GitHub issue를 기반으로 Plan Agent를 실행한다.

```bash
harness plan --issue 8
```

이미 성공한 plan이 있어도 다시 실행하려면:

```bash
harness plan --issue 8 --force
```

동작:

- GitHub issue를 읽는다.
- `type:*` label을 바탕으로 작업 타입을 판단한다.
- task가 없으면 생성한다.
- 상태를 `Todo`로 맞춘다.
- Plan Agent를 실행한다.
- 설계 artifact를 생성한다.
- GitHub issue에 설계 요약 댓글을 남긴다.

주요 산출물:

```text
artifacts/{task_id}/plans/architecture.md
artifacts/{task_id}/plans/sequence-diagram.md
artifacts/{task_id}/plans/flow.md
artifacts/{task_id}/plans/flow-chart.md
artifacts/{task_id}/plans/edge-case-checklist.md
```

언제 쓰는가:

- 새 작업의 설계를 처음 만들 때
- GitHub issue의 요구사항을 Agent가 읽게 하고 싶을 때

### `harness replan`

사람의 수정 요청을 반영해 Plan Agent를 다시 실행한다.

```bash
harness replan --issue 8 --note "email은 nullable이고 loginId 또는 email로 로그인 가능하게 설계해라."
```

긴 요청은 파일로 전달한다.

```bash
harness replan --issue 8 --note-file ./notes/replan-issue-8.md
```

동작:

- GitHub issue를 다시 읽는다.
- `--note` 또는 `--note-file` 내용을 `Human Replan Request`로 기록한다.
- Plan Agent를 강제 재실행한다.
- 기존 설계와 별개로 새 run과 artifact를 남긴다.

언제 쓰는가:

- 설계가 마음에 들지 않을 때
- 미결정 사항을 사람이 결정했을 때
- 새로운 정책을 설계에 반영하고 싶을 때

### `harness develop`

Plan을 승인하고 Dev Agent를 실행한다.

```bash
harness develop --issue 8
```

동작:

- 성공한 Plan run이 있는지 확인한다.
- 상태가 `Todo`면 `In Progress`로 전환한다.
- Dev Agent를 실행한다.
- 작업 타입에 맞는 runner를 선택한다.
- 가능한 경우 코드를 수정하고 커밋한다.
- 개발 artifact를 생성한다.
- GitHub issue에 개발 요약 댓글을 남긴다.

주요 산출물:

```text
artifacts/{task_id}/dev/commit-plan.md
artifacts/{task_id}/dev/dev-status.md
artifacts/{task_id}/dev/implementation.patch
artifacts/{task_id}/dev/test-report.md
```

언제 쓰는가:

- 사람이 Plan을 보고 개발해도 된다고 판단했을 때
- Codex가 “이제 개발 진행”이라고 판단했을 때

주의:

- 현재 Dev Agent는 모든 기능을 완전 자동 구현하지 않는다.
- runner capability가 부족하면 `needs_human`으로 멈춘다.
- 실패하면 `fix-develop` 또는 Codex 수동 수정으로 이어간다.

### `harness fix-develop`

최근 실패한 Dev run을 읽고 자동 복구를 시도한다.

```bash
harness fix-develop --issue 8
```

동작:

- 해당 issue의 최근 실패한 Dev run을 찾는다.
- `dev-status.md`, `test-report.md`, 로그를 기준으로 실패 원인을 분류한다.
- 자동 수리 가능한 패턴이면 수정한다.
- 테스트를 다시 실행한다.
- 성공하면 task를 `In Progress` 상태로 유지한다.
- 실패하거나 매칭되지 않으면 사람에게 넘긴다.

언제 쓰는가:

- `develop`이 실패했을 때
- Gradle, Node, CORS, 설정 누락 같은 자동 복구 후보가 있을 때

주의:

- 모든 실패를 자동으로 고치지는 않는다.
- 원인 분류가 불명확하면 `needs_human`으로 멈추는 것이 정상이다.

### `harness refactor`

이미 구현된 결과를 사람 요청에 맞춰 구조 개선한다.

```bash
harness refactor --issue 8 --note "Controller 내부 data class를 별도 DTO 파일로 분리해라."
```

긴 요청은 파일로 전달한다.

```bash
harness refactor --issue 8 --note-file ./notes/refactor-issue-8.md
```

동작:

- 성공한 Dev 또는 Fix Develop run이 있는지 확인한다.
- 요청 메모를 `Human Refactor Request`로 기록한다.
- Dev Agent를 리팩터링 모드로 다시 실행한다.
- 상태를 `In Progress`로 돌린다.

언제 쓰는가:

- 자동 구현 결과가 마음에 들지 않을 때
- 코드 스타일, DDD 경계, DTO 분리, 메시지 정책 등을 사람이 보정하고 싶을 때

### `harness qa`

System QA Agent를 실행한다.

```bash
harness qa --issue 8
```

추가 QA 요청을 전달하려면:

```bash
harness qa --issue 8 --note "중복 로그인 아이디와 email nullable 케이스를 함께 검증해라."
```

동작:

- 상태가 `In Progress`인지 확인한다.
- QA Agent를 실행한다.
- 작업 타입에 맞는 smoke/curl/browser/db/config 검증을 수행한다.
- 통과하면 상태를 `System QA`로 전환한다.
- QA artifact를 생성한다.
- GitHub issue에 QA 요약과 Human QA 요청 내용을 남긴다.

주요 산출물:

```text
artifacts/{task_id}/qa/qa-report.md
artifacts/{task_id}/qa/qa-checklist.md
```

언제 쓰는가:

- 개발 결과가 준비되었고 시스템 검증으로 넘기고 싶을 때

### `harness re-qa`

System QA 상태에서 QA를 다시 실행한다.

```bash
harness re-qa --issue 8
```

수정 맥락을 전달하려면:

```bash
harness re-qa --issue 8 --note "내가 에러 메시지만 수정했으니 API 응답 메시지와 기존 성공 케이스를 다시 봐라."
```

동작:

- 상태가 `System QA`인지 확인한다.
- QA Agent를 다시 실행한다.
- 상태는 `System QA`로 유지한다.
- 새 QA run과 artifact를 남긴다.

언제 쓰는가:

- 사람이 코드를 조금 수정한 뒤 QA만 다시 확인하고 싶을 때
- 같은 작업을 재검증하고 싶을 때

### `harness status`

로컬 DB 기준으로 작업 상태를 조회한다.

```bash
harness status --issue 8
```

JSON으로 보고 싶으면:

```bash
harness --json status --issue 8
```

출력 예시:

```json
{
  "status": "ok",
  "task_id": "08dcfcef-8564-4705-b1af-75c483c35ff8",
  "issue": 8,
  "title": "[FS] 로그인 아이디 기반 회원가입/로그인",
  "state": "In Progress",
  "next": "@ai-harness qa",
  "latest_run": {
    "agent": "dev",
    "status": "success",
    "summary": "개발 구현이 완료되었습니다."
  }
}
```

주의:

- `status`는 GitHub 댓글을 남기지 않는다.
- 현재 하네스 DB에 저장된 상태만 보여준다.

### `harness cancel`

작업을 `Cancelled` 상태로 바꾼다.

```bash
harness cancel --issue 8 --note "요구사항 방향이 바뀌어 중지한다."
```

동작:

- task 상태를 `Cancelled`로 바꾼다.
- 상태 전이와 audit log를 남긴다.
- GitHub issue에 중지 요약을 남길 수 있다.

언제 쓰는가:

- 작업 자체를 더 진행하지 않기로 했을 때
- 잘못 생성한 이슈 또는 방향이 바뀐 이슈를 중단할 때

### `harness approve`

Human QA 승인을 기록한다.

```bash
harness approve --task-id 08dcfcef-8564-4705-b1af-75c483c35ff8 --approved-by rsy --notes "화면과 API를 직접 확인했다."
```

동작:

- task가 `Human QA` 상태일 때 `Done` 전이를 기록한다.
- 승인자와 승인 메모를 audit log에 남긴다.

주의:

- 현재 명령은 `issue number`가 아니라 `task id`를 사용한다.
- `task id`는 `harness status --issue {number}`로 확인한다.

## 출력 형식

기본 출력은 사람이 읽는 텍스트다.

```bash
harness status --issue 8
```

Codex나 다른 자동화가 파싱하기 좋게 하려면 `--json`을 붙인다.

```bash
harness --json status --issue 8
```

CLI는 JSON 출력이 깨지지 않도록 로그를 stderr로 보낸다.

## 작업 타입과 라벨

GitHub issue에는 다음 label 중 하나를 붙이는 것을 권장한다.

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

Plan Agent와 Dev Agent는 이 라벨을 보고 작업 성격을 판단한다.

예:

```text
type: beFeature
-> Kotlin/Spring Boot 백엔드 구현 중심

type: feFeature
-> Next.js 프론트엔드 화면/컴포넌트 구현 중심

type: fullstackFeature
-> 화면, API, DB, 연동을 함께 고려

type: apiConnect
-> 이미 있는 FE/BE를 연결

type: config
-> Security, Redis, profile, secret 등 설정 작업
```

## 상태 흐름

하네스의 기본 상태 흐름은 다음과 같다.

```text
Backlog
-> Todo
-> In Progress
-> System QA
-> Human QA
-> Done
```

상태 의미:

- `Backlog`: GitHub issue가 동기화되었지만 아직 설계 전
- `Todo`: Plan Agent가 완료되어 개발 가능
- `In Progress`: Dev Agent 또는 리팩터링이 진행된 상태
- `System QA`: QA Agent가 통과한 상태
- `Human QA`: 사람이 직접 확인해야 하는 상태
- `Done`: 사람이 최종 승인한 상태
- `Cancelled`: 작업 중지

## DB와 산출물 위치

### SQLite DB

기본 DB:

```text
/Users/rsy/Desktop/myPlayGround/harness/ai_harness.db
```

주요 테이블:

- `tasks`: 작업 단위와 현재 상태
- `runs`: Agent 실행 이력
- `artifacts`: 산출물 파일 인덱스
- `state_transitions`: 상태 전이 이력
- `audit_logs`: 감사 로그

CLI로 보는 것이 가장 간단하다.

```bash
harness status --issue 8
```

직접 SQLite를 보고 싶으면:

```bash
sqlite3 /Users/rsy/Desktop/myPlayGround/harness/ai_harness.db "select github_issue_number, title, state from tasks order by updated_at desc;"
```

### Artifact

산출물은 task id 기준으로 저장된다.

```text
artifacts/{task_id}/plans
artifacts/{task_id}/dev
artifacts/{task_id}/qa
```

IntelliJ에서 바로 열려면:

```bash
open -a "IntelliJ IDEA" /Users/rsy/Desktop/myPlayGround/harness/artifacts/{task_id}/qa/qa-report.md
```

## Codex에서 사용하는 방식

앞으로 사용자는 Codex에게 이렇게 말하면 된다.

```text
이슈 8번 sync 해줘.
이슈 8번 plan 돌려줘.
이슈 8번 develop 진행해줘.
이슈 8번 QA 해줘. QA 요청사항은 로그인 실패 케이스를 자세히 보는 것이다.
이슈 8번 status 확인해줘.
```

Codex는 내부적으로 다음 명령을 실행한다.

```bash
harness sync --issue 8
harness plan --issue 8
harness develop --issue 8
harness qa --issue 8 --note "로그인 실패 케이스를 자세히 보는 것이다."
harness status --issue 8
```

## 자주 쓰는 명령 모음

### 전체 open issue 동기화

```bash
harness sync --all
```

### 특정 이슈 상태 확인

```bash
harness status --issue 8
```

### 설계 생성

```bash
harness plan --issue 8
```

### 설계 강제 재생성

```bash
harness plan --issue 8 --force
```

### 사람의 결정사항을 반영해 재설계

```bash
harness replan --issue 8 --note "loginId는 필수, email은 선택값으로 한다."
```

### 개발 실행

```bash
harness develop --issue 8
```

### 개발 실패 복구

```bash
harness fix-develop --issue 8
```

### 사람 요청 기반 리팩터링

```bash
harness refactor --issue 8 --note "DDD 경계를 유지하고 controller를 얇게 정리해라."
```

### QA 실행

```bash
harness qa --issue 8
```

### QA 재실행

```bash
harness re-qa --issue 8 --note "내가 직접 수정한 커밋까지 포함해서 다시 검증해라."
```

### 작업 중지

```bash
harness cancel --issue 8 --note "요구사항 방향이 바뀌어 중지한다."
```

## 문제 해결

### `harness: command not found`

패키지 설치가 안 된 상태다.

```bash
cd /Users/rsy/Desktop/myPlayGround/harness
source .venv/bin/activate
pip install -e ".[dev]"
```

또는 module 방식으로 실행한다.

```bash
python -m ai_harness.cli status --issue 8
```

### `GITHUB_TOKEN이 필요합니다`

`.env`에 `GITHUB_TOKEN`이 없거나 잘못된 상태다.

확인:

```bash
grep GITHUB_TOKEN .env
```

토큰에는 최소한 대상 repository issue 읽기/쓰기 권한이 필요하다.

### `Plan을 찾을 수 없습니다`

`develop`, `qa`, `refactor`를 너무 빨리 실행한 경우다.

먼저 실행한다.

```bash
harness plan --issue 8
```

### `QA는 In Progress에서만 실행할 수 있습니다`

QA는 개발 완료 상태에서만 실행된다.

상태 확인:

```bash
harness status --issue 8
```

필요하면 먼저:

```bash
harness develop --issue 8
```

### `re-QA는 System QA에서만 실행할 수 있습니다`

아직 첫 QA가 통과하지 않은 상태다.

```bash
harness qa --issue 8
```

### Agent가 `needs_human`으로 멈춤

정상적인 방어 동작이다.

의미:

- 현재 runner가 안전하게 자동 구현하기 어렵다.
- 요구사항이 불명확하다.
- 로그는 읽었지만 자동 수리 전략에 매칭되지 않았다.
- 코드베이스 수정이 위험하다고 판단했다.

다음 행동:

```bash
harness status --issue 8
open -a "IntelliJ IDEA" artifacts/{task_id}/dev/dev-status.md
```

그 뒤 Codex에게 artifact 내용을 보고 수동 보정 또는 runner 강화 작업을 시킨다.

## FastAPI 서버에 대한 현재 입장

FastAPI 서버는 현재 기본 운영 방식이 아니다.

사용하지 않아도 되는 것:

- `uvicorn orchestrator.main:app`
- ngrok
- GitHub issue comment command webhook
- SSR 대시보드 명령 실행

서버를 나중에 다시 쓸 수 있는 경우:

- 팀원이 여러 명이어서 HTTP API가 필요할 때
- 외부 webhook 자동화가 다시 필요할 때
- read-only 관제 대시보드가 필요할 때
- 장기 실행 작업을 별도 서비스로 관리하고 싶을 때

현재 1인 개발 + Codex 중심 운영에서는 CLI가 기본이다.

## 권장 운영 습관

- 복잡한 요구사항은 Codex와 먼저 대화한다.
- GitHub issue에는 목표, 사용자 경험, 완료 기준을 간결히 남긴다.
- Agent 실행은 Codex에게 맡기거나 CLI로 직접 실행한다.
- 각 단계가 끝나면 `harness status --issue {number}`로 확인한다.
- 실패하면 먼저 artifact를 열어본다.
- 자동화가 부족하면 runner를 강화한다.
- Human QA와 최종 책임은 사람이 진다.
