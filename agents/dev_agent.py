import re
from pathlib import Path

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec
from orchestrator.core.settings import settings


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


def _extract_refactor_request(markdown: str) -> list[str]:
    return _extract_section(markdown, "Human Refactor Request")


def _branch_prefix(issue_type: str) -> str:
    return {
        "beFeature": "feature(BE)",
        "feFeature": "feature(FE)",
        "fullstackFeature": "feature(FS)",
        "apiConnect": "api-connect",
        "bugfix": "bugfix",
        "hotfix": "hotfix",
        "infra": "infra",
        "config": "config",
        "docs": "docs",
    }.get(issue_type, "task")


def _branch_name(issue_type: str, issue_number: str) -> str:
    number = issue_number if issue_number and issue_number != "unknown" else "no-issue"
    return f"{_branch_prefix(issue_type)}-{number}"


def _feature_name(title: str) -> str:
    cleaned = re.sub(r"\[[^\]]+\]", "", title).strip()
    return cleaned or title.strip() or "작업"


def _commit_units(issue_type: str) -> list[tuple[str, str]]:
    if issue_type == "feFeature":
        return [("화면 구현", "화면/상태/폼 구현"), ("검증", "브라우저와 빌드 검증")]
    if issue_type == "beFeature":
        return [("백엔드 구현", "도메인/usecase/API 구현"), ("검증", "테스트와 API smoke 검증")]
    if issue_type == "apiConnect":
        return [("Contract 연결", "FE 요청과 BE 응답 연결"), ("검증", "성공/실패 연동 검증")]
    if issue_type == "fullstackFeature":
        return [("백엔드 구현", "도메인/API 구현"), ("프론트엔드 구현", "화면/API client 구현"), ("통합 검증", "FE/BE 흐름 검증")]
    if issue_type in {"config", "infra"}:
        return [("설정 변경", "환경/보안/배포 설정 변경"), ("검증", "health/log/rollback 기준 확인")]
    return [("변경 구현", "요구사항 기반 최소 변경"), ("검증", "관련 테스트와 smoke 검증")]


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in text.lower() for keyword in keywords)


def _codex_playbooks(issue_type: str, title: str, body: str) -> list[str]:
    text = f"{title}\n{body}"
    if issue_type == "feFeature":
        return ["frontend-implementation"]
    if issue_type == "beFeature":
        return ["backend-kotlin-spring"]
    if issue_type == "apiConnect":
        return ["api-connect"]
    if issue_type == "fullstackFeature":
        return ["backend-kotlin-spring", "frontend-implementation", "api-connect"]
    if issue_type in {"config", "infra"}:
        return ["infra-config"]
    if issue_type == "docs":
        return ["documentation"]
    playbooks: list[str] = []
    if _contains_any(text, ["frontend", "next", "tsx", "화면", "버튼", "모달", "ui", "ux", "web"]):
        playbooks.append("frontend-implementation")
    if _contains_any(text, ["backend", "api", "spring", "kotlin", "db", "redis", "서버", "도메인"]):
        playbooks.append("backend-kotlin-spring")
    if _contains_any(text, ["연동", "contract", "request", "response", "client"]):
        playbooks.append("api-connect")
    if _contains_any(text, ["infra", "config", "환경", "docker", "railway", "github actions", "jwt"]):
        playbooks.append("infra-config")
    return playbooks or ["frontend-implementation"]


def _backend_style_lines(issue_type: str) -> list[str]:
    if issue_type not in {"beFeature", "apiConnect", "fullstackFeature", "bugfix", "hotfix"}:
        return ["- backend orchestration style skill: 이 이슈 타입에는 필수가 아닙니다."]
    return [
        "- backend orchestration style skill: required when editing Kotlin/Spring code",
        "- domain/application/port/infrastructure/bootstrap 경계를 지킨다.",
        "- 메인 서비스 메서드는 유스케이스 흐름이 보이게 작성한다.",
        "- 정책, 검증, 외부 연동, 상태 변경 책임은 이름이 명확한 책임 객체로 분리한다.",
        "- 책임 객체의 public 메서드에는 한국어 한 줄 주석을 작성한다.",
    ]


class DevAgent:
    name = "dev"

    def run(self, input_data: AgentInput) -> AgentResult:
        task_dir = input_data.artifacts_root / input_data.task_id / "dev"
        task_dir.mkdir(parents=True, exist_ok=True)
        issue_type = _extract_issue_type(input_data.body)
        issue_number = _extract_metadata_value(input_data.body, "issue_number") or "unknown"
        branch_name = _branch_name(issue_type, issue_number)
        feature_name = _feature_name(input_data.title)
        playbooks = _codex_playbooks(issue_type, input_data.title, input_data.body)
        refactor_request = _extract_refactor_request(input_data.body)

        commit_plan = task_dir / "commit-plan.md"
        commit_plan.write_text(
            "\n".join(
                [
                    "# Codex 커밋 계획",
                    "",
                    f"- issue_type: `{issue_type}`",
                    f"- issue_number: `{issue_number}`",
                    f"- recommended_branch: `{branch_name}`",
                    f"- base_branch: `{settings.development_base_branch}`",
                    f"- codex_playbooks: {', '.join(f'`agents/playbooks/{name}.md`' for name in playbooks)}",
                    "- python_implementation_layer: removed",
                    "",
                    "## 커밋 단위",
                    *[
                        f"{index}. [{feature_name}] : {message}"
                        for index, (_title, message) in enumerate(_commit_units(issue_type), start=1)
                    ],
                    "",
                    "## Backend Style",
                    *_backend_style_lines(issue_type),
                ]
            ),
            encoding="utf-8",
        )

        handoff = task_dir / "codex-implementation-request.md"
        handoff.write_text(
            "\n".join(
                [
                    "# Codex Implementation Request",
                    "",
                    f"- title: {input_data.title}",
                    f"- issue_type: `{issue_type}`",
                    f"- issue_number: `{issue_number}`",
                    f"- recommended_branch: `{branch_name}`",
                    "- source: GitHub issue + Markdown playbook",
                    "- python_implementation_layer: removed",
                    "",
                    "## Required Playbooks",
                    *[f"- `agents/playbooks/{name}.md`" for name in playbooks],
                    "",
                    "## Codex Execution",
                    "1. GitHub issue 본문과 design artifact를 읽는다.",
                    "2. 위 playbook을 기준으로 Codex가 직접 파일을 수정한다.",
                    "3. 변경 단위별로 테스트하고 커밋한다.",
                    "4. 실행한 검증, 남은 위험, 후속 작업을 artifact와 댓글에 남긴다.",
                    "",
                    *(
                        [
                            "## Human Refactor Request",
                            *refactor_request,
                            "",
                        ]
                        if refactor_request
                        else []
                    ),
                    "## Issue Body",
                    input_data.body,
                ]
            ),
            encoding="utf-8",
        )

        status = task_dir / "dev-status.md"
        status.write_text(
            "\n".join(
                [
                    "# Dev 상태",
                    "",
                    "- mode: stateless Codex handoff",
                    "- python_implementation_layer: removed",
                    f"- recommended_branch: `{branch_name}`",
                    f"- handoff: `{handoff}`",
                    "",
                    "## 다음 행동",
                    "- Codex가 handoff와 playbook을 읽고 직접 구현한다.",
                    "- 구현 후 테스트 결과와 커밋 정보를 이 디렉토리에 남긴다.",
                ]
            ),
            encoding="utf-8",
        )

        test_report = task_dir / "test-report.md"
        test_report.write_text(
            "\n".join(
                [
                    "# Dev 검증 계획",
                    "",
                    "- 자동 테스트 Python 계층은 제거되었습니다.",
                    "- Codex가 변경 범위에 맞는 테스트 명령을 직접 선택하고 실행합니다.",
                    "",
                    "## 최소 기대",
                    "- 관련 단위 테스트 또는 smoke test",
                    "- 빌드 또는 타입 체크",
                    "- 실패/미실행 사유 기록",
                ]
            ),
            encoding="utf-8",
        )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            summary=f"Python 구현 계층 없이 Codex가 직접 구현할 dev handoff를 생성했습니다: {branch_name}",
            artifacts=[
                ArtifactSpec("commit-plan", Path(commit_plan)),
                ArtifactSpec("dev-status", Path(status)),
                ArtifactSpec("codex-implementation-request", Path(handoff)),
                ArtifactSpec("test-report", Path(test_report)),
            ],
        )
