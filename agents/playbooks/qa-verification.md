---
name: qa-verification
version: 1
summary: 기획/설계안을 기준으로 Codex가 QA Plan을 만들고 의미 있는 증거를 수집한다.
triggers:
  - "harness qa"
  - "harness re-qa"
  - "Human QA 요청"
inputs:
  - github_issue
  - design_artifacts
  - dev_artifacts
  - target_repository
outputs:
  - qa-plan.md
  - qa-report.md
  - qa-checklist.md
  - browser-evidence
---
# Mission
이번 작업의 기획/설계안을 읽고 작업 전용 QA Plan을 만든다.
Codex는 해당 QA Plan에 맞는 자동 검증만 수행하고, 사람이 봐야 하는 항목은 Human QA 체크리스트로 넘긴다.

# Call Conditions
- Dev 단계가 완료되고 QA Ready 상태가 되었을 때 사용한다.
- re-qa에서는 기존 실패 원인과 재검증 범위를 먼저 확인한다.
- QA 기준이 불충분하면 fallback 사용 사실을 보고서 상단에 명시한다.

# Codex Execution Steps
1. 이슈 본문, design artifact, dev artifact, commit diff를 읽는다.
2. acceptance criteria와 edge case를 QA Plan 항목으로 재작성한다.
3. 변경 범위와 무관한 smoke test를 제거한다.
4. 자동 검증 가능한 항목과 Human QA 항목을 분리한다.
5. API, DB, 브라우저, build/test 중 의미 있는 검증만 실행한다.
6. 브라우저 캡처는 검증 기능의 시작부터 끝까지 찍고, 준비 단계 캡처는 제외한다.
7. 실패/엣지 케이스도 가능한 범위에서 캡처하고 설명한다.
8. 보고서에는 각 캡처 위 소제목, 아래 1~3줄 설명을 남긴다.

# Evidence
- QA Plan과 각 항목의 출처
- 자동 검증 결과
- Human QA 체크리스트
- 캡처 제목, 설명, 파일 경로
- 원본 로그 부록

# Handoff
- 최종 결론은 pass, fail, needs_human 중 하나로만 쓴다.
- 자동 검증하지 못한 항목은 별도 섹션에 둔다.
- Discord QA 메시지에는 Human QA 승인 명령을 포함한다.

# Decision Rules
- 이슈/설계의 QA 기준을 고정 체크리스트보다 우선한다.
- 자동 검증하지 않은 항목을 PASS로 표시하지 않는다.
- 브라우저 증거는 사람이 직관적으로 이해할 수 있어야 한다.
- 실패 케이스가 기능의 핵심이면 성공 케이스만으로 통과시키지 않는다.
- PDF 보고서는 짧은 결론, 기능별 검증, 증거, 부록 순서로 작성한다.

# Hard Rules
- 관련 없는 회원가입 smoke를 AI 채팅 기능 검증 근거로 쓰지 않는다.
- `[X]`를 통과 표시로 쓰지 않는다. 통과 표시는 `[V]`, 실패는 `[ ]` 또는 명시적 fail로 쓴다.
- 캡처 이미지만 나열하지 않는다.
- 준비 단계 화면을 핵심 기능 증거로 표시하지 않는다.
- 원본 로그를 보고서 본문보다 앞에 두지 않는다.

# Ask User When
- 자동 검증을 위해 실사용자 데이터 삭제나 외부 알림 발송이 필요할 때
- 기획/설계/구현 artifact가 서로 충돌해 QA 기준을 확정할 수 없을 때
