# Codex Playbook Common Contract

이 디렉토리는 Codex가 직접 읽고 실행할 Markdown playbook을 보관한다.
에이전트의 역할, 판단 기준, 실행 순서, 검증 기준은 Markdown을 원본으로 삼고, Python 코드는 외부 API 호출과 산출물 저장 같은 얇은 어댑터로 제한한다.

## 기본 원칙

1. 작업을 시작하기 전에 대상 이슈, 승인된 design 산출물, 기존 artifact, 변경 대상 레포지토리 상태를 확인한다.
2. 이슈 타입과 변경 범위에 맞는 playbook을 선택한다.
3. playbook의 `Codex Execution Steps`를 따라 Codex가 직접 파일을 읽고 수정하고 테스트한다.
4. 자동화 코드가 처리할 수 없다는 이유로 관련 없는 작업 흐름으로 우회하지 않는다.
5. 구현, 검증, 남은 위험, 다음 사람 승인 기준을 `Handoff` 형식으로 남긴다.

## Python에 남기는 책임

- GitHub, Notion, Discord API 호출
- artifact 경로 생성과 파일 저장
- Codex가 직접 실행한 명령 결과 정리
- Codex가 직접 수행한 Playwright screenshot, PDF 렌더링 결과 정리
- timeout, retry, error handling, schema validation

## Markdown으로 관리하는 책임

- 에이전트 역할 설명
- 호출 조건
- 작업 단계
- 판단 기준
- QA 체크리스트 생성 규칙
- Fast Path와 Strict Path 기준
- 보고서 형식
- 금지 사항
- 사용자에게 질문해야 하는 조건

## Handoff

각 playbook 실행 후 다음 형식을 artifact 또는 최종 보고에 남긴다.

```md
## Handoff

### 실행한 playbook
- `agents/playbooks/<name>.md`

### 변경 요약
- 실제로 바꾼 기능, 파일, 정책을 적는다.

### 검증 요약
- 실행한 테스트, 브라우저 검증, 수동 확인 항목을 적는다.

### 남은 위험
- 자동 검증하지 못한 항목과 이유를 적는다.

### 다음 사람 승인 기준
- 사람이 확인해야 할 체크리스트와 승인 명령을 적는다.
```

## Python Adapter Policy

`agents/runners/*.py`는 제거되었다.
새 기능을 추가할 때는 먼저 Markdown playbook을 작성하고, Python 확장은 외부 API 호출이나 artifact 저장처럼 Codex가 직접 수행할 수 없는 I/O가 있을 때만 한다.
