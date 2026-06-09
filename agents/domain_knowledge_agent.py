from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec
from orchestrator.core.settings import settings


class DomainKnowledgeAgent:
    name = "domain_knowledge"

    # QA가 끝난 구현 결과를 Obsidian의 서비스 지식으로 정리한다.
    def run(self, input_data: AgentInput) -> AgentResult:
        vault_path = settings.obsidian_vault_path.expanduser()
        if not vault_path.exists():
            return AgentResult(
                status=AgentStatus.NEEDS_HUMAN,
                summary="Obsidian Vault 경로를 찾지 못했습니다.",
                error=f"Obsidian Vault 경로가 존재하지 않습니다: {vault_path}",
            )

        domain_dir = input_data.artifacts_root / input_data.task_id / "domain-knowledge"
        domain_dir.mkdir(parents=True, exist_ok=True)

        issue_number = _issue_number_from_body(input_data.body)
        issue_type = _issue_type_from_body(input_data.body)
        now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d %H:%M:%S")

        plan_summary = _read_first_existing(input_data.artifacts_root / input_data.task_id / "plans", ["architecture.md"])
        dev_summary = _read_first_existing(input_data.artifacts_root / input_data.task_id / "dev", ["dev-status.md", "commit-plan.md"])
        qa_summary = _read_first_existing(input_data.artifacts_root / input_data.task_id / "qa", ["qa-report.md", "qa-checklist.md"])

        entry = _domain_entry(
            title=input_data.title,
            issue_number=issue_number,
            issue_type=issue_type,
            state=input_data.state,
            recorded_at=now,
            plan_summary=plan_summary,
            dev_summary=dev_summary,
            qa_summary=qa_summary,
        )

        entry_artifact = domain_dir / "domain-knowledge-entry.md"
        result_artifact = domain_dir / "domain-knowledge-result.md"
        entry_artifact.write_text(entry, encoding="utf-8")

        implemented_features = vault_path / "agent-context" / "implemented-features.md"
        planning_context = vault_path / "agent-context" / "planning-assistant-context.md"
        domain_decisions = vault_path / "planning" / "domain-decisions.md"

        _upsert_marked_section(
            implemented_features,
            marker=_marker(issue_number, input_data.task_id),
            content=entry,
            heading="# Implemented Features",
        )
        _upsert_marked_section(
            domain_decisions,
            marker=_marker(issue_number, input_data.task_id),
            content=_decision_entry(input_data.title, issue_number, issue_type, now, plan_summary),
            heading="# Domain Decisions",
        )
        _upsert_marked_section(
            planning_context,
            marker=_marker(issue_number, input_data.task_id),
            content=_context_entry(input_data.title, issue_number, issue_type, qa_summary),
            heading="# Planning Assistant Context",
        )

        result_artifact.write_text(
            "\n".join(
                [
                    "# Domain Knowledge Agent 결과",
                    "",
                    "- status: success",
                    f"- vault: `{vault_path}`",
                    f"- implemented_features: `{implemented_features}`",
                    f"- domain_decisions: `{domain_decisions}`",
                    f"- planning_context: `{planning_context}`",
                ]
            ),
            encoding="utf-8",
        )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            summary=f"Domain Knowledge Agent가 Obsidian에 서비스 지식을 정리했습니다. issue=#{issue_number or 'unknown'}",
            artifacts=[
                ArtifactSpec("domain-knowledge-entry", entry_artifact),
                ArtifactSpec("domain-knowledge-result", result_artifact),
            ],
        )


# 구현 결과를 Obsidian에 저장할 도메인 지식 항목으로 변환한다.
def _domain_entry(
    title: str,
    issue_number: str,
    issue_type: str,
    state: str,
    recorded_at: str,
    plan_summary: str,
    dev_summary: str,
    qa_summary: str,
) -> str:
    return "\n".join(
        [
            f"## {title}",
            "",
            f"- 이슈: {_issue_link(issue_number)}",
            f"- 구현 타입: {_readable_issue_type(issue_type)}",
            f"- 상태: {state}",
            f"- 기록 시각: {recorded_at}",
            "",
            "### 서비스 지식",
            _compact(plan_summary, 700),
            "",
            "### 구현된 동작",
            _compact(dev_summary, 600),
            "",
            "### 검증된 내용",
            _compact(qa_summary, 500),
        ]
    )


# 확정된 정책과 결정사항만 planning 폴더에 짧게 남긴다.
def _decision_entry(title: str, issue_number: str, issue_type: str, recorded_at: str, plan_summary: str) -> str:
    return "\n".join(
        [
            f"## {title}",
            "",
            f"- 이슈: {_issue_link(issue_number)}",
            f"- 구현 타입: {_readable_issue_type(issue_type)}",
            f"- 결정 시각: {recorded_at}",
            "",
            "### 확정된 방향",
            _compact(plan_summary, 700),
        ]
    )


# 기획 보조 Agent가 빠르게 읽을 수 있는 압축 맥락을 만든다.
def _context_entry(title: str, issue_number: str, issue_type: str, qa_summary: str) -> str:
    return "\n".join(
        [
            f"## {title}",
            "",
            f"- 이슈: {_issue_link(issue_number)}",
            f"- 구현 타입: {_readable_issue_type(issue_type)}",
            "- 용도: 이후 기획 보조 Agent가 이미 구현된 사용자 흐름과 검증 결과를 참고한다.",
            "",
            "### 참고할 검증 결과",
            _compact(qa_summary, 500),
        ]
    )


# 이슈 번호와 task id를 기준으로 Obsidian 중복 기록 방지용 marker를 만든다.
def _marker(issue_number: str, task_id: str) -> str:
    return f"issue-{issue_number or 'unknown'}-{task_id}"


# marker로 감싼 section을 새로 쓰거나 기존 section을 교체한다.
def _upsert_marked_section(path: Path, marker: str, content: str, heading: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    start = f"<!-- harness:{marker}:start -->"
    end = f"<!-- harness:{marker}:end -->"
    section = f"{start}\n{content.strip()}\n{end}\n"

    if not path.exists():
        path.write_text(f"{heading}\n\n{section}", encoding="utf-8")
        return

    original = path.read_text(encoding="utf-8")
    if start in original and end in original:
        before = original.split(start, 1)[0]
        after = original.split(end, 1)[1]
        path.write_text(f"{before}{section}{after.lstrip()}", encoding="utf-8")
        return

    separator = "\n" if original.endswith("\n") else "\n\n"
    path.write_text(f"{original}{separator}{section}", encoding="utf-8")


# 후보 파일 중 가장 먼저 존재하는 문서 내용을 읽는다.
def _read_first_existing(directory: Path, filenames: list[str]) -> str:
    for filename in filenames:
        path = directory / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
    return "아직 산출물이 없습니다."


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


# 구현 타입 코드를 사람이 읽는 이름으로 변환한다.
def _readable_issue_type(issue_type: str) -> str:
    mapping = {
        "feFeature": "FE Feature",
        "beFeature": "BE Feature",
        "fullstackFeature": "Full Stack Feature",
        "apiConnect": "API Connect",
        "config": "Config",
        "infra": "Infra",
        "docs": "Docs",
        "bugfix": "Bugfix",
        "hotfix": "Hotfix",
    }
    return mapping.get(issue_type, issue_type or "unspecified")


# 이슈 번호를 GitHub issue 링크 Markdown으로 변환한다.
def _issue_link(issue_number: str) -> str:
    if not issue_number:
        return "기록 없음"
    return f"[#{issue_number}](https://github.com/{settings.github_owner}/{settings.github_repo}/issues/{issue_number})"


# 긴 문서를 Obsidian에 적기 좋은 길이로 압축한다.
def _compact(text: str, limit: int = 800) -> str:
    normalized = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    if not normalized:
        return "기록 없음"
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n...(요약 길이 제한으로 일부 생략)"
