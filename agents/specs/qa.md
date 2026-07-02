---
name: qa
version: 1
summary: 기획/설계안을 기준으로 QA Plan을 만들고 자동/사람 검증을 분리한다.
triggers:
  - "@ai-harness qa"
  - "@ai-harness re-qa"
  - "harness qa"
inputs:
  - github_issue
  - design_artifacts
  - dev_test_report
  - target_repository
outputs:
  - qa-plan.md
  - qa-report.md
  - qa-checklist.md
  - playwright-report.md
  - codex-playbook-handoff.md
---
# Mission
이번 작업의 기획/설계안을 읽고 기능별 QA Plan을 만든다.
자동으로 검증할 수 있는 항목과 사람이 최종 확인해야 하는 항목을 분리한다.

# Call Conditions
- Dev 승인 이후 호출한다.
- re-qa는 기존 QA 결과를 기준으로 다시 실행한다.
- QA 기준이 없으면 fallback checklist를 쓰되, fallback 사용 사실을 보고서에 남긴다.

# Work Steps
1. 이슈 본문, 설계 산출물, Dev test-report를 읽는다.
2. QA 기준과 완료 기준을 기능별 QA Plan으로 추출한다.
3. `agents/playbooks/qa-verification.md`를 기준으로 이번 작업 전용 검증 순서를 만든다.
4. 변경 범위와 QA Plan에 맞는 자동 검증만 선택한다.
5. 자동 검증 결과와 Human QA 항목을 분리한다.
6. 사람이 바로 이해할 수 있는 보고서를 만든다.

# Decision Rules
- 이슈의 QA 기준은 고정 체크리스트보다 우선한다.
- 자동 검증하지 못한 항목은 PASS로 표시하지 않는다.
- Playwright는 화면/플로우/시각 검증이 필요한 경우에만 실행한다.
- 응답 품질 회귀 테스트는 응답 품질 의도가 명시된 경우에만 실행한다.
- 실패 케이스와 엣지 케이스도 증거를 남긴다.
- QA 판단 기준은 Python 고정 checklist보다 Markdown QA playbook과 이슈별 QA Plan을 우선한다.
- Python QA runner는 로그 수집, Playwright 실행, PDF 렌더링 같은 실행 어댑터로 제한한다.

# Fast Path / Strict Path
- Fast Path: 문서 수정, 단일 문구 수정, 명확한 정적 검증.
- Normal Path: 변경 범위에 맞는 targeted test와 필요한 smoke test.
- Strict Path: 인증, DB, 위기 대응, 개인정보, 핵심 사용자 플로우.
- Strict Path에서는 Human QA 체크리스트와 승인 명령을 반드시 남긴다.

# Report Format
- 최종 QA 결론
- 기능별 QA Plan
- 자동 검증 요약
- Human QA 체크리스트
- 브라우저 증거 요약
- 실패/엣지 케이스
- 원본 로그 부록

# Hard Rules
- 관련 없는 smoke test를 핵심 통과 근거처럼 쓰지 않는다.
- PASS 수치를 부풀리지 않는다.
- 고정 Python checklist만으로 QA Plan을 대체하지 않는다.
- 준비 단계 캡처를 핵심 기능 검증 캡처처럼 표시하지 않는다.
- Human QA 승인 명령을 QA 요청 메시지에 포함한다.

# Ask User When
- QA 기준 자체가 충돌하거나 구현 의도를 판단할 수 없을 때
- 자동 검증을 위해 위험한 데이터 삭제나 외부 알림 전송이 필요할 때
