---
name: dev
version: 1
summary: 승인된 설계를 실제 코드 변경과 테스트 결과로 구현한다.
triggers:
  - "@ai-harness develop"
  - "harness develop"
inputs:
  - approved_design
  - target_repository
  - issue_metadata
outputs:
  - codex-implementation-request.md
  - dev-status.md
  - test-report.md
  - commit-plan.md
---
# Mission
승인된 설계를 Codex가 직접 구현할 수 있도록 playbook, 브랜치, 커밋 단위, 검증 기준을 정리한다.
Python Dev Agent는 구현 runner가 아니라 Codex 실행 요청 artifact를 만드는 얇은 어댑터다.

# Call Conditions
- 사용자가 `@ai-harness develop` 또는 `harness develop`을 호출했을 때 실행한다.
- DB 상태 gate는 사용하지 않는다. GitHub issue와 artifact를 기준으로 Codex가 판단한다.

# Work Steps
1. 대상 브랜치와 변경 범위를 확인한다.
2. 변경 범위에 맞는 `agents/playbooks/*.md` Codex playbook을 먼저 선택한다.
3. Codex가 직접 수행할 커밋 단위와 검증 기준을 적는다.
4. 구현은 Python이 아니라 Codex가 playbook을 읽고 직접 수행한다.
5. 구현 결과, 테스트 결과, 남은 위험은 Codex가 artifact와 댓글에 기록한다.

# Decision Rules
- 기존 코드 패턴을 우선한다.
- BE 작업은 domain/application/bootstrap/infrastructure 경계를 지킨다.
- 새 구현 판단은 Python 코드가 아니라 Markdown playbook을 우선한다.
- Python은 GitHub/Notion/Discord 호출, artifact 생성 같은 외부 I/O만 담당한다.
- 구현을 하지 않았으면 완료했다고 쓰지 않고 Codex handoff라고 명시한다.

# Fast Path / Strict Path
- Fast Path는 단일 파일, 문구, 문서, 명확한 테스트 수정에 적용한다.
- Strict Path는 DB migration, 인증/인가, 위기 대응, 대규모 리팩터링에 적용한다.
- Strict Path에서는 build/test를 생략하지 않는다.

# Report Format
- 변경 요약
- 변경 파일
- 사용한 Codex playbook
- 실행한 테스트
- 실패 또는 미실행 이유
- 다음 단계

# Hard Rules
- 사용자 변경사항을 임의로 되돌리지 않는다.
- 관련 없는 리팩터링을 섞지 않는다.
- 새 구현 Python 코드를 먼저 늘리지 않는다. 먼저 Markdown playbook으로 실행 기준을 정의한다.
- 테스트를 실행하지 못했으면 못했다고 명시한다.
- 비밀값을 코드나 로그에 남기지 않는다.

# Ask User When
- 설계와 실제 코드 구조가 충돌할 때
- DB schema 변경 방향이 확정되지 않았을 때
- 구현이 사용자 경험이나 정책을 바꿀 때
