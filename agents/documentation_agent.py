import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec
from orchestrator.core.settings import settings


class DocumentationAgent:
    name = "documentation"

    # 이슈의 설계/개발/QA 산출물을 Notion에 옮기기 쉬운 요약 문서로 정리한다.
    def run(self, input_data: AgentInput) -> AgentResult:
        docs_dir = input_data.artifacts_root / input_data.task_id / "documentation"
        docs_dir.mkdir(parents=True, exist_ok=True)

        issue_summary = docs_dir / "issue-summary.md"
        daily_log = docs_dir / "daily-log.md"
        notion_entry = docs_dir / "notion-entry.md"
        notion_publish = docs_dir / "notion-publish-result.md"

        plan_summary = _read_first_existing(input_data.artifacts_root / input_data.task_id / "plans", ["architecture.md"])
        dev_summary = _read_first_existing(
            input_data.artifacts_root / input_data.task_id / "dev",
            ["manual-completion.md", "dev-status.md", "commit-plan.md"],
        )
        review_summary = _read_first_existing(input_data.artifacts_root / input_data.task_id / "review", ["review-report.md"])
        qa_summary = _read_first_existing(
            input_data.artifacts_root / input_data.task_id / "qa",
            ["manual-completion.md", "qa-report.md", "qa-checklist.md"],
        )
        effective_state = _effective_state(input_data.state, dev_summary, qa_summary)
        issue_number = _issue_number_from_body(input_data.body)
        issue_type = _issue_type_from_body(input_data.body)
        human_sections = build_human_sections(
            title=input_data.title,
            issue_number=issue_number,
            issue_type=issue_type,
            state=effective_state,
            plan_summary=plan_summary,
            dev_summary=dev_summary,
            review_summary=review_summary,
            qa_summary=qa_summary,
        )

        now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d %H:%M:%S")
        issue_summary.write_text(
            "\n".join(
                [
                    f"# 이슈 구현 요약: {input_data.title}",
                    "",
                    f"- Task ID: `{input_data.task_id}`",
                    f"- 현재 상태: `{effective_state}`",
                    f"- 정리 시각: {now}",
                    "",
                    *_markdown_sections(human_sections),
                ]
            ),
            encoding="utf-8",
        )

        daily_log.write_text(
            "\n".join(
                [
                    f"# 작업 일지 - {now[:10]}",
                    "",
                    f"- 작업: {input_data.title}",
                    f"- 상태: {effective_state}",
                    f"- 요약: {_section_text(human_sections, '한눈에 보기')}",
                    f"- 상세 문서: `{issue_summary}`",
                ]
            ),
            encoding="utf-8",
        )

        notion_entry.write_text(
            "\n".join(
                [
                    "# Notion 입력용 요약",
                    "",
                    f"- 날짜: {now[:10]}",
                    f"- 작업명: {input_data.title}",
                    f"- 상태: {effective_state}",
                    f"- Task ID: {input_data.task_id}",
                    f"- 이슈 번호: {issue_number or '기록 없음'}",
                    f"- 구현 타입: {issue_type}",
                    "- 분류: 개발 기록",
                    f"- 한 줄 요약: {_section_text(human_sections, '한눈에 보기')}",
                    f"- 상세: {issue_summary}",
                ]
            ),
            encoding="utf-8",
        )

        publish_result = publish_feature_record(
            title=input_data.title,
            issue_number=issue_number,
            issue_type=issue_type,
            state=effective_state,
            sections=human_sections,
        )
        notion_publish.write_text(
            "\n".join(
                [
                    "# Notion 발행 결과",
                    "",
                    f"- status: `{publish_result['status']}`",
                    "- target: `feature`",
                    f"- url: {publish_result.get('url') or '없음'}",
                    f"- reason: {publish_result.get('reason') or '없음'}",
                ]
            ),
            encoding="utf-8",
        )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            summary=f"Documentation Agent가 구현 기록을 정리했습니다. Notion status={publish_result['status']}",
            artifacts=[
                ArtifactSpec("documentation-issue-summary", issue_summary),
                ArtifactSpec("documentation-daily-log", daily_log),
                ArtifactSpec("documentation-notion-entry", notion_entry),
                ArtifactSpec("documentation-notion-publish-result", notion_publish),
            ],
        )


# 구현 완료 이슈를 MyMentalCare 구현 기록 Notion 표에 발행한다.
def publish_feature_record(
    title: str,
    issue_number: str,
    issue_type: str,
    state: str,
    sections: list[tuple[str, str]] | None = None,
) -> dict[str, str]:
    if not settings.notion_api_token:
        return {"status": "skipped", "reason": "NOTION_API_TOKEN이 설정되지 않았습니다."}
    if not settings.notion_feature_data_source_id:
        return {"status": "skipped", "reason": "NOTION_FEATURE_DATA_SOURCE_ID가 설정되지 않았습니다."}

    payload = {
        "parent": {
            "type": "data_source_id",
            "data_source_id": settings.notion_feature_data_source_id,
        },
        "properties": {
            "이슈 제목 ": _title_property(title),
            "이슈 번호 ": _rich_text_property(issue_number or "기록 없음"),
            "구현 타입": _multi_select_property([_notion_issue_type(issue_type)]),
            "현재 staus": _multi_select_property([_notion_state(state)]),
        },
        "children": _children_from_sections(
            (sections or [("한눈에 보기", _feature_description(title, issue_type, ""))])
            + [
                ("동작 원리", _feature_operation_principle(issue_type)),
                ("이슈 티켓", _issue_ticket(issue_number)),
            ]
        ),
    }
    return _post_notion_page(payload)


# 사람이 Notion에서 바로 읽을 수 있는 이슈 설명 섹션을 만든다.
def build_human_sections(
    title: str,
    issue_number: str,
    issue_type: str,
    state: str,
    plan_summary: str,
    dev_summary: str,
    review_summary: str,
    qa_summary: str,
) -> list[tuple[str, str]]:
    commits = _commit_evidence(dev_summary) or _commit_evidence(qa_summary)
    follow_ups = _follow_up_points(plan_summary, qa_summary)
    return [
        ("한눈에 보기", _one_line_summary(title, issue_type, state)),
        ("사용자가 체감하는 변화", _user_facing_change(title, plan_summary)),
        ("구현 범위", _implementation_scope(title, plan_summary, dev_summary)),
        ("검증 상태", _verification_summary(qa_summary, review_summary)),
        ("후속 확인", follow_ups),
        ("구현 근거", commits or "관련 커밋 근거가 산출물에 명시되어 있지 않다."),
    ]


# 하네스 세팅 변경을 History Notion 표에 발행한다.
def publish_harness_history_record(
    title: str,
    category: str,
    feature: str,
    usage: str,
) -> dict[str, str]:
    if not settings.notion_api_token:
        return {"status": "skipped", "reason": "NOTION_API_TOKEN이 설정되지 않았습니다."}
    if not settings.notion_harness_history_data_source_id:
        return {"status": "skipped", "reason": "NOTION_HARNESS_HISTORY_DATA_SOURCE_ID가 설정되지 않았습니다."}

    payload = {
        "parent": {
            "type": "data_source_id",
            "data_source_id": settings.notion_harness_history_data_source_id,
        },
        "properties": {
            "이름": _title_property(title),
            "다중 선택": _multi_select_property([category]),
            "기능 ": _rich_text_property(feature),
            "사용 방법 ": _rich_text_property(usage),
        },
        "children": _children_from_sections(
            [
                ("기능 설명", feature),
                ("동작 원리", _harness_operation_principle(category)),
                ("사용 방법", usage),
            ]
        ),
    }
    return _post_notion_page(payload)


# Markdown 섹션을 issue-summary.md에 쓸 line 목록으로 변환한다.
def _markdown_sections(sections: list[tuple[str, str]]) -> list[str]:
    lines: list[str] = []
    for heading, content in sections:
        lines.extend([f"## {heading}", content.strip() or "기록 없음", ""])
    return lines


def _section_text(sections: list[tuple[str, str]], heading: str) -> str:
    for section_heading, content in sections:
        if section_heading == heading:
            return _single_line(content, limit=260)
    return "기록 없음"


def _one_line_summary(title: str, issue_type: str, state: str) -> str:
    clean_title = _clean_title(title)
    type_name = _notion_issue_type(issue_type)
    if state == "Ready To Deploy":
        return f"{clean_title} 작업은 배포 가능한 상태로 정리되었고, 작업자가 기능 목적과 검증 상태를 바로 확인할 수 있다. ({type_name})"
    return f"{clean_title} 작업은 현재 `{state}` 상태이며, 작업자가 남은 검증/후속 판단을 확인해야 한다. ({type_name})"


def _user_facing_change(title: str, plan_summary: str) -> str:
    candidate = _extract_section(plan_summary, ["## 사용자 경험", "## User Experience", "## 목표", "## Goal"])
    if candidate:
        return _human_compact(candidate, limit=700)
    return f"사용자는 `{_clean_title(title)}` 범위의 변경을 서비스 화면이나 API 흐름에서 체감한다."


def _implementation_scope(title: str, plan_summary: str, dev_summary: str) -> str:
    plan_scope = _extract_section(
        plan_summary,
        ["## 작업 범위", "## 구현 범위", "## Change Scope", "## 백엔드 구현", "## 프론트엔드 구현", "## API Contract"],
    )
    dev_notes = _notes_only(dev_summary)
    parts = []
    if plan_scope:
        parts.append(_human_compact(plan_scope, limit=650))
    if dev_notes and "Manual DEV Completion" not in dev_summary:
        parts.append(_human_compact(dev_notes, limit=650))
    if not parts:
        parts.append(f"`{_clean_title(title)}` 구현 범위는 이슈 본문과 개발 산출물 기준으로 정리한다.")
    return "\n\n".join(parts)


def _verification_summary(qa_summary: str, review_summary: str) -> str:
    if "Manual QA Completion" in qa_summary:
        return "자동 QA 원문은 남아 있지 않다. stage/main 병합 이력 기준으로 구현 완료를 사후 정리했으며, 배포 전 정밀 확인이 필요하면 핵심 사용자 흐름만 별도 회귀 검증한다."
    if "result: pass" in qa_summary or "통과" in qa_summary:
        return _human_compact(qa_summary, limit=700)
    if "아직 산출물이 없습니다" in qa_summary:
        if "아직 산출물이 없습니다" not in review_summary:
            return "별도 QA 산출물은 없지만 리뷰 산출물이 존재한다. 작업자가 배포 전 수동 회귀 검증 필요 여부를 확인한다."
        return "QA/리뷰 산출물이 아직 없다. 이 페이지는 구현 기록이며, 배포 전 재검증 필요 여부를 확인해야 한다."
    return _human_compact(qa_summary, limit=700)


def _follow_up_points(plan_summary: str, qa_summary: str) -> str:
    joined = "\n".join([plan_summary, qa_summary])
    points: list[str] = []
    if "정책 결정 필요" in joined or "확정 필요" in joined:
        points.append("- 정책이 남아 있는 항목은 별도 이슈로 분리한다.")
    if "계정" in joined and "충돌" in joined:
        points.append("- 카카오/기존 계정 충돌 정책은 자동 병합하지 말고 명시적으로 결정한다.")
    if "알림" in joined and ("준비중" in joined or "비활성" in joined):
        points.append("- 알림 발송은 목적, 빈도, 시간대, 거부/재동의 정책 확정 전까지 활성화하지 않는다.")
    if "정밀 회귀 검증" in joined or "재검증" in joined:
        points.append("- 사후 정리된 이슈는 필요 시 핵심 사용자 흐름만 재검증한다.")
    if not points:
        points.append("- 현재 문서 기준으로 별도 후속 결정은 없다.")
    return "\n".join(points)


def _commit_evidence(text: str) -> str:
    lines = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("- `") and "|" in stripped:
            lines.append(stripped)
    return "\n".join(lines[:8])


def _notes_only(text: str) -> str:
    if "## Notes" not in text:
        return ""
    return text.split("## Notes", 1)[1].strip()


def _extract_section(text: str, headings: list[str]) -> str:
    lines = text.splitlines()
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped not in headings:
            continue
        collected = []
        for next_line in lines[index + 1 :]:
            next_stripped = next_line.strip()
            if next_stripped.startswith("## ") and collected:
                break
            if next_stripped:
                collected.append(next_line.rstrip())
        return "\n".join(collected).strip()
    return ""


def _human_compact(text: str, limit: int = 700) -> str:
    cleaned = []
    skip_prefixes = (
        "# Backfill",
        "# Manual",
        "- task_id:",
        "- source:",
        "- branch evidence:",
        "- recorded_at:",
        "- original_harness_state:",
        "- title:",
        "- issue:",
    )
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(prefix) for prefix in skip_prefixes):
            continue
        if "Documentation Agent" in stripped or "Domain Knowledge Agent" in stripped:
            continue
        if "누락된 사후 정리" in stripped or "사후 문서화" in stripped:
            continue
        if stripped.startswith("```"):
            break
        cleaned.append(line)
    normalized = "\n".join(cleaned).strip()
    if not normalized:
        return "기록 없음"
    if len(normalized) <= limit:
        return normalized
    clipped = normalized[:limit].rstrip()
    if "\n" in clipped:
        clipped = clipped.rsplit("\n", 1)[0].rstrip()
    return clipped


def _single_line(text: str, limit: int = 260) -> str:
    line = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if len(line) <= limit:
        return line
    return line[:limit].rstrip()


def _clean_title(title: str) -> str:
    cleaned = title
    for prefix in ("[FE]", "[BE]", "[FS]", "[API]", "[Config]", "[Bugfix]", "[BUG]", "[Infra]", "[Docs]"):
        cleaned = cleaned.replace(prefix, "")
    return " ".join(cleaned.split()).strip() or title


# 하네스 내부 구현 타입을 Notion 구현 타입 옵션명으로 변환한다.
def _notion_issue_type(issue_type: str) -> str:
    mapping = {
        "feFeature": "FE Feature",
        "beFeature": "BE Feature",
        "fullstackFeature": "Full Stack Feature",
        "apiConnect": "API Connect",
        "config": "Config",
    }
    return mapping.get(issue_type, issue_type or "unspecified")


# 하네스 내부 상태명을 Notion 현재 상태 옵션명으로 변환한다.
def _notion_state(state: str) -> str:
    mapping = {
        "Ready To Deploy": "Stage",
        "Done": "Done",
        "Human QA": "Human QA",
        "System QA": "System QA",
        "QA Review": "Human QA",
    }
    return mapping.get(state, state or "Stage")


# 서비스 구현 기록의 기능 설명을 2~3줄로 생성한다.
def _feature_description(title: str, issue_type: str, summary: str) -> str:
    type_name = _notion_issue_type(issue_type)
    compact_summary = _compact(summary, limit=420)
    return "\n".join(
        [
            f"{title} 작업을 통해 MyMentalCare 서비스의 {type_name} 범위를 보강했다.",
            "사용자가 서비스 흐름 안에서 더 자연스럽게 기능을 사용할 수 있도록 설계, 개발, 검증 결과를 정리했다.",
            compact_summary,
        ]
    )


# 구현 타입별로 서비스 기능의 동작 원리를 설명한다.
def _feature_operation_principle(issue_type: str) -> str:
    principles = {
        "feFeature": "프론트엔드 화면과 상태가 사용자의 입력과 클릭에 반응한다. 사용자는 화면에서 기능을 발견하고, 필요한 정보를 입력한 뒤 결과 메시지를 확인한다.",
        "beFeature": "백엔드는 사용자의 요청을 도메인 규칙에 따라 검증하고 처리한다. 성공하면 결과를 반환하고, 실패하면 사용자가 이해할 수 있는 한국어 메시지를 반환한다.",
        "apiConnect": "프론트엔드가 사용자의 행동을 API 요청으로 변환하고, 백엔드 응답을 다시 화면 상태와 사용자 메시지로 바꾼다.",
        "fullstackFeature": "화면, API, 데이터 처리가 하나의 사용자 흐름으로 연결된다. 사용자는 화면에서 기능을 수행하고, 서버는 도메인 규칙과 저장 결과를 기준으로 응답한다.",
        "config": "서비스 실행과 인증/보안 정책에 필요한 설정을 추가한다. 설정은 로컬 실행, 테스트, 이후 기능 구현의 기반으로 사용된다.",
    }
    return principles.get(
        issue_type,
        "사용자 목표를 기준으로 화면, 서버, 데이터 흐름이 연결된다. 구현 결과는 Human QA 이후 서비스 기록으로 남긴다.",
    )


# 이슈 번호를 GitHub issue 링크 Markdown으로 변환한다.
def _issue_ticket(issue_number: str) -> str:
    if not issue_number:
        return "GitHub 이슈 번호를 찾지 못했습니다."
    return f"[#{issue_number} 이슈 보기](https://github.com/{settings.github_owner}/{settings.github_repo}/issues/{issue_number})"


# 하네스 기록의 동작 원리를 카테고리별로 짧게 생성한다.
def _harness_operation_principle(category: str) -> str:
    principles = {
        "스킬 생성": "반복되는 판단 기준을 Codex가 읽을 수 있는 skill 문서로 분리해 재사용한다.",
        "스킬 강화": "기존 skill의 규칙을 더 구체화해 다음 구현과 리뷰에서 같은 기준을 적용한다.",
        "에이전트 생성": "새 책임을 가진 Agent를 추가해 설계, 개발, 검증, 기록 흐름을 분리한다.",
        "에이전트 보강": "기존 Agent의 질문, 실행, 검증, 기록 방식을 개선해 사람이 확인하기 쉬운 결과를 만든다.",
        "하네스 강화": "GitHub, Notion, Discord, 로컬 저장소 흐름을 연결해 작업 기록과 실행 안정성을 높인다.",
        "기획 변경": "서비스와 하네스의 운영 방향을 조정하고 다음 작업 기준으로 남긴다.",
    }
    return principles.get(category, "하네스가 사람이 통제하는 개발 흐름을 더 안정적으로 지원하도록 동작 방식을 보강한다.")


# Notion Create Page API로 page를 생성하고 결과를 표준 dict로 반환한다.
def _post_notion_page(payload: dict) -> dict[str, str]:
    request = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.notion_api_token}",
            "Content-Type": "application/json",
            "Notion-Version": settings.notion_version,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
            return {
                "status": "published",
                "url": response_payload.get("url", ""),
                "reason": "",
            }
    except urllib.error.HTTPError as exc:
        return {"status": "failed", "reason": exc.read().decode("utf-8")}
    except Exception as exc:  # noqa: BLE001 - Notion 발행 실패는 문서 생성 자체를 막지 않는다.
        return {"status": "failed", "reason": str(exc)}


# Notion title property payload를 만든다.
def _title_property(value: str) -> dict:
    return {"title": [{"type": "text", "text": {"content": _truncate(value, 1800)}}]}


# Notion rich_text property payload를 만든다.
def _rich_text_property(value: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": _truncate(value, 1800)}}]}


# Notion multi_select property payload를 만든다.
def _multi_select_property(values: list[str]) -> dict:
    return {"multi_select": [{"name": value} for value in values if value]}


# Markdown 섹션 목록을 Notion block children으로 변환한다.
def _children_from_sections(sections: list[tuple[str, str]]) -> list[dict]:
    children: list[dict] = []
    for heading, content in sections:
        children.append(
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": heading}}]},
            }
        )
        for chunk in _chunks(content, 1800):
            children.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
                }
            )
    return children


# 긴 텍스트를 Notion rich_text 제한에 맞춰 나눈다.
def _chunks(value: str, size: int) -> list[str]:
    text = value.strip() or "기록 없음"
    return [text[index : index + size] for index in range(0, len(text), size)]


# Notion property에 들어갈 긴 문자열을 안전하게 자른다.
def _truncate(value: str, limit: int) -> str:
    text = value.strip() or "기록 없음"
    return text[:limit]


# 하네스 metadata에서 GitHub issue number를 추출한다.
def _issue_number_from_body(body: str) -> str:
    for line in _metadata_lines(body):
        if line.startswith("- issue_number:"):
            return line.removeprefix("- issue_number:").strip()
    return ""


# 하네스 metadata에서 구현 타입 label을 추출한다.
def _issue_type_from_body(body: str) -> str:
    for line in _metadata_lines(body):
        if not line.startswith("- labels:"):
            continue
        labels = [item.strip() for item in line.removeprefix("- labels:").split(",")]
        for label in labels:
            if label.startswith("type: "):
                return label.removeprefix("type: ").strip()
    return "unspecified"


# 하네스 metadata 섹션의 line 목록을 반환한다.
def _metadata_lines(body: str) -> list[str]:
    if "## Harness Metadata" not in body:
        return []
    metadata = body.split("## Harness Metadata", 1)[1]
    return [line.strip() for line in metadata.splitlines() if line.strip()]


# 후보 파일 중 먼저 존재하는 문서 내용을 읽는다.
def _read_first_existing(directory: Path, filenames: list[str]) -> str:
    for filename in filenames:
        path = directory / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
    return "아직 산출물이 없습니다."


# 사후 정리된 이슈는 DB kanban 상태가 Backlog여도 문서상 구현 완료 상태로 해석한다.
def _effective_state(state: str, dev_summary: str, qa_summary: str) -> str:
    if "Manual QA Completion" in qa_summary:
        return "Ready To Deploy"
    if "Manual DEV Completion" in dev_summary and state == "Backlog":
        return "Ready To Deploy"
    return state


# Notion 표에 붙이기 쉽도록 긴 문서를 앞부분 중심으로 압축한다.
def _compact(text: str, limit: int = 1600) -> str:
    normalized = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n...(요약 길이 제한으로 일부 생략)"
