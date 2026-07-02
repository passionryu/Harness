from dataclasses import dataclass


@dataclass(frozen=True)
class RunnerDefinition:
    name: str
    responsibility: str
    current_capability: str


@dataclass(frozen=True)
class WorkUnit:
    runner_name: str
    objective: str
    required_output: str


PRODUCT_PLANNER_RUNNERS = [
    RunnerDefinition("Domain Analyzer", "도메인 개념과 책임 경계를 분석한다.", "계획 산출물에 도메인 후보를 기록한다."),
    RunnerDefinition("Requirement Clarifier", "요구사항의 빈칸과 결정이 필요한 항목을 찾는다.", "미결정 사항과 질문을 기록한다."),
    RunnerDefinition("Risk Detector", "구현 전에 실패 가능성과 영향 범위를 탐지한다.", "risk-register.md를 생성한다."),
    RunnerDefinition("Work Unit Decomposer", "요구사항을 실행 가능한 책임 단위로 분해한다.", "work-units.md를 생성한다."),
    RunnerDefinition("Acceptance Criteria Writer", "사람과 시스템이 검증할 완료 기준을 정리한다.", "검증 기준을 댓글과 artifact에 기록한다."),
]

DEVELOPMENT_RUNNERS = [
    RunnerDefinition("DDD Modeling Runner", "도메인 모델, 정책, 유스케이스 흐름 책임을 식별한다.", "Codex backend playbook handoff artifact를 생성한다."),
    RunnerDefinition("DB Migration Runner", "스키마 변경, 인덱스, nullable, unique 정책 책임을 식별한다.", "명시된 DDL과 backend playbook handoff artifact를 생성한다."),
    RunnerDefinition("API Implementation Runner", "API endpoint, request/response, application 연결 책임을 식별한다.", "Codex backend playbook handoff artifact를 생성한다."),
    RunnerDefinition("Frontend Implementation Runner", "화면, 상태, 폼, 사용자 메시지 책임을 식별한다.", "Codex frontend playbook handoff artifact를 생성한다."),
    RunnerDefinition("API Connect Runner", "프론트엔드 요청과 백엔드 contract 연결 책임을 식별한다.", "Codex API connect playbook handoff artifact를 생성한다."),
    RunnerDefinition("Event Flow Runner", "비동기 이벤트, 실시간 흐름, 상태 전이 책임을 식별한다.", "Codex backend playbook handoff artifact를 생성한다."),
    RunnerDefinition("Refactoring Runner", "사람이 요청한 구조 개선과 책임 분리 범위를 식별한다.", "Codex playbook handoff artifact를 생성한다."),
    RunnerDefinition("Test Implementation Runner", "단위, 통합, smoke 테스트 명령을 실행한다.", "반복 가능한 테스트 명령 실행과 결과 수집을 수행한다."),
]

QA_RUNNERS = [
    RunnerDefinition("Integration Test Runner", "서비스 경계 간 통합 테스트를 실행한다.", "기존 QA 검증과 연결한다."),
    RunnerDefinition("Curl Scenario Runner", "실제 API curl 시나리오를 실행한다.", "BE QA에서 일부 지원한다."),
    RunnerDefinition("Browser Scenario Runner", "브라우저에서 사용자 흐름을 검증한다.", "Playwright로 로그인/화면/채팅 흐름과 콘솔 에러를 검증한다."),
    RunnerDefinition("DB State Validator", "DB 저장 결과와 정합성을 검증한다.", "BE QA에서 일부 지원한다."),
    RunnerDefinition("Concurrency Test Runner", "동시성 충돌과 race condition을 검증한다.", "아직 needs_human 중심이다."),
    RunnerDefinition("Idempotency Validator", "반복 요청과 멱등성을 검증한다.", "아직 needs_human 중심이다."),
    RunnerDefinition("Security Boundary Validator", "인증/인가 경계를 검증한다.", "config QA에서 일부 지원한다."),
    RunnerDefinition("Regression Detector", "기존 기능 회귀를 탐지한다.", "기존 smoke/test 재실행으로 일부 지원한다."),
]

HUMAN_QA_SUPPORT_RUNNERS = [
    RunnerDefinition("Human Checklist Writer", "사람이 직접 확인할 체크리스트를 작성한다.", "Human QA 댓글 생성에 사용한다."),
    RunnerDefinition("QA Notification Runner", "Discord/Google Chat 등으로 QA 요청을 보낸다.", "Discord 알림을 지원한다."),
    RunnerDefinition("Manual Verification Guide Runner", "확인 URL, Swagger, curl 기준을 정리한다.", "Human QA 댓글 생성에 사용한다."),
    RunnerDefinition("Approval Recorder", "사람의 승인 기록을 남긴다.", "approval endpoint로 지원한다."),
]


# 러너 정의 목록을 제목이 있는 Markdown 섹션으로 렌더링한다.
def render_runner_definitions(title: str, runners: list[RunnerDefinition]) -> list[str]:
    lines: list[str] = []
    lines.extend([f"## {title}", ""])
    lines.extend(
        [
            f"- {runner.name}: {runner.responsibility} 현재 능력: {runner.current_capability}"
            for runner in runners
        ]
    )
    lines.append("")
    return lines


# 하네스에 등록된 AI 조직과 각 러너의 현재 능력을 Markdown으로 렌더링한다.
def render_ai_organization_catalog() -> list[str]:
    sections = [
        ("Product Planner Agent", PRODUCT_PLANNER_RUNNERS),
        ("Development Agent", DEVELOPMENT_RUNNERS),
        ("QA Agent", QA_RUNNERS),
        ("Human QA Support", HUMAN_QA_SUPPORT_RUNNERS),
    ]
    lines: list[str] = []
    for title, runners in sections:
        lines.extend(render_runner_definitions(title, runners))
    return lines


# 이슈 타입에 따라 기본 work unit을 책임 러너 단위로 분해한다.
def work_units_for_issue_type(issue_type: str) -> list[WorkUnit]:
    if issue_type == "feFeature":
        return [
            WorkUnit("Frontend Implementation Runner", "사용자 화면과 입력 흐름 책임 식별", "frontend playbook handoff"),
            WorkUnit("Test Implementation Runner", "프론트엔드 smoke 또는 단위 테스트 명령 실행", "테스트 명령과 결과"),
        ]
    if issue_type == "beFeature":
        return [
            WorkUnit("DDD Modeling Runner", "도메인 모델과 정책 흐름 책임 식별", "backend playbook handoff"),
            WorkUnit("DB Migration Runner", "필요한 DB 변경 책임 식별", "DDL 요약과 backend playbook handoff"),
            WorkUnit("API Implementation Runner", "API endpoint와 request/response 책임 식별", "endpoint 요약과 backend playbook handoff"),
            WorkUnit("Test Implementation Runner", "도메인/API 테스트 명령 실행", "Gradle 테스트 결과"),
        ]
    if issue_type == "apiConnect":
        return [
            WorkUnit("API Connect Runner", "FE/BE contract 연결 책임 식별", "api-connect playbook handoff"),
            WorkUnit("Curl Scenario Runner", "실제 API 호출 시나리오 검증", "curl 결과"),
            WorkUnit("Regression Detector", "기존 회원가입/로그인 등 주요 흐름 회귀 확인", "회귀 검증 결과"),
        ]
    if issue_type == "fullstackFeature":
        return [
            WorkUnit("DDD Modeling Runner", "도메인 모델과 정책 흐름 책임 식별", "backend playbook handoff"),
            WorkUnit("DB Migration Runner", "DB schema와 제약 조건 책임 식별", "DDL 요약과 backend playbook handoff"),
            WorkUnit("API Implementation Runner", "백엔드 API contract와 endpoint 책임 식별", "endpoint 요약과 backend playbook handoff"),
            WorkUnit("Frontend Implementation Runner", "사용자 화면과 상태 책임 식별", "frontend playbook handoff"),
            WorkUnit("API Connect Runner", "프론트 요청과 백엔드 응답 연결 책임 식별", "api-connect playbook handoff"),
            WorkUnit("Test Implementation Runner", "FE/BE 검증 명령 실행", "테스트 명령과 결과"),
        ]
    if issue_type in {"config", "infra"}:
        return [
            WorkUnit("Dependency/Config Fix Runner", "설정/의존성 변경 범위 확인", "infra-config playbook handoff"),
            WorkUnit("Security Boundary Validator", "보안 경계와 헬스체크 검증", "검증 결과"),
        ]
    return [
        WorkUnit("Requirement Clarifier", "요구사항을 구현 가능한 작업으로 명확화", "질문과 결정 사항"),
        WorkUnit("Risk Detector", "Codex handoff와 수동 판단 지점을 탐지", "risk-register.md"),
    ]


# work unit 목록을 Markdown bullet로 렌더링한다.
def render_work_units(issue_type: str) -> list[str]:
    return [
        f"- {unit.runner_name}: {unit.objective} -> {unit.required_output}"
        for unit in work_units_for_issue_type(issue_type)
    ]
