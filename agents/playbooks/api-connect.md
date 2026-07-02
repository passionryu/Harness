---
name: api-connect
version: 1
summary: 프론트엔드와 백엔드 API contract를 Codex가 직접 연결하고 검증한다.
triggers:
  - "type: apiConnect"
  - "FE/BE 연동"
  - "contract 연결"
inputs:
  - approved_design
  - frontend_repository
  - backend_repository
  - api_contract
outputs:
  - implementation.patch
  - contract-test-report.md
  - browser-evidence
---
# Mission
프론트엔드 요청과 백엔드 응답을 실제 contract 기준으로 연결한다.
사용자 플로우, HTTP status, error response, loading/error UI가 함께 동작하는지 확인한다.

# Call Conditions
- 이미 존재하는 API를 화면 submit, query, mutation, client 함수와 연결할 때 사용한다.
- 백엔드 contract 자체가 아직 없으면 backend playbook과 분리해서 먼저 설계한다.
- 단순 UI만 바꾸는 작업에는 사용하지 않는다.

# Codex Execution Steps
1. API path, method, request json, response json, error code를 확인한다.
2. FE의 API client, form submit, query cache, 상태 관리 위치를 찾는다.
3. 기존 mocking 문구와 실제 API 연결이 충돌하지 않게 정리한다.
4. happy path와 최소 edge path를 화면 또는 API 수준에서 검증한다.
5. 백엔드 서버가 필요하면 실행 여부와 base URL을 명확히 기록한다.
6. 브라우저에서 사용자가 보는 성공/실패 메시지를 확인한다.
7. 관련 FE test, backend smoke, build 중 필요한 명령을 실행한다.

# Evidence
- request/response 예시
- 화면에서 확인한 성공/실패 상태
- 실행한 FE/BE 명령
- 서버 미실행 등으로 생략한 검증과 이유

# Handoff
- 연결된 API contract를 요약한다.
- 사람이 직접 확인할 입력값과 기대 화면을 남긴다.
- API 서버 주소, Swagger 주소, 승인 명령을 포함한다.

# Decision Rules
- 실제 contract를 이슈 본문보다 우선하되, 차이가 있으면 보고한다.
- 연동 전 mock-safe 안내는 실제 연동 후 제거하거나 의미를 바꾼다.
- 오류 응답은 사용자에게 안전한 문구로 변환한다.
- 불필요한 전체 회귀 smoke보다 변경 API 중심 검증을 우선한다.

# Hard Rules
- 회원가입 smoke 같은 무관한 API를 핵심 검증 근거로 쓰지 않는다.
- 실패 응답 처리를 생략하지 않는다.
- 백엔드 contract와 다른 임의 DTO를 FE에 만들지 않는다.
- 서버가 꺼져 있는데 PASS로 기록하지 않는다.

# Ask User When
- 어떤 API가 canonical contract인지 불분명할 때
- 실제 테스트 계정이나 안전한 테스트 데이터가 필요할 때
