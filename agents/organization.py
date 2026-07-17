from dataclasses import dataclass


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    responsibility: str
    markdown_source: str


@dataclass(frozen=True)
class WorkUnit:
    name: str
    objective: str
    required_output: str


AGENT_CATALOG = [
    AgentDefinition("Planning Assistant Agent", "기획이 확정되기 전 사용자와 요구사항을 정리한다.", "agents/specs/planning_assistant.md"),
    AgentDefinition("Design Agent", "확정된 요구사항을 개발 가능한 설계와 QA 기준으로 정리한다.", "agents/specs/design.md"),
    AgentDefinition("Dev Agent", "Codex가 직접 구현할 playbook과 커밋 계획을 준비한다.", "agents/specs/dev.md"),
    AgentDefinition("Review Agent", "Codex 구현 결과의 구조, 위험, 누락을 검토한다.", "agents/specs/review.md"),
    AgentDefinition("QA Agent", "Codex가 직접 검증할 QA 계획과 보고서 기준을 준비한다.", "agents/specs/qa.md"),
    AgentDefinition("Documentation Agent", "작업 결과를 Notion/문서용 기록으로 정리한다.", "agents/specs/documentation.md"),
    AgentDefinition("Domain Knowledge Agent", "서비스 지식과 정책 결정을 Obsidian용 지식으로 정리한다.", "agents/specs/domain_knowledge.md"),
]


def render_agent_definitions(title: str, agents: list[AgentDefinition]) -> list[str]:
    lines = [f"## {title}", ""]
    lines.extend(
        f"- {agent.name}: {agent.responsibility} 기준 문서: `{agent.markdown_source}`"
        for agent in agents
    )
    lines.append("")
    return lines


def render_ai_organization_catalog() -> list[str]:
    return render_agent_definitions("Markdown Agent Catalog", AGENT_CATALOG)


def work_units_for_issue_type(issue_type: str) -> list[WorkUnit]:
    if issue_type == "feFeature":
        return [
            WorkUnit("Frontend Codex Work", "사용자 화면과 입력 흐름 구현", "변경 파일, 스크린샷, 검증 결과"),
            WorkUnit("QA Codex Work", "브라우저 성공/실패 흐름 검증", "QA report와 Human QA checklist"),
        ]
    if issue_type == "beFeature":
        return [
            WorkUnit("Backend Codex Work", "도메인/usecase/API 구현", "변경 파일, 테스트 결과, API smoke evidence"),
            WorkUnit("QA Codex Work", "API 성공/실패/회귀 검증", "QA report와 Human QA checklist"),
        ]
    if issue_type == "apiConnect":
        return [
            WorkUnit("API Connect Codex Work", "FE request와 BE response 연결", "contract 검증 결과"),
            WorkUnit("QA Codex Work", "성공/실패 연동 검증", "QA report와 Human QA checklist"),
        ]
    if issue_type == "fullstackFeature":
        return [
            WorkUnit("Backend Codex Work", "백엔드 도메인/API 구현", "backend 변경과 테스트 결과"),
            WorkUnit("Frontend Codex Work", "프론트 화면/API client 구현", "frontend 변경과 브라우저 검증"),
            WorkUnit("Integration QA Codex Work", "전체 사용자 흐름 검증", "통합 QA report"),
        ]
    if issue_type in {"config", "infra"}:
        return [
            WorkUnit("Infra Codex Work", "설정/의존성/운영 변경", "설정 diff, health/log 검증, rollback note"),
        ]
    return [
        WorkUnit("Codex Work", "요구사항을 코드와 문서에 반영", "변경 파일과 검증 결과"),
        WorkUnit("QA Codex Work", "완료 기준 검증", "QA report"),
    ]


def render_work_units(issue_type: str) -> list[str]:
    return [
        f"- {unit.name}: {unit.objective} -> {unit.required_output}"
        for unit in work_units_for_issue_type(issue_type)
    ]
