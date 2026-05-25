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


def _profile_for_issue_type(issue_type: str) -> dict[str, list[str] | str]:
    profiles: dict[str, dict[str, list[str] | str]] = {
        "feFeature": {
            "flow_title": "Frontend Feature Flow",
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
        "bugfix": {
            "flow_title": "Bugfix Investigation Flow",
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
                    *(goal or ["StudyHub에 회원가입 진입 흐름과 회원가입 화면을 추가한다."]),
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
                    *_format_bullets(scope, ["회원가입 진입 링크, `/signup` 페이지, 폼 UI를 추가한다."]),
                    "",
                    f"## Proposed {flow_title}",
                    "```text",
                    "Issue intake",
                    "-> plan review",
                    "-> implementation",
                    "-> system QA",
                    "-> human QA",
                    "```",
                    "",
                    "## Expected Files",
                    *_format_bullets(inferred_files, []),
                    "",
                    "## Implementation Steps",
                    *_format_bullets(implementation_steps, []),
                    "",
                    "## Acceptance Criteria",
                    *_format_bullets(acceptance, ["web build passes", "sign-up form is visible"]),
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

        flow = task_dir / "flow.md"
        flow.write_text(
            "\n".join(
                [
                    f"# {flow_title}",
                    "",
                    "```mermaid",
                    "flowchart TD",
                    "    A[Issue requirements] --> B[Plan review]",
                    "    B --> C[Implementation scope]",
                    "    C --> D[Tests and build verification]",
                    "    D --> E[System QA]",
                    "    E --> F[Human QA]",
                    "```",
                ]
            ),
            encoding="utf-8",
        )

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
            summary=f"{issue_type} plan generated with implementation steps and edge cases.",
            artifacts=[
                ArtifactSpec("architecture-doc", Path(architecture)),
                ArtifactSpec("flow", Path(flow)),
                ArtifactSpec("edge-case-checklist", Path(checklist)),
            ],
        )
