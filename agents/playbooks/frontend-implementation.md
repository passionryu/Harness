---
name: frontend-implementation
version: 1
summary: 프론트엔드 화면, 상태, 폼, 사용자 메시지를 Codex가 직접 구현한다.
triggers:
  - "type: feFeature"
  - "type: bugfix"
  - "UI/UX 작업"
inputs:
  - approved_design
  - target_repository
  - current_ui_state
outputs:
  - implementation.patch
  - browser-evidence
  - test-report.md
---
# Mission
승인된 기획/설계안을 기준으로 프론트엔드 사용자 경험을 구현한다.
Codex가 실제 레포지토리를 읽고 필요한 컴포넌트, 상태, 스타일, 테스트를 직접 수정한다.

# Call Conditions
- 작업 범위가 화면, 폼, 라우팅, 상태, 사용자 메시지, 반응형 레이아웃에 걸쳐 있을 때 사용한다.
- FE bugfix는 백엔드 DDD runner로 라우팅하지 않고 이 playbook을 우선한다.
- API contract 구현이 필요한 경우 `api-connect` 성격의 작업인지 먼저 확인한다.

# Codex Execution Steps
1. 이슈 본문과 design artifact에서 사용자 플로우, acceptance criteria, 제외 범위를 추출한다.
2. 대상 앱의 package manager, framework, route 구조, 테스트 명령을 확인한다.
3. 기존 컴포넌트와 디자인 토큰을 먼저 찾고, 새 스타일 체계를 임의로 만들지 않는다.
4. 사용자가 보는 핵심 흐름부터 구현한다.
5. 상태 저장, 입력 검증, 에러/빈 상태/로딩 상태를 변경 범위에 맞게 연결한다.
6. 모바일과 데스크톱에서 텍스트 겹침, 레이아웃 깨짐, 클릭 불가능 영역을 확인한다.
7. 변경 범위에 맞는 단위 테스트, smoke test, build를 실행한다.
8. Playwright 또는 브라우저 캡처가 필요한 경우 기능 시작부터 끝까지의 의미 있는 장면만 남긴다.

# Evidence
- 변경 파일 목록
- 실행한 명령과 결과
- 브라우저 캡처 경로 또는 생략 사유
- 실패/엣지 케이스 확인 결과

# Handoff
- 구현한 사용자 흐름을 3줄 이내로 요약한다.
- 사람이 확인해야 할 화면과 입력값을 명시한다.
- 자동 검증하지 못한 항목은 PASS로 표시하지 않는다.

# Decision Rules
- 기존 UI 패턴과 design artifact를 우선한다.
- 작은 bugfix는 최소 변경으로 처리한다.
- 정신 건강 서비스 같은 민감 도메인은 과장된 표현보다 안정적이고 이해 가능한 문구를 우선한다.
- API 미연동 상태라면 mock-safe 안내와 실제 연동 필요 여부를 분리한다.
- 새 라이브러리는 기존 의존성으로 해결할 수 없을 때만 추가한다.

# Hard Rules
- FE 작업을 DDD Modeling Runner로 보내지 않는다.
- 마케팅형 랜딩 화면을 임의로 만들지 않는다.
- 관련 없는 색상/레이아웃 리디자인을 섞지 않는다.
- 테스트나 build를 실행하지 못했으면 이유를 기록한다.
- 준비 단계 로그인/회원가입 캡처를 핵심 기능 검증 증거처럼 쓰지 않는다.

# Ask User When
- UI 문구가 서비스 정책이나 의료/상담 표현을 바꿀 수 있을 때
- design artifact와 기존 화면 규칙이 충돌할 때
- API contract가 아직 확정되지 않았는데 실제 연동이 필요한 때
