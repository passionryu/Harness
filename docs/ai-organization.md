# AI Harness Organization

## 목적

이 하네스는 완전 자율 개발자가 아니라 사람이 통제하는 AI 개발 조직이다.
따라서 자동 구현이 불확실한 작업은 성공한 척하지 않고, 어떤 책임 러너가 부족한지 명확히 보고한 뒤 사람에게 넘긴다.

## Product Planner Agent

- Domain Analyzer: 도메인 개념과 책임 경계를 분석한다.
- Requirement Clarifier: 미결정 사항과 질문을 찾는다.
- Risk Detector: 실패 가능성과 영향 범위를 탐지한다.
- Work Unit Decomposer: 요구사항을 실행 가능한 책임 단위로 나눈다.
- Acceptance Criteria Writer: 시스템 QA와 Human QA 기준을 정리한다.

## Development Agent

- DDD Modeling Runner: 도메인 모델, 정책, 유스케이스 흐름을 구현한다.
- DB Migration Runner: schema, index, nullable, unique 정책을 구현한다.
- API Implementation Runner: endpoint, request/response, application 연결을 구현한다.
- Frontend Implementation Runner: 화면, 상태, 폼, 사용자 메시지를 구현한다.
- API Connect Runner: 프론트엔드 요청과 백엔드 contract를 연결한다.
- Event Flow Runner: 이벤트, 채팅, 실시간 흐름을 구현한다.
- Refactoring Runner: 사람의 수정 요구를 기존 구현에 반영한다.
- Test Implementation Runner: 단위, 통합, smoke 테스트를 작성하고 실행한다.

현재 Development Agent의 책임 러너들은 capability gate를 기본으로 동작한다.
즉, 필요한 책임을 식별하고 artifact로 남기되, 범용 자동 구현 능력이 없는 경우 `needs_human`으로 중단한다.

현재 구현된 1차 capability:

- 모든 Development Runner는 코드베이스 스냅샷을 읽고 artifact에 남긴다.
- DDD Modeling Runner는 명시된 `METHOD /api/...` endpoint가 있으면 `usecase-orchestration-style`을 참고해 application layer의 Command, Result, Service, PolicyChecker scaffold를 생성할 수 있다.
- Frontend Implementation Runner는 명시된 화면 route가 있으면 Next.js page scaffold를 생성할 수 있다.
- DB Migration Runner는 명시된 `sql` code block이 있으면 Flyway migration 파일을 생성할 수 있다.
- API Implementation Runner는 명시된 `METHOD /api/...` endpoint가 있으면 API contract 초안을 생성할 수 있다.
- Test Implementation Runner는 기존 프론트엔드/백엔드 테스트 명령을 찾아 실제로 실행할 수 있다.
- Refactoring Runner는 명확한 요청이 있으면 Controller 내부 `data class`를 별도 Kotlin 파일로 분리할 수 있다.

아직 구현되지 않은 부분:

- 실제 도메인 정책, 저장소 연결, 상태 변경까지 포함한 완전한 application service 구현
- Controller, DTO, Repository adapter의 범용 자동 구현
- 기존 화면에 자연스럽게 UI를 삽입하는 범용 자동 구현
- 복잡한 FE/BE contract mismatch 자동 수정

## Fix Develop Agent

- Failure Log Analyzer: 실패한 run과 로그를 읽고 실패 원인을 분류한다.
- Compile Error Fix Runner: 컴파일 실패를 복구한다.
- Test Failure Fix Runner: 깨진 테스트를 복구한다.
- Dependency/Config Fix Runner: 의존성이나 설정 누락을 복구한다.
- Contract Mismatch Fix Runner: FE/BE contract 불일치를 복구한다.
- Frontend Build Fix Runner: 프론트엔드 빌드와 타입 오류를 복구한다.
- Regression Verification Runner: 수정 후 회귀 검증을 실행한다.

현재는 CORS preflight 테스트 실패처럼 안전하게 고칠 수 있는 일부 패턴부터 자동 수리한다.
매칭되지 않는 실패는 `needs_human`으로 넘긴다.

## QA Agent

- Integration Test Runner: 서비스 경계 간 통합 테스트를 실행한다.
- Curl Scenario Runner: 실제 API curl 시나리오를 실행한다.
- Browser Scenario Runner: 브라우저 사용자 흐름을 검증한다.
- DB State Validator: DB 저장 결과와 정합성을 검증한다.
- Concurrency Test Runner: 동시성 충돌을 검증한다.
- Idempotency Validator: 반복 요청과 멱등성을 검증한다.
- Security Boundary Validator: 인증/인가 경계를 검증한다.
- Regression Detector: 기존 기능 회귀를 탐지한다.

현재 QA Agent는 지원되는 타입별 smoke, curl, config 검증을 실행하고,
자동 검증이 부족한 부분은 Human QA 체크리스트로 넘긴다.

## Human QA Support

- Human Checklist Writer: 사람이 확인할 체크리스트를 작성한다.
- QA Notification Runner: Discord 또는 Google Chat으로 QA 요청을 보낸다.
- Manual Verification Guide Runner: 확인 URL, Swagger, curl 기준을 정리한다.
- Approval Recorder: 사람의 최종 승인 기록을 남긴다.

Human QA는 사람이 직접 수행한다.
AI는 사람의 검증이 쉽도록 체크리스트, URL, 산출물 위치, 승인 기록만 지원한다.

## 운영 원칙

- 특정 기능 전용 구현을 기본값으로 두지 않는다.
- runner는 책임 단위로 작게 나눈다.
- 자동 구현이 불확실하면 `needs_human`으로 멈춘다.
- 실패한 run은 `@ai-harness status`와 artifact로 추적 가능해야 한다.
- 자동 수리 가능한 실패만 `@ai-harness fix-develop`이 처리한다.
- Human QA 승인 없이는 Done으로 이동하지 않는다.
