from pathlib import Path

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec


def _extract_section(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    collected: list[str] = []
    in_section = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_section:
                break
            in_section = stripped.removeprefix("## ").strip() == heading
            continue
        if stripped.startswith("### "):
            if in_section:
                break
            in_section = stripped.removeprefix("### ").strip() == heading
            continue
        if in_section and stripped:
            collected.append(stripped)

    return collected


def _extract_bullets(markdown: str, heading: str) -> list[str]:
    return [
        line.removeprefix("-").strip()
        for line in _extract_section(markdown, heading)
        if line.startswith("-")
    ]


def _format_bullets(items: list[str], fallback: list[str]) -> list[str]:
    source = items or fallback
    return [f"- {item}" for item in source]


def _extract_issue_type(markdown: str) -> str:
    metadata = _extract_section(markdown, "Harness Metadata")
    for line in metadata:
        if not line.startswith("- labels:"):
            continue
        labels = [item.strip() for item in line.removeprefix("- labels:").split(",")]
        for label in labels:
            if label.startswith("type: "):
                return label.removeprefix("type: ").strip()
    return "unspecified"


# 이슈 타입별 Plan 산출물의 기본 구조와 질문을 결정한다.
def _profile_for_issue_type(issue_type: str) -> dict[str, list[str] | str]:
    profiles: dict[str, dict[str, list[str] | str]] = {
        "feFeature": {
            "flow_title": "Frontend Feature Flow",
            "summary_fallback": "사용자가 화면에서 목표 기능을 수행할 수 있도록 프론트엔드 UI와 흐름을 구현한다.",
            "scope_fallback": ["화면 진입점, route, page, component, validation UI를 추가하거나 수정한다."],
            "acceptance_fallback": ["사용자가 목표 화면으로 이동할 수 있다.", "프론트엔드 검증이 통과한다."],
            "expected_files": [
                "apps/web 하위 route, page, component 파일",
                "packages/shared 하위 공통 타입 또는 API contract",
                "docs/product 또는 docs/api 하위 사용자 흐름 문서",
            ],
            "steps": [
                "현재 화면 진입점과 기존 컴포넌트 구조를 확인한다.",
                "사용자 흐름에 맞는 route, page, component 변경 범위를 확정한다.",
                "폼, 상태, validation, loading/error UI를 구현한다.",
                "API가 없으면 mock-safe submit 구조를 두고 contract TODO를 남긴다.",
                "반응형 화면과 프론트엔드 빌드/린트를 검증한다.",
            ],
            "open_questions": [
                "최종 UX flow와 화면 진입 위치",
                "필요한 API endpoint와 request/response contract",
                "validation 정책과 에러 메시지",
                "모바일 화면에서의 우선순위",
            ],
            "edge_cases": [
                "필수 입력값 누락",
                "잘못된 입력 형식",
                "중복 submit",
                "API 실패 또는 지연",
                "모바일 레이아웃 overflow",
            ],
        },
        "beFeature": {
            "flow_title": "Backend Feature Flow",
            "summary_fallback": "API 요청을 받아 도메인 규칙에 따라 데이터를 처리하고 저장하는 백엔드 기능을 구현한다.",
            "scope_fallback": ["controller, DTO, usecase, domain, repository, persistence, migration을 추가하거나 수정한다."],
            "acceptance_fallback": ["API가 정상 응답한다.", "서버 테스트와 빌드가 통과한다."],
            "expected_files": [
                "apps/server/modules/domain 하위 도메인 모델",
                "apps/server/modules/application 하위 usecase",
                "apps/server/modules/infrastructure 하위 adapter/persistence",
                "apps/server/modules/bootstrap 하위 API endpoint",
            ],
            "steps": [
                "도메인 규칙과 usecase 책임을 분리한다.",
                "API request/response와 application command/query를 정의한다.",
                "트랜잭션 경계와 repository port를 확정한다.",
                "필요한 DB migration, index, rollback 영향을 점검한다.",
                "unit/integration/smoke test를 작성하고 빌드를 검증한다.",
            ],
            "open_questions": [
                "도메인 정책과 예외 케이스",
                "transaction boundary",
                "DDL/migration 필요 여부",
                "외부 시스템 연동 여부",
            ],
            "edge_cases": [
                "중복 요청",
                "동시성 충돌",
                "존재하지 않는 리소스",
                "권한 없는 접근",
                "트랜잭션 rollback",
            ],
        },
        "apiConnect": {
            "flow_title": "API Connect Flow",
            "summary_fallback": "프론트엔드와 백엔드 API contract를 연결하고 요청/응답/오류 흐름을 검증한다.",
            "scope_fallback": ["FE 호출 지점, API client, BE endpoint, shared contract를 연결한다."],
            "acceptance_fallback": ["FE에서 API 호출이 성공한다.", "오류 응답이 사용자에게 자연스럽게 처리된다."],
            "expected_files": [
                "apps/web 하위 API client 또는 server action",
                "apps/server 하위 controller/usecase/DTO",
                "packages/shared 하위 request/response schema",
            ],
            "steps": [
                "프론트엔드 호출 지점과 백엔드 endpoint를 매핑한다.",
                "request/response/error contract를 확정한다.",
                "loading, success, error 상태 처리를 구현한다.",
                "contract mismatch와 validation 실패 처리를 검증한다.",
                "FE/BE smoke test를 수행한다.",
            ],
            "open_questions": [
                "최종 endpoint path와 method",
                "인증/인가 필요 여부",
                "에러 코드와 메시지 형식",
                "공통 schema 위치",
            ],
            "edge_cases": [
                "network timeout",
                "4xx validation error",
                "5xx server error",
                "stale response",
                "동일 요청 반복",
            ],
        },
        "fullstackFeature": {
            "flow_title": "Fullstack Feature Flow",
            "summary_fallback": "사용자 화면 경험, API contract, 백엔드 처리, 프론트엔드 연동까지 하나의 기능 흐름으로 구현한다.",
            "scope_fallback": [
                "화면 UX, API contract, Kotlin/Spring Boot backend, Next.js frontend, FE/BE 연동, smoke test를 함께 정의한다."
            ],
            "acceptance_fallback": [
                "사용자가 화면에서 기능을 정상 수행할 수 있다.",
                "API contract와 실제 FE/BE 구현이 일치한다.",
                "백엔드 테스트와 프론트엔드 smoke test가 통과한다.",
            ],
            "expected_files": [
                "docs/api 하위 API contract 문서",
                "apps/server 하위 controller/usecase/domain/persistence/test 파일",
                "apps/web 하위 route/component/API client/test 파일",
            ],
            "steps": [
                "사용자 시나리오와 화면 제공 방식을 먼저 정리한다.",
                "프론트-백엔드 API contract를 확정한다.",
                "백엔드 도메인/usecase/API/persistence와 테스트를 먼저 구현한다.",
                "프론트엔드 화면, 상태, 검증, API client를 구현한다.",
                "FE submit 흐름과 BE endpoint를 연결하고 smoke test를 수행한다.",
            ],
            "open_questions": [
                "최종 사용자 플로우와 성공 후 이동 위치",
                "API endpoint, request/response/error contract",
                "인증/인가 필요 여부",
                "DB 변경과 migration 필요 여부",
                "모바일 화면에서 우선적으로 보장할 UX",
            ],
            "edge_cases": [
                "FE validation과 BE validation 불일치",
                "중복 submit",
                "네트워크 timeout 또는 5xx",
                "4xx 에러 메시지 표시",
                "DB 저장 성공 후 FE 상태 반영 실패",
            ],
        },
        "bugfix": {
            "flow_title": "Bugfix Investigation Flow",
            "summary_fallback": "재현 가능한 문제를 기준으로 원인을 좁히고 최소 수정과 회귀 테스트를 추가한다.",
            "scope_fallback": ["문제 재현 경로와 직접 관련된 최소 코드 범위를 수정한다."],
            "acceptance_fallback": ["보고된 문제가 재현되지 않는다.", "회귀 테스트가 통과한다."],
            "expected_files": ["재현 경로와 관련된 최소 코드 범위", "regression test 파일"],
            "steps": [
                "재현 조건과 기대 동작을 고정한다.",
                "원인 후보를 좁히고 최소 수정 범위를 정한다.",
                "regression test를 먼저 추가하거나 보강한다.",
                "수정 후 기존 동작에 영향이 없는지 검증한다.",
            ],
            "open_questions": ["재현 가능한 입력값", "영향받는 사용자/환경", "릴리즈 우선순위"],
            "edge_cases": ["부분 재현", "환경별 차이", "기존 데이터와의 호환성", "회귀 가능성"],
        },
    }
    default_profile = {
        "flow_title": "Task Flow",
        "summary_fallback": "이슈 요구사항을 기준으로 변경 범위를 정하고 구현 가능한 계획을 만든다.",
        "scope_fallback": ["이슈 본문 기준 변경 대상 파일"],
        "acceptance_fallback": ["요구사항이 충족된다.", "관련 검증이 통과한다."],
        "expected_files": ["이슈 본문 기준 변경 대상 파일"],
        "steps": [
            "요구사항과 완료 기준을 확인한다.",
            "변경 범위를 작게 나누고 영향 범위를 점검한다.",
            "구현 후 관련 테스트와 빌드를 검증한다.",
        ],
        "open_questions": ["정확한 변경 범위", "검증 기준", "배포 또는 문서화 필요 여부"],
        "edge_cases": ["누락된 요구사항", "기존 기능 회귀", "환경별 차이"],
    }
    return profiles.get(issue_type, default_profile)


# 이슈 타입에 맞는 기본 Mermaid 시퀀스 다이어그램을 만든다.
def _sequence_diagram_for_issue_type(issue_type: str) -> list[str]:
    diagrams = {
        "feFeature": [
            "sequenceDiagram",
            "    actor User",
            "    participant Page as Next.js Page",
            "    participant Component as UI Component",
            "    participant Validator as Validation",
            "    User->>Page: 화면 진입",
            "    Page->>Component: 폼/컴포넌트 렌더링",
            "    User->>Component: 입력 및 제출",
            "    Component->>Validator: 입력값 검증",
            "    Validator-->>Component: 검증 결과",
            "    Component-->>User: 성공/오류 피드백",
        ],
        "beFeature": [
            "sequenceDiagram",
            "    actor Client",
            "    participant Controller",
            "    participant UseCase",
            "    participant Domain",
            "    participant Repository",
            "    participant DB",
            "    Client->>Controller: API 요청",
            "    Controller->>UseCase: Command 전달",
            "    UseCase->>Domain: 도메인 규칙 검증",
            "    UseCase->>Repository: 저장/조회 요청",
            "    Repository->>DB: persistence 처리",
            "    DB-->>Repository: 결과 반환",
            "    Repository-->>UseCase: domain result",
            "    UseCase-->>Controller: response model",
            "    Controller-->>Client: API 응답",
        ],
        "apiConnect": [
            "sequenceDiagram",
            "    actor User",
            "    participant UI as Frontend UI",
            "    participant Client as API Client",
            "    participant API as Backend API",
            "    participant DB",
            "    User->>UI: 액션 수행",
            "    UI->>Client: request 생성",
            "    Client->>API: HTTP 요청",
            "    API->>DB: 필요 데이터 처리",
            "    DB-->>API: 처리 결과",
            "    API-->>Client: response/error",
            "    Client-->>UI: 상태 반영",
            "    UI-->>User: 성공/오류 피드백",
        ],
        "fullstackFeature": [
            "sequenceDiagram",
            "    actor User",
            "    participant UI as Next.js UI",
            "    participant Client as API Client",
            "    participant Controller as Spring Controller",
            "    participant UseCase as Application UseCase",
            "    participant Domain",
            "    participant DB",
            "    User->>UI: 화면 진입 및 입력",
            "    UI->>Client: request 생성",
            "    Client->>Controller: HTTP 요청",
            "    Controller->>UseCase: command 전달",
            "    UseCase->>Domain: 도메인 규칙 검증",
            "    UseCase->>DB: 저장/조회",
            "    DB-->>UseCase: 처리 결과",
            "    UseCase-->>Controller: response model",
            "    Controller-->>Client: response/error",
            "    Client-->>UI: 상태 반영",
            "    UI-->>User: 성공/오류 피드백",
        ],
        "bugfix": [
            "sequenceDiagram",
            "    actor User",
            "    participant Broken as 기존 문제 경로",
            "    participant Fix as 수정 코드",
            "    participant Test as Regression Test",
            "    User->>Broken: 문제 재현 입력",
            "    Broken-->>User: 잘못된 결과",
            "    Fix->>Test: 회귀 케이스 실행",
            "    Test-->>Fix: 기대 동작 검증",
        ],
    }
    return diagrams.get(
        issue_type,
        [
            "sequenceDiagram",
            "    actor User",
            "    participant Harness",
            "    participant Code",
            "    User->>Harness: 요구사항 전달",
            "    Harness->>Code: 변경 범위 분석",
            "    Code-->>Harness: 검증 결과",
            "    Harness-->>User: 계획 보고",
        ],
    )


# 이슈 타입에 맞는 기본 Mermaid 플로우 차트를 만든다.
def _flow_chart_for_issue_type(issue_type: str) -> list[str]:
    charts = {
        "feFeature": [
            "flowchart TD",
            "    A[화면 진입] --> B[UI 렌더링]",
            "    B --> C[사용자 입력]",
            "    C --> D{입력값 유효?}",
            "    D -- 아니오 --> E[검증 메시지 표시]",
            "    D -- 예 --> F[submit 처리]",
            "    F --> G[성공/오류 피드백]",
        ],
        "beFeature": [
            "flowchart TD",
            "    A[API 요청] --> B[Request validation]",
            "    B --> C{유효한 요청?}",
            "    C -- 아니오 --> D[400 오류 응답]",
            "    C -- 예 --> E[UseCase 실행]",
            "    E --> F[도메인 규칙 검증]",
            "    F --> G{중복/정책 위반?}",
            "    G -- 예 --> H[409 또는 정책 오류]",
            "    G -- 아니오 --> I[저장 및 커밋]",
            "    I --> J[성공 응답]",
        ],
        "apiConnect": [
            "flowchart TD",
            "    A[사용자 액션] --> B[FE request 생성]",
            "    B --> C[BE API 호출]",
            "    C --> D{응답 상태}",
            "    D -- 2xx --> E[성공 UI 반영]",
            "    D -- 4xx --> F[검증/권한 오류 표시]",
            "    D -- 5xx/timeout --> G[재시도 또는 실패 안내]",
        ],
        "fullstackFeature": [
            "flowchart TD",
            "    A[사용자 시나리오 정의] --> B[API Contract 확정]",
            "    B --> C[백엔드 도메인/UseCase 구현]",
            "    C --> D[백엔드 API/DB 연결]",
            "    D --> E[프론트 화면/상태 구현]",
            "    E --> F[FE API client 연동]",
            "    F --> G{통합 검증 통과?}",
            "    G -- 아니오 --> H[BE/FE contract 재조정]",
            "    H --> F",
            "    G -- 예 --> I[System QA]",
        ],
        "bugfix": [
            "flowchart TD",
            "    A[문제 재현] --> B[원인 후보 분석]",
            "    B --> C[회귀 테스트 추가]",
            "    C --> D[최소 수정]",
            "    D --> E{테스트 통과?}",
            "    E -- 아니오 --> B",
            "    E -- 예 --> F[수정 완료]",
        ],
    }
    return charts.get(
        issue_type,
        [
            "flowchart TD",
            "    A[Issue requirements] --> B[Plan review]",
            "    B --> C[Implementation scope]",
            "    C --> D[Tests and build verification]",
            "    D --> E[System QA]",
            "    E --> F[Human QA]",
        ],
    )


class PlanAgent:
    name = "plan"

    def run(self, input_data: AgentInput) -> AgentResult:
        task_dir = input_data.artifacts_root / input_data.task_id / "plans"
        task_dir.mkdir(parents=True, exist_ok=True)

        goal = _extract_section(input_data.body, "목표")
        scope = _extract_bullets(input_data.body, "작업 범위")
        acceptance = _extract_bullets(input_data.body, "완료 기준")
        replan_request = _extract_section(input_data.body, "Human Replan Request")
        issue_type = _extract_issue_type(input_data.body)
        profile = _profile_for_issue_type(issue_type)

        inferred_files = list(profile["expected_files"])
        implementation_steps = list(profile["steps"])
        open_questions = list(profile["open_questions"])
        edge_cases = list(profile["edge_cases"])
        flow_title = str(profile["flow_title"])
        summary_fallback = [str(profile["summary_fallback"])]
        scope_fallback = list(profile["scope_fallback"])
        acceptance_fallback = list(profile["acceptance_fallback"])
        sequence_diagram = _sequence_diagram_for_issue_type(issue_type)
        flow_chart = _flow_chart_for_issue_type(issue_type)

        architecture = task_dir / "architecture.md"
        architecture.write_text(
            "\n".join(
                [
                    f"# Architecture Plan: {input_data.title}",
                    "",
                    "## Issue Type",
                    issue_type,
                    "",
                    "## Goal",
                    *(goal or summary_fallback),
                    "",
                    *(
                        [
                            "## Human Replan Request",
                            *replan_request,
                            "",
                        ]
                        if replan_request
                        else []
                    ),
                    "## Change Scope",
                    *_format_bullets(scope, scope_fallback),
                    "",
                    f"## Proposed {flow_title}",
                    "```mermaid",
                    *flow_chart,
                    "```",
                    "",
                    "## Expected Files",
                    *_format_bullets(inferred_files, []),
                    "",
                    "## Implementation Steps",
                    *_format_bullets(implementation_steps, []),
                    "",
                    "## Acceptance Criteria",
                    *_format_bullets(acceptance, acceptance_fallback),
                    "",
                    "## Open Questions",
                    *_format_bullets(open_questions, []),
                    "",
                    "## Human Gate",
                    "Review open questions before moving this issue into implementation.",
                ]
            ),
            encoding="utf-8",
        )

        sequence = task_dir / "sequence-diagram.md"
        sequence.write_text(
            "\n".join(
                [
                    f"# {flow_title} Sequence Diagram",
                    "",
                    "```mermaid",
                    *sequence_diagram,
                    "```",
                ]
            ),
            encoding="utf-8",
        )

        flow = task_dir / "flow.md"
        flow_content = "\n".join(
            [
                f"# {flow_title}",
                "",
                "```mermaid",
                *flow_chart,
                "```",
            ]
        )
        flow.write_text(
            flow_content,
            encoding="utf-8",
        )
        flow_chart_file = task_dir / "flow-chart.md"
        flow_chart_file.write_text(flow_content, encoding="utf-8")

        checklist = task_dir / "edge-case-checklist.md"
        checklist.write_text(
            "\n".join(
                [
                    "# Edge Case Checklist",
                    "",
                    *_format_bullets(edge_cases, []),
                ]
            ),
            encoding="utf-8",
        )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            summary=f"{issue_type} Plan이 구현 순서와 엣지 케이스를 포함해 생성되었습니다.",
            artifacts=[
                ArtifactSpec("architecture-doc", Path(architecture)),
                ArtifactSpec("sequence-diagram", Path(sequence)),
                ArtifactSpec("flow", Path(flow)),
                ArtifactSpec("flow-chart", Path(flow_chart_file)),
                ArtifactSpec("edge-case-checklist", Path(checklist)),
            ],
        )
