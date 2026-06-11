from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QaPlanItem:
    item_id: str
    text: str
    source: str
    verification: str
    runner_hint: str


@dataclass(frozen=True)
class QaPlan:
    items: list[QaPlanItem]
    fallback_used: bool

    @property
    def has_issue_specific_items(self) -> bool:
        return bool(self.items) and not self.fallback_used

    def human_checklist(self) -> list[str]:
        return [item.text for item in self.items]


PRIMARY_QA_HEADINGS = [
    "QA 기준",
    "검증 기준",
    "완료 기준",
    "Acceptance Criteria",
    "사용자 플로우",
]

SECONDARY_QA_HEADINGS = [
    "프론트엔드 구현 범위",
    "백엔드 구현 범위",
    "API Contract",
    "체크인 모달 요구사항",
    "채팅창 요구사항",
    "기타 직접 입력 정책",
    "디자인 기준",
]

BROWSER_KEYWORDS = [
    "화면",
    "브라우저",
    "버튼",
    "클릭",
    "모달",
    "폼",
    "입력",
    "노출",
    "보이는",
    "표시",
    "선택",
    "단계",
    "마법사",
    "레이아웃",
    "텍스트",
    "모바일",
    "데스크톱",
    "색감",
    "톤",
    "템플릿",
]

API_KEYWORDS = ["API", "curl", "HTTP", "응답", "status", "저장", "조회", "DB", "데이터", "서버"]
SECURITY_KEYWORDS = ["인증", "인가", "권한", "민감정보", "위험", "위기", "안전", "자해", "자살"]


def build_qa_plan(title: str, body: str, fallback_items: list[str]) -> QaPlan:
    """Build an issue-specific QA plan from planning/design text.

    The QA agent should prefer explicit issue QA criteria over static presets. Static
    presets stay as a fallback for old or underspecified issues.
    """

    extracted = _extract_issue_specific_items(body)
    source_items = extracted if extracted else [(item, "fallback") for item in fallback_items]
    limited_items = _dedupe_items(source_items)[:18]
    items = [
        QaPlanItem(
            item_id=f"QP-{index:03d}",
            text=text,
            source=source,
            verification=_classify_verification(text),
            runner_hint=_classify_runner_hint(title, text),
        )
        for index, (text, source) in enumerate(limited_items, start=1)
    ]
    return QaPlan(items=items, fallback_used=not bool(extracted))


def render_qa_plan_markdown(plan: QaPlan) -> list[str]:
    lines = [
        "## QA Plan",
        "",
        f"- source: `{'fallback preset' if plan.fallback_used else 'issue planning/design text'}`",
        f"- items: `{len(plan.items)}`",
        "",
        "### 기능별 검증 항목",
    ]
    if not plan.items:
        lines.append("- 추출된 QA 항목이 없습니다.")
        lines.append("")
        return lines

    for item in plan.items:
        lines.append(
            f"- `{item.item_id}` [{item.verification}] {item.text} "
            f"(source={item.source}, runner={item.runner_hint})"
        )
    lines.append("")
    lines.extend(
        [
            "### 자동화 커버리지 원칙",
            "- `auto-candidate`는 자동 Runner가 직접 검증해야 하는 후보입니다.",
            "- 자동 Runner가 직접 검증하지 못한 항목은 통과로 표시하지 않고 Human QA에 남깁니다.",
            "- `human-required`는 시각 품질, 정책 판단, 운영 확인처럼 사람이 최종 승인해야 하는 항목입니다.",
            "",
        ]
    )
    return lines


def qa_plan_coverage_lines(plan: QaPlan) -> list[str]:
    if not plan.items:
        return ["- QA Plan 항목이 없어 커버리지 판단을 생략했습니다."]
    lines: list[str] = []
    for item in plan.items:
        if item.verification == "human-required":
            status = "Human QA 필요"
        elif item.verification == "auto-candidate":
            status = "자동 Runner 후보"
        else:
            status = "자동화 미지원"
        lines.append(f"- {item.item_id}: {status} - {item.text} ({item.runner_hint})")
    return lines


def _extract_issue_specific_items(markdown: str) -> list[tuple[str, str]]:
    primary = _extract_items_from_headings(markdown, PRIMARY_QA_HEADINGS)
    if primary:
        return primary
    return _extract_items_from_headings(markdown, SECONDARY_QA_HEADINGS)


def _extract_items_from_headings(markdown: str, headings: list[str]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for heading in headings:
        for item in _extract_section_items(markdown, heading):
            items.append((item, heading))
    return items


def _extract_section_items(markdown: str, heading: str) -> list[str]:
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
            if title == heading:
                in_section = True
                section_level = level
                continue
        if in_section:
            collected.append(line)

    return [_normalize_item(line) for line in collected if _is_list_item(line)]


def _is_list_item(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r"^([-*]|\d+[.)])\s+", stripped))


def _normalize_item(line: str) -> str:
    text = re.sub(r"^([-*]|\d+[.)])\s+", "", line.strip())
    text = re.sub(r"^\[[ xXvV]\]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _dedupe_items(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for text, source in items:
        key = _dedupe_key(text)
        if not text or key in seen or _should_skip_item(text):
            continue
        seen.add(key)
        deduped.append((text, source))
    return deduped


def _dedupe_key(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", text).lower()


def _should_skip_item(text: str) -> bool:
    lowered = text.lower()
    return lowered.startswith("http") or lowered.endswith(".png`") or lowered.endswith(".svg`")


def _classify_verification(text: str) -> str:
    if any(keyword in text for keyword in ["디자인", "톤", "색감", "해치지 않는다", "자연스럽게"]):
        return "human-required"
    if any(keyword in text for keyword in BROWSER_KEYWORDS + API_KEYWORDS):
        return "auto-candidate"
    return "human-required"


def _classify_runner_hint(title: str, text: str) -> str:
    haystack = f"{title}\n{text}"
    if any(keyword in haystack for keyword in SECURITY_KEYWORDS):
        return "Security Boundary Validator"
    if any(keyword in haystack for keyword in API_KEYWORDS):
        return "Integration/API Scenario Runner"
    if any(keyword in haystack for keyword in BROWSER_KEYWORDS):
        return "Browser Scenario Runner"
    return "Human Checklist Writer"
