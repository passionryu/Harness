---
name: backend-kotlin-spring
version: 1
summary: Kotlin Spring Boot 백엔드 변경을 DDD/hexagonal 경계에 맞춰 Codex가 직접 구현한다.
triggers:
  - "type: beFeature"
  - "Kotlin Spring Boot"
  - "DDD backend"
inputs:
  - approved_design
  - target_repository
  - backend_style_rules
outputs:
  - implementation.patch
  - test-report.md
  - migration-report.md
---
# Mission
승인된 백엔드 설계를 Kotlin Spring Boot 코드로 구현한다.
도메인, application, port, infrastructure, bootstrap 경계를 지키고, 컨트롤러는 얇게 유지한다.

# Call Conditions
- 작업이 도메인 정책, usecase, repository, API endpoint, DB migration에 걸쳐 있을 때 사용한다.
- 단순 문서 수정이나 프론트엔드 수정에는 사용하지 않는다.
- API 연동 작업은 백엔드 contract 변경이 실제로 필요한 경우에만 함께 사용한다.

# Codex Execution Steps
1. 이슈 본문, design artifact, 기존 코드 구조를 읽고 변경 범위를 확정한다.
2. 기존 package, naming, 테스트 스타일을 먼저 확인한다.
3. 도메인 정책과 application orchestration을 분리한다.
4. request/response DTO는 controller 내부에 숨기지 않고 기존 패턴에 맞게 둔다.
5. DB 변경이 필요하면 migration, nullable, unique, index, rollback 위험을 확인한다.
6. 예외 메시지, 사용자 응답, Swagger 설명은 한국어로 작성한다.
7. 단위 테스트와 통합 테스트 중 변경 위험에 맞는 검증을 실행한다.
8. build 또는 targeted Gradle test 결과를 남긴다.

# Evidence
- 변경한 domain/application/infrastructure/controller 파일
- migration 파일과 적용 이유
- 실행한 Gradle 명령과 결과
- 검증하지 못한 경계와 이유

# Handoff
- 변경된 API contract와 도메인 정책을 요약한다.
- FE에 전달해야 할 response shape, status code, error code를 명시한다.
- 사람이 확인해야 할 Swagger 또는 curl 기준을 남긴다.

# Decision Rules
- 유스케이스 흐름이 보이도록 application service를 작성한다.
- 의미 없는 한 줄 private method를 남발하지 않는다.
- 정책, 검증, 외부 연동, 상태 변경 책임은 이름이 명확한 객체로 분리한다.
- 트랜잭션 경계와 예외 변환 위치를 명확히 한다.
- 기존 테스트가 부족하면 최소 회귀 테스트를 추가한다.

# Hard Rules
- 컨트롤러에 비즈니스 로직을 넣지 않는다.
- FE 전용 수정에 이 playbook을 적용하지 않는다.
- schema 변경 없이 코드만 바꿔야 하는 작업에 migration을 만들지 않는다.
- 민감 데이터나 토큰을 로그에 남기지 않는다.
- 실패한 테스트를 삭제하거나 약화하지 않는다.

# Ask User When
- DB schema 정책이 설계에 확정되어 있지 않을 때
- API 응답 형태가 기존 FE와 충돌할 때
- 도메인 정책이 사용자 경험이나 서비스 약관성 표현에 영향을 줄 때
