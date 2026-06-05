from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec


class DocumentationAgent:
    name = "documentation"

    # 이슈의 설계/개발/QA 산출물을 Notion에 옮기기 쉬운 요약 문서로 정리한다.
    def run(self, input_data: AgentInput) -> AgentResult:
        docs_dir = input_data.artifacts_root / input_data.task_id / "documentation"
        docs_dir.mkdir(parents=True, exist_ok=True)

        issue_summary = docs_dir / "issue-summary.md"
        daily_log = docs_dir / "daily-log.md"
        notion_entry = docs_dir / "notion-entry.md"

        plan_summary = _read_first_existing(input_data.artifacts_root / input_data.task_id / "plans", ["architecture.md"])
        dev_summary = _read_first_existing(input_data.artifacts_root / input_data.task_id / "dev", ["dev-status.md", "commit-plan.md"])
        review_summary = _read_first_existing(input_data.artifacts_root / input_data.task_id / "review", ["review-report.md"])
        qa_summary = _read_first_existing(input_data.artifacts_root / input_data.task_id / "qa", ["qa-report.md", "qa-checklist.md"])

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
                    "- 분류: 개발 기록",
                    "- 한 줄 요약: 설계/개발/리뷰/QA 흐름을 완료 기록으로 정리",
                    f"- 상세: {issue_summary}",
                ]
            ),
            encoding="utf-8",
        )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            summary="Documentation Agent가 Notion 입력용 작업 기록을 생성했습니다.",
            artifacts=[
                ArtifactSpec("documentation-issue-summary", issue_summary),
                ArtifactSpec("documentation-daily-log", daily_log),
                ArtifactSpec("documentation-notion-entry", notion_entry),
            ],
        )


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
