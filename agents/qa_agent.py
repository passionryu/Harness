from pathlib import Path

from agents.agent_spec import AgentSpecError, load_agent_spec, render_agent_spec_context
from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec
from agents.qa_plan import build_qa_plan, qa_plan_coverage_lines, render_qa_plan_markdown
from orchestrator.core.settings import settings


DEFAULT_HUMAN_QA_CHECKLIST = [
    "이번 이슈의 핵심 사용자/운영 흐름이 처음부터 끝까지 동작하는가",
    "성공 케이스와 실패/엣지 케이스가 모두 확인되었는가",
    "모바일/데스크톱 또는 API/DB/로그 등 영향 영역이 깨지지 않는가",
    "사용자에게 보이는 문구가 안전하고 이해 가능한 한국어인가",
    "검증 결과와 남은 위험이 GitHub 댓글 또는 artifact에 남아 있는가",
]

FE_HUMAN_QA_CHECKLIST = [
    "브라우저에서 대상 화면의 핵심 진입점이 보이는가",
    "클릭/입력/제출 흐름이 페이지 이동과 상태 변화까지 의도대로 이어지는가",
    "성공/실패 상태의 메시지가 명확하게 보이는가",
    "모바일/데스크톱 화면에서 폼 레이아웃이 깨지거나 텍스트가 겹치지 않는가",
    "정신 건강 서비스에 맞는 따뜻하고 안정적인 디자인 톤이 유지되는가",
]

BE_HUMAN_QA_CHECKLIST = [
    "대상 API의 해피 케이스가 의도한 2xx 응답을 반환하는가",
    "주요 엣지 케이스가 의도한 오류 응답을 반환하는가",
    "DB 저장/조회 상태가 API 응답과 일치하는가",
    "민감정보가 응답이나 로그에 노출되지 않는가",
    "Swagger/OpenAPI 설명이 실제 동작과 일치하는가",
]

INFRA_HUMAN_QA_CHECKLIST = [
    "변경된 설정 파일과 운영 문서가 대상 저장소에 반영되어 있는가",
    "문서에 적힌 로컬 실행 명령 또는 검증 명령이 실제로 성공하는가",
    "포트, 볼륨, 환경변수 충돌 없이 구성 요소가 시작되는가",
    "health, status, logs 명령으로 정상 상태를 확인할 수 있는가",
    "secret, token, password 같은 민감정보가 설정 파일이나 로그에 노출되지 않는가",
]


def _extract_section(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    collected: list[str] = []
    in_section = False
    section_level: int | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[level:].strip()
            if in_section and section_level is not None and level <= section_level:
                break
            if level in {2, 3} and title == heading:
                in_section = True
                section_level = level
                continue
        if in_section and stripped:
            collected.append(stripped)
    return collected


def _extract_metadata_value(markdown: str, key: str) -> str | None:
    for line in _extract_section(markdown, "Harness Metadata"):
        prefix = f"- {key}:"
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def _extract_issue_type(markdown: str) -> str:
    labels = _extract_metadata_value(markdown, "labels") or ""
    for label in [item.strip() for item in labels.split(",")]:
        if label.startswith("type: "):
            return label.removeprefix("type: ").strip()
    return "unspecified"


def _issue_number(markdown: str) -> str:
    return _extract_metadata_value(markdown, "issue_number") or "unknown"


def _fallback_human_qa_checklist(issue_type: str, title: str, body: str) -> list[str]:
    if issue_type in {"feFeature", "bugfix"} or any(keyword in f"{title}\n{body}".lower() for keyword in ["ui", "ux", "화면", "버튼", "모달"]):
        return FE_HUMAN_QA_CHECKLIST
    if issue_type in {"beFeature", "apiConnect", "fullstackFeature"}:
        return BE_HUMAN_QA_CHECKLIST
    if issue_type in {"infra", "config"}:
        return INFRA_HUMAN_QA_CHECKLIST
    return DEFAULT_HUMAN_QA_CHECKLIST


def _infra_human_qa_checklist(title: str, body: str) -> list[str]:
    return INFRA_HUMAN_QA_CHECKLIST


class QAAgent:
    name = "qa"

    def run(self, input_data: AgentInput) -> AgentResult:
        task_dir = input_data.artifacts_root / input_data.task_id / "qa"
        task_dir.mkdir(parents=True, exist_ok=True)
        issue_type = _extract_issue_type(input_data.body)
        issue_number = _issue_number(input_data.body)
        human_qa_items = _fallback_human_qa_checklist(issue_type, input_data.title, input_data.body)
        qa_request = _extract_section(input_data.body, "Human QA Request")
        qa_plan = build_qa_plan(input_data.title, input_data.body, human_qa_items)

        try:
            agent_spec_lines = render_agent_spec_context(load_agent_spec("qa"))
        except AgentSpecError as exc:
            agent_spec_lines = ["## QA Agent Markdown Spec", "", f"- spec_error: {exc}"]

        qa_plan_lines = render_qa_plan_markdown(qa_plan)
        codex_handoff = task_dir / "codex-qa-handoff.md"
        codex_handoff.write_text(
            "\n".join(
                [
                    "# Codex QA Handoff",
                    "",
                    f"- issue_type: `{issue_type}`",
                    f"- issue_number: `{issue_number}`",
                    "- python_runner: removed",
                    "- playbook: `agents/playbooks/qa-verification.md`",
                    "",
                    "## Codex Execution",
                    "1. 기획/설계 artifact와 실제 변경 diff를 읽는다.",
                    "2. 이슈에 맞는 성공/실패/회귀 검증 목록을 직접 작성한다.",
                    "3. 필요한 브라우저, API, DB, 로그 검증을 직접 수행한다.",
                    "4. 스크린샷은 기능 흐름의 시작부터 끝까지 의미 있는 장면만 남긴다.",
                    "5. 각 스크린샷에는 제목과 1~3줄 설명을 붙인다.",
                    "",
                    "## QA 요청사항",
                    *(qa_request or ["추가 QA 요청사항이 없습니다."]),
                ]
            ),
            encoding="utf-8",
        )

        checklist = task_dir / "qa-checklist.md"
        checklist.write_text(
            "\n".join(
                [
                    "# QA 체크리스트",
                    "",
                    *agent_spec_lines,
                    *qa_plan_lines,
                    "## QA Plan 커버리지",
                    *qa_plan_coverage_lines(qa_plan),
                    "",
                    "## Human QA 체크리스트",
                    *[f"- [ ] {item}" for item in human_qa_items],
                ]
            ),
            encoding="utf-8",
        )

        report = task_dir / "qa-report.md"
        report.write_text(
            "\n".join(
                [
                    "# System QA Report",
                    "",
                    f"- issue_type: `{issue_type}`",
                    f"- issue_number: `{issue_number}`",
                    "- result: `handoff`",
                    "- python_runner: removed",
                    "- actual_verifier: Codex",
                    f"- frontend_url: `{settings.frontend_base_url}`",
                    f"- api_url: `{settings.target_api_base_url}`",
                    f"- swagger_url: `{settings.target_swagger_url}`",
                    "",
                    "## QA 요청사항",
                    *(qa_request or ["추가 QA 요청사항이 없습니다."]),
                    "",
                    *qa_plan_lines,
                    "## Human QA 체크리스트",
                    *[f"- [ ] {item}" for item in human_qa_items],
                    "",
                    "## 다음 행동",
                    "- Codex가 `agents/playbooks/qa-verification.md`를 읽고 실제 검증을 수행한다.",
                    "- 자동 확인하지 않은 항목을 pass로 표시하지 않는다.",
                    "- 사람이 볼 보고서는 기능 흐름과 실패 케이스를 직관적으로 설명해야 한다.",
                ]
            ),
            encoding="utf-8",
        )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            summary="Runner 없이 Codex가 직접 검증할 QA handoff를 생성했습니다.",
            artifacts=[
                ArtifactSpec("qa-plan", Path(codex_handoff)),
                ArtifactSpec("qa-report", Path(report)),
                ArtifactSpec("qa-checklist", Path(checklist)),
            ],
        )
