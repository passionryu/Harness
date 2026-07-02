# AI Harness Organization

## 목적

이 하네스는 완전 자율 개발자가 아니라 사람이 통제하는 AI 개발 조직이다.
따라서 Codex handoff 또는 도구 호출기로 안전하게 처리하기 어려운 작업은 성공한 척하지 않고, 어떤 책임이나 capability가 부족한지 명확히 보고한 뒤 사람에게 넘긴다.

## Product Planner Agent

- Domain Analyzer: 도메인 개념과 책임 경계를 분석한다.
- Requirement Clarifier: 미결정 사항과 질문을 찾는다.
- Risk Detector: 실패 가능성과 영향 범위를 탐지한다.
- Work Unit Decomposer: 요구사항을 실행 가능한 책임 단위로 나눈다.
- Acceptance Criteria Writer: 시스템 QA와 Human QA 기준을 정리한다.

## Development Agent

- DDD Modeling Runner: 도메인 모델, 정책, 유스케이스 흐름 책임을 식별하고 backend playbook handoff를 남긴다.
- DB Migration Runner: schema, index, nullable, unique 정책 책임을 식별하고 DDL 요약을 남긴다.
- API Implementation Runner: endpoint, request/response, application 연결 책임을 식별하고 backend playbook handoff를 남긴다.
- Frontend Implementation Runner: 화면, 상태, 폼, 사용자 메시지 책임을 식별하고 frontend playbook handoff를 남긴다.
- API Connect Runner: 프론트엔드 요청과 백엔드 contract 연결 책임을 식별하고 api-connect playbook handoff를 남긴다.
- Event Flow Runner: 이벤트, 채팅, 실시간 흐름 책임을 식별하고 playbook handoff를 남긴다.
- Refactoring Runner: 사람의 수정 요구 범위를 식별하고 Codex handoff를 남긴다.
- Test Implementation Runner: 반복 가능한 테스트 명령을 실행하고 결과를 수집한다.

현재 Development Agent의 책임 러너들은 Codex playbook handoff adapter로 동작한다.
즉, 필요한 책임을 식별하고 어떤 Markdown playbook을 따라야 하는지 artifact로 남긴 뒤 `needs_human`으로 중단한다.
구현 판단과 파일 수정은 runner 코드가 아니라 Codex가 `agents/playbooks/*.md`를 읽고 수행한다.

현재 구현된 1차 capability:

- Development 책임 runner는 코드베이스 스냅샷과 감지된 endpoint, route, DDL 후보를 artifact에 남긴다.
- DDD/API/FE/API Connect/Refactoring/DB Migration runner는 앱 코드를 생성하지 않고 playbook handoff만 남긴다.
- Test Implementation Runner는 기존 프론트엔드/백엔드 테스트 명령을 찾아 실제로 실행한다.
- Infra Runner는 설정 파일을 만들지 않고 `infra-config` playbook handoff만 남긴다.

아직 구현되지 않은 부분:

- 자동 개발자처럼 앱 코드를 생성하는 runner는 의도적으로 비활성화했다.
- 반복 가능한 도구 호출로 격리할 수 없는 구현 판단은 Markdown playbook과 Codex 대화형 실행으로 처리한다.

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
- Codex handoff 또는 도구 실행으로 안전하게 처리하기 어려우면 `needs_human`으로 멈춘다.
- 실패한 run은 `harness status`와 artifact로 추적 가능해야 한다.
- 개발 실패 복구는 Dev Agent 내부 runner 또는 Codex 대화형 수정 흐름에서 처리한다.
- `harness fix-develop`은 새 복구를 수행하지 않는 deprecated 안내 명령으로만 유지한다.
- plan/dev/qa/deploy 승인 gate 없이는 다음 단계로 이동하지 않는다.
