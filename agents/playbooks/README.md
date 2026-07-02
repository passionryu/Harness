# Codex Playbook Common Contract

이 디렉토리는 Python 자동 runner를 늘리는 대신 Codex가 직접 읽고 실행할 Markdown playbook을 보관한다.
에이전트의 역할, 판단 기준, 실행 순서, 검증 기준은 Markdown을 원본으로 삼고, Python 코드는 상태 전이, 외부 API 호출, 산출물 저장 같은 얇은 실행 어댑터로 제한한다.

## 기본 원칙

1. 작업을 시작하기 전에 대상 이슈, 승인된 design 산출물, 기존 artifact, 변경 대상 레포지토리 상태를 확인한다.
2. 이슈 타입과 변경 범위에 맞는 playbook을 선택한다.
3. playbook의 `Codex Execution Steps`를 따라 Codex가 직접 파일을 읽고 수정하고 테스트한다.
4. 자동화 코드가 처리할 수 없다는 이유만으로 관련 없는 runner로 우회하지 않는다.
5. 구현, 검증, 남은 위험, 다음 사람 승인 기준을 `Handoff` 형식으로 남긴다.

## Python에 남기는 책임

- GitHub, Notion, Discord API 호출
- 상태 머신 전이와 approval 기록
- DB 저장과 artifact 경로 관리
- 브랜치 checkout, commit, push의 안전장치
- 테스트 명령 실행 결과 수집
- Playwright 실행, screenshot 저장, PDF 렌더링 같은 I/O 작업
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

## Legacy Runner Policy

기존 `agents/runners/*.py`는 즉시 삭제하지 않는다.
현재 auto-run, QA PDF, 상태 전이와 연결되어 있으므로 호환층으로 유지한다.
새 기능을 추가할 때는 먼저 Markdown playbook을 작성하고, Python runner 확장은 필요한 외부 I/O나 반복 실행 어댑터가 있을 때만 한다.
