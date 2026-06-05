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
        dev_summary = _read_first_existing(input_data.artifacts_root / input_data.task_id / "dev", ["dev-status.md", "commit-plan.md"])
        review_summary = _read_first_existing(input_data.artifacts_root / input_data.task_id / "review", ["review-report.md"])
        qa_summary = _read_first_existing(input_data.artifacts_root / input_data.task_id / "qa", ["qa-report.md", "qa-checklist.md"])
        issue_number = _issue_number_from_body(input_data.body)
        issue_type = _issue_type_from_body(input_data.body)

        now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d %H:%M:%S")
        issue_summary.write_text(
            "\n".join(
                [
                    f"# 이슈 구현 요약: {input_data.title}",
                    "",
                    f"- Task ID: `{input_data.task_id}`",
                    f"- 현재 상태: `{input_data.state}`",
                    f"- 정리 시각: {now}",
                    "",
                    "## 설계 요약",
                    _compact(plan_summary),
                    "",
                    "## 개발 요약",
                    _compact(dev_summary),
                    "",
                    "## 리뷰 요약",
                    _compact(review_summary),
                    "",
                    "## QA 요약",
                    _compact(qa_summary),
                    "",
                    "## 회고 포인트",
                    "- 다음에 같은 유형의 작업을 더 빠르게 하기 위해 남겨야 할 결정이나 규칙을 추가한다.",
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
                    f"- 상태: {input_data.state}",
                    "- 요약: 설계, 개발, 리뷰, QA 산출물을 이슈 단위로 정리했다.",
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
                    f"- 상태: {input_data.state}",
                    f"- Task ID: {input_data.task_id}",
                    f"- 이슈 번호: {issue_number or '기록 없음'}",
                    f"- 구현 타입: {issue_type}",
                    "- 분류: 개발 기록",
                    "- 한 줄 요약: 설계/개발/리뷰/QA 흐름을 완료 기록으로 정리",
                    f"- 상세: {issue_summary}",
                ]
            ),
            encoding="utf-8",
        )

        publish_result = publish_feature_record(
            title=input_data.title,
            issue_number=issue_number,
            issue_type=issue_type,
            state=input_data.state,
            summary=_compact(issue_summary.read_text(encoding="utf-8"), limit=1200),
        )
        notion_publish.write_text(
            "\n".join(
                [
                    "# Notion 발행 결과",
                    "",
                    f"- status: `{publish_result['status']}`",
                    f"- target: `feature`",
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
    summary: str,
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
            "구현 타입": _multi_select_property([issue_type]),
            "현재 staus": _multi_select_property([state]),
        },
        "children": _children_from_sections(
            [
                ("정리", summary),
                ("확인", "Human QA 승인 이후 Documentation Agent가 자동 기록했다."),
            ]
        ),
    }
    return _post_notion_page(payload)


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
                ("기능", feature),
                ("사용 방법", usage),
            ]
        ),
    }
    return _post_notion_page(payload)


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


# Notion 표에 붙이기 쉽도록 긴 문서를 앞부분 중심으로 압축한다.
def _compact(text: str, limit: int = 1600) -> str:
    normalized = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n...(요약 길이 제한으로 일부 생략)"
