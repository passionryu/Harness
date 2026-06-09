from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec
from orchestrator.core.settings import settings


class PlanningAssistantAgent:
    name = "planning_assistant"

    # Obsidian의 서비스 지식과 리서치 자료를 읽고 다음 기획 후보와 질문을 만든다.
    def run(self, input_data: AgentInput) -> AgentResult:
        vault_path = settings.obsidian_vault_path.expanduser()
        if not vault_path.exists():
            return AgentResult(
                status=AgentStatus.NEEDS_HUMAN,
                summary="Obsidian Vault 경로를 찾지 못했습니다.",
                error=f"Obsidian Vault 경로가 존재하지 않습니다: {vault_path}",
            )

        planning_dir = input_data.artifacts_root / input_data.task_id / "planning-assistant"
        planning_dir.mkdir(parents=True, exist_ok=True)

        topic = _topic_from_body(input_data.body)
        context = _collect_vault_context(vault_path)
        report = _build_planning_report(topic, input_data.body, context)

        report_artifact = planning_dir / "planning-assistant-report.md"
        issue_draft_artifact = planning_dir / "issue-draft.md"
        report_artifact.write_text(report, encoding="utf-8")
        issue_draft_artifact.write_text(_extract_issue_draft(report), encoding="utf-8")

        suggestions_path = vault_path / "planning" / "planning-assistant-suggestions.md"
        _append_suggestion(suggestions_path, report)

        return AgentResult(
            status=AgentStatus.SUCCESS,
            summary=f"Planning Assistant Agent가 기획 후보와 질문을 정리했습니다. topic={topic or '일반 기획'}",
            artifacts=[
                ArtifactSpec("planning-assistant-report", report_artifact),
                ArtifactSpec("planning-assistant-issue-draft", issue_draft_artifact),
            ],
        )


# CLI에서 전달한 topic을 AgentInput body에서 추출한다.
def _topic_from_body(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("topic:"):
            return line.removeprefix("topic:").strip()
    return ""


# Obsidian Vault에서 기획 보조에 필요한 문서만 짧게 수집한다.
def _collect_vault_context(vault_path: Path) -> dict[str, str]:
    files = {
        "서비스 맥락": vault_path / "agent-context" / "planning-assistant-context.md",
        "구현된 기능": vault_path / "agent-context" / "implemented-features.md",
        "사용자 문제": vault_path / "planning" / "user-problems.md",
        "기능 아이디어": vault_path / "planning" / "feature-ideas.md",
        "로드맵 메모": vault_path / "planning" / "roadmap-notes.md",
        "도메인 결정": vault_path / "planning" / "domain-decisions.md",
        "제품 사례": vault_path / "references" / "product-examples.md",
        "리서치": vault_path / "research" / "mental-care-apps.md",
    }
    return {name: _read_text(path) for name, path in files.items()}


# 파일이 있으면 읽고 없으면 비어 있는 맥락으로 처리한다.
def _read_text(path: Path) -> str:
    if not path.exists():
        return "기록 없음"
    return path.read_text(encoding="utf-8")


# 수집한 맥락을 바탕으로 사람이 승인하기 전 기획 보고서를 만든다.
def _build_planning_report(topic: str, request_body: str, context: dict[str, str]) -> str:
    now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d %H:%M:%S")
    focus = topic or "다음 기능 후보 탐색"
    implemented = _compact(context.get("구현된 기능", ""), 900)
    user_problems = _compact(context.get("사용자 문제", ""), 700)
    ideas = _compact(context.get("기능 아이디어", ""), 700)
    research = _compact(context.get("리서치", ""), 700)

    return "\n".join(
        [
            "# Planning Assistant Report",
            "",
            f"- 주제: {focus}",
            f"- 작성 시각: {now}",
            "",
            "## 참고한 서비스 맥락",
            implemented,
            "",
            "## 관찰한 사용자 문제",
            user_problems,
            "",
            "## 다음 기능 후보",
            *_feature_candidates(focus, ideas, research),
            "",
            "## 먼저 확인할 질문",
            *_planning_questions(focus, request_body),
            "",
            "## 위험 요소",
            *_risk_items(focus),
            "",
            "## GitHub Issue 초안",
            *_issue_draft(focus),
            "",
            "## 확정/미확정 구분",
            "- 확정: 이 보고서는 기획 후보와 질문을 제안한다.",
            "- 미확정: 실제 구현 여부, 우선순위, 상세 정책은 사람이 결정한다.",
        ]
    )


# 주제와 기존 아이디어를 바탕으로 기능 후보를 제안한다.
def _feature_candidates(focus: str, ideas: str, research: str) -> list[str]:
    candidates = [
        f"1. {focus} 정교화",
        "   - 이유: 현재 관심 주제를 구현 가능한 작업 단위로 줄여야 한다.",
        "   - 기대 효과: GitHub Issue로 옮겼을 때 설계와 개발 범위가 흔들리지 않는다.",
        "2. 감정 기록 흐름 보강",
        "   - 이유: myMentalCare의 핵심 경험은 사용자가 자신의 상태를 이해하는 것이다.",
        "   - 기대 효과: 이후 채팅, 알림, 회고 기능의 기반 데이터가 된다.",
        "3. 부담 없는 알림 정책 설계",
        "   - 이유: 정신 건강 서비스의 알림은 도움과 부담 사이의 균형이 중요하다.",
        "   - 기대 효과: 사용자가 서비스에 압박을 느끼지 않고 다시 돌아올 수 있다.",
    ]
    if "기록 없음" not in ideas:
        candidates.append(f"- 기존 아이디어 참고: {_one_line(ideas)}")
    if "기록 없음" not in research:
        candidates.append(f"- 외부 리서치 참고: {_one_line(research)}")
    return candidates


# 구현 전에 사람이 답해야 할 질문을 만든다.
def _planning_questions(focus: str, request_body: str) -> list[str]:
    return [
        f"1. {focus}는 사용자의 어떤 불편을 가장 먼저 줄여야 하는가?",
        "2. 이 기능은 매일 쓰는 기능인가, 필요할 때만 쓰는 기능인가?",
        "3. 사용자가 실패하거나 중단했을 때 어떤 안내를 받아야 하는가?",
        "4. 이번 이슈에서 화면만 만들 것인가, API와 저장 구조까지 함께 만들 것인가?",
        f"5. 추가 요청 메모에서 반드시 반영할 문장은 무엇인가? ({_one_line(request_body)})",
    ]


# 기획 단계에서 미리 확인해야 할 위험 요소를 만든다.
def _risk_items(focus: str) -> list[str]:
    return [
        f"- {focus}의 범위가 넓으면 개발 Agent가 과도한 구현을 시도할 수 있다.",
        "- 정신 건강 관련 문구는 의학적 진단처럼 보이지 않게 조심해야 한다.",
        "- 알림이나 채팅 기능은 사용자의 감정 상태를 압박하지 않는 방향이어야 한다.",
        "- 확정되지 않은 정책을 GitHub Issue에 확정처럼 적지 않아야 한다.",
    ]


# 사람이 승인하면 GitHub Issue로 옮길 수 있는 초안을 만든다.
def _issue_draft(focus: str) -> list[str]:
    return [
        "### 목표",
        f"{focus}를 사용자가 이해하기 쉬운 서비스 흐름으로 구체화한다.",
        "",
        "### 사용자 경험",
        "- 사용자가 기능의 목적을 즉시 이해한다.",
        "- 입력, 확인, 실패 안내가 부담 없이 제공된다.",
        "",
        "### 도메인 정책",
        "- 확정된 정책만 구현한다.",
        "- 미확정 정책은 이슈의 미결정 사항으로 분리한다.",
        "",
        "### QA 기준",
        "- 주요 사용자 흐름이 화면 또는 API에서 재현된다.",
        "- 사용자에게 노출되는 메시지는 한국어로 제공된다.",
        "- 실패 상황에서도 다음 행동을 알 수 있다.",
        "",
        "### 완료 기준",
        "- Design Agent가 설계 가능한 수준의 요구사항이 정리된다.",
        "- 사람이 미결정 사항에 답변한 뒤 구현 이슈로 전환할 수 있다.",
    ]


# 보고서에서 GitHub Issue 초안 섹션만 추출한다.
def _extract_issue_draft(report: str) -> str:
    marker = "## GitHub Issue 초안"
    if marker not in report:
        return report
    return report.split(marker, 1)[1].split("## 확정/미확정 구분", 1)[0].strip()


# Planning Assistant 결과를 Obsidian planning 폴더에 누적한다.
def _append_suggestion(path: Path, report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    separator = "\n\n---\n\n" if path.exists() else ""
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Planning Assistant Suggestions\n"
    path.write_text(f"{existing}{separator}{report}", encoding="utf-8")


# 긴 텍스트를 보고서에 넣기 좋은 길이로 압축한다.
def _compact(text: str, limit: int = 800) -> str:
    normalized = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    if not normalized:
        return "기록 없음"
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n...(요약 길이 제한으로 일부 생략)"


# 여러 줄 텍스트에서 첫 줄 중심의 짧은 설명만 반환한다.
def _one_line(text: str) -> str:
    compacted = _compact(text, 140)
    return compacted.splitlines()[0] if compacted else "기록 없음"
