# 백엔드 Runner 구현 규칙

Kotlin/Spring Boot 백엔드 Runner는 DDD와 헥사고날 아키텍처 경계를 지키는 코드를 생성해야 한다. 이 문서는 모든 백엔드 구현의 기본 규칙이다.

## Controller와 DTO

- Controller는 얇게 유지한다.
- Controller는 요청 데이터를 받고, 하나의 application service/usecase를 호출하고, 응답을 반환하는 정도만 담당한다.
- request/response `data class`를 controller 파일 안에 정의하지 않는다.
- HTTP request/response DTO는 `{domain}/web/request`, `{domain}/web/response` 하위의 별도 파일로 둔다.
- request DTO는 명시적인 mapping method를 통해 application command로 변환한다.
- 비즈니스 규칙, persistence 호출, 비밀번호 해싱, 정책 검증을 controller에 넣지 않는다.

권장 package 구조:

```text
bootstrap/{domain}/web/
├── {Domain}Controller.kt
├── {Domain}ExceptionHandler.kt
├── {Domain}ResponseMapper.kt
├── request/
│   └── {Usecase}Payload.kt
└── response/
    └── {Usecase}Response.kt
```

`web`은 HTTP inbound adapter를 의미한다. 화면 구현이 아니라 Spring MVC endpoint,
HTTP request/response DTO, HTTP exception mapping, application port 호출 경계를 담당한다.

## 서버 디렉토리 관리 기준

백엔드 서버는 도메인 중심 Vertical Slice 구조를 기본으로 한다. 기능이 늘어날수록
같은 도메인의 usecase, request/response, policy, reader/recorder, port를 가까운 위치에
두어 작업자가 변경 범위를 빠르게 파악할 수 있어야 한다.

권장 구조:

```text
modules/domain/{domain}
├── {DomainModel}.kt
└── {DomainPolicyValue}.kt

modules/application/{domain}
├── usecase/
│   └── {Usecase}Service.kt
├── request/
│   └── {Usecase}Request.kt
├── response/
│   └── {Usecase}Response.kt
├── policy/
│   └── {Domain}PolicyChecker.kt
├── reader/
│   └── {Domain}Reader.kt
├── recorder/
│   └── {Domain}Recorder.kt
└── port/
    └── {RequiredPort}.kt

modules/bootstrap/{app}/{domain}
├── web/
│   ├── {Domain}Controller.kt
│   ├── {Domain}ExceptionHandler.kt
│   ├── {Domain}ResponseMapper.kt
│   ├── request/
│   └── response/
└── adapter/
    └── {external-system}/

modules/infrastructure/persistence/{domain}
├── {Domain}Entity.kt
├── {Domain}PersistenceAdapter.kt
└── Jpa{Domain}Repository.kt
```

디렉토리별 책임:

- `domain/{domain}`: Spring, JPA, HTTP에 의존하지 않는 domain model과 domain rule.
- `application/{domain}/usecase`: application service와 usecase orchestration.
- `application/{domain}/request`: usecase 입력 command/query.
- `application/{domain}/response`: usecase 결과 DTO.
- `application/{domain}/policy`: 비즈니스 정책 판단과 검증.
- `application/{domain}/reader`: usecase에 필요한 조회 책임.
- `application/{domain}/recorder`: 상태 변경, 이력 저장, 이벤트 기록 책임.
- `application/{domain}/port`: 해당 도메인 usecase가 필요로 하는 inbound/outbound interface.
- `bootstrap/{app}/{domain}/web`: HTTP inbound adapter.
- `bootstrap/{app}/{domain}/adapter/{external-system}`: OpenAI, Redis, OAuth, notification 같은 outbound adapter.
- `infrastructure/persistence/{domain}`: DB persistence adapter, JPA entity, Spring Data repository.

도메인별 port가 명확할 때는 `application/{domain}/port`에 둔다. 여러 도메인에서 공유하는
진짜 공통 port만 `application/port`에 둘 수 있다. 단순히 위치를 고민하기 어렵다는 이유로
전역 `application/port`를 기본값으로 사용하지 않는다.

외부 시스템별 adapter는 한 패키지에 섞지 않는다. 예를 들어 AI 마음 대화 도메인은 다음과
같이 분리한다.

```text
bootstrap/mymentalcare/aichat/adapter/openai/
bootstrap/mymentalcare/aichat/adapter/redis/
```

서비스 정책에 가까운 코드는 외부 adapter에 두지 않는다. 예를 들어 챗봇 응답 정책,
프롬프트 정책, 안전 응답 정책은 OpenAI 호출 기술이 아니라 서비스 정책이면
`application/{domain}/policy`로 이동한다.

## Swagger/OpenAPI 문서화

- 모든 API endpoint에는 `@Operation`을 작성한다.
- `summary`에는 기능 이름을 짧게 작성한다.
- `description`에는 사용자가 이해할 수 있는 간단한 API 설명을 작성한다.
- Swagger 설명은 한국어로 작성한다.
- `@ApiResponse`, DTO field `@Schema` 등 상세 문서화는 기본 생성하지 않는다. 명시적으로 요청된 경우에만 추가한다.
- 단순히 기능 이름만 반복하지 말고, API가 언제 쓰이고 어떤 결과를 반환하는지 한두 문장으로 설명한다.

## DDD와 헥사고날 경계

- `domain`은 Spring, JPA, web API에 의존하지 않는 domain model과 domain rule을 둔다.
- `application/{domain}`은 usecase service, command/result, port, policy checker, validator, orchestration flow를 둔다.
- `application/{domain}/port`는 해당 도메인 usecase가 필요로 하는 interface를 둔다.
- `infrastructure/persistence/{domain}`은 application port를 구현하는 DB adapter를 둔다.
- `bootstrap/{app}/{domain}/web`은 HTTP controller, request/response DTO, exception handler, framework wiring을 둔다.
- `bootstrap/{app}/{domain}/adapter/{external-system}`은 DB가 아닌 외부 시스템 adapter를 둔다.

Runner는 속도를 이유로 이 경계를 생략하지 않는다. 경계를 지키며 구현할 수 없다면 낮은 품질의 코드를 만들지 말고 `needs_human`으로 중단한다.

## 파일 생성 규칙

- 기본적으로 하나의 의미 있는 public class/data class는 하나의 파일에 둔다.
- 파일명은 primary class 이름과 맞춘다.
- 기존 프로젝트가 강하게 사용 중인 관례가 아니면 `Util`, `Helper`, `Manager`, `CommonService`를 피한다.
- 기존 프로젝트에 강한 local pattern이 있는 경우가 아니면 새 백엔드 코드에서 `companion object`를 피한다.
- 비즈니스 동작을 static-like factory에 숨기기보다 책임이 명확한 class를 선호한다.

## Application Service 규칙

- Application service는 usecase 흐름을 orchestration한다.
- 메인 메서드는 비즈니스 순서가 읽히게 작성한다.
- service를 다른 private method로 한 줄 위임하는 구조로 축소하지 않는다.
- 정책, 검증, 상태 변경, persistence boundary, 외부 연동 책임은 이름이 명확한 collaborator로 분리한다.
- 책임 객체의 public method에는 규칙이 존재하는 이유를 설명하는 한국어 한 줄 주석을 작성한다.

## 오류와 로깅

- 사용자에게 반환하는 API 오류는 한국어이며, 안전하고, 다음 행동을 이해할 수 있어야 한다.
- 내부 구현 상세, stack trace, SQL 상세, class name, 외부 시스템 원문 오류를 사용자에게 노출하지 않는다.
- 내부 예외 메시지와 로그는 한국어를 우선한다.
- 내부 로그는 CS 처리와 디버깅에 충분한 정보를 포함한다.
- 실패 처리에는 `usecase-orchestration-style`의 로깅 정책을 따른다.
- `rules/localization.md`도 함께 따른다.
