from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec
from orchestrator.core.settings import settings


@dataclass(frozen=True)
class FrontendSnapshot:
    repo: Path
    web_root: Path
    page_files: list[str] = field(default_factory=list)
    component_files: list[str] = field(default_factory=list)
    style_markers: list[str] = field(default_factory=list)
    icon_library: str = "확인 필요"


@dataclass(frozen=True)
class BrowserObservation:
    ran: bool
    reachable: bool
    details: list[str] = field(default_factory=list)
    screenshots: list[Path] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    network_failures: list[str] = field(default_factory=list)


class UIUXDesignerAgent:
    name = "uiux_designer"

    # UI/UX 작업의 첫 단계에서 사람과 논의할 방향성과 Planning Agent handoff를 만든다.
    def run(self, input_data: AgentInput) -> AgentResult:
        task_dir = input_data.artifacts_root / input_data.task_id / "uiux-designer"
        task_dir.mkdir(parents=True, exist_ok=True)

        topic = _topic_from_body(input_data.body) or input_data.title
        note = "\n".join(_extract_section(input_data.body, "요청 메모"))
        target_user = _single_line_value(input_data.body, "target_user") or "핵심 사용자"
        routes = _routes_from_body(input_data.body)
        snapshot = _inspect_frontend_codebase()
        observation = _probe_frontend_with_playwright(routes, task_dir)

        brief = _build_design_brief(topic, note, target_user, routes, snapshot, observation)
        handoff = _build_planning_handoff(topic, note, target_user, routes, snapshot, observation)
        conversation_guide = _build_conversation_guide(topic, note, target_user)

        brief_path = task_dir / "uiux-design-brief.md"
        handoff_path = task_dir / "planning-handoff.md"
        guide_path = task_dir / "conversation-guide.md"
        brief_path.write_text(brief, encoding="utf-8")
        handoff_path.write_text(handoff, encoding="utf-8")
        guide_path.write_text(conversation_guide, encoding="utf-8")

        _append_obsidian_uiux_brief(topic, brief)

        artifacts = [
            ArtifactSpec("uiux-design-brief", brief_path),
            ArtifactSpec("uiux-planning-handoff", handoff_path),
            ArtifactSpec("uiux-conversation-guide", guide_path),
        ]
        if observation.screenshots:
            artifacts.append(ArtifactSpec("uiux-screenshots", task_dir / "screenshots"))

        return AgentResult(
            status=AgentStatus.SUCCESS,
            summary=f"UI/UX Designer Agent가 `{topic}` 방향성과 Planning handoff를 작성했습니다.",
            artifacts=artifacts,
        )


def _topic_from_body(body: str) -> str:
    return _single_line_value(body, "topic")


def _single_line_value(body: str, key: str) -> str:
    prefix = f"{key}:"
    for line in body.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return ""


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


def _routes_from_body(body: str) -> list[str]:
    routes: list[str] = []
    in_routes = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == "routes:":
            in_routes = True
            continue
        if in_routes:
            if not stripped:
                continue
            if stripped.startswith("#") or ":" in stripped and not stripped.startswith("-"):
                break
            if stripped.startswith("-"):
                route = stripped.removeprefix("-").strip()
                if route:
                    routes.append(route)
    return routes or ["/"]


def _inspect_frontend_codebase() -> FrontendSnapshot:
    repo = settings.target_repo_path.expanduser().resolve()
    web_root = repo / "apps" / "web"
    if not web_root.exists():
        web_root = repo

    package_text = _read_text(web_root / "package.json")
    page_files = _relative_files(web_root / "app", {".tsx", ".ts", ".css"}, 40)
    component_files = _relative_files(web_root / "components", {".tsx", ".ts"}, 40)
    style_markers: list[str] = []
    globals_css = web_root / "app" / "globals.css"
    if globals_css.exists():
        style_markers.append("전역 CSS: app/globals.css")
    if "tailwind" in package_text.lower() or "className=" in _read_first_existing(page_files, web_root):
        style_markers.append("Tailwind/className 기반 스타일 가능성")
    if "framer-motion" in package_text:
        style_markers.append("framer-motion 사용 가능")
    if not style_markers:
        style_markers.append("스타일 시스템은 Planning Agent가 추가 확인 필요")

    icon_library = "lucide-react" if "lucide-react" in package_text else "확인 필요"
    return FrontendSnapshot(
        repo=repo,
        web_root=web_root,
        page_files=page_files,
        component_files=component_files,
        style_markers=style_markers,
        icon_library=icon_library,
    )


def _read_text(path: Path, limit: int = 12000) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except OSError:
        return ""


def _relative_files(root: Path, suffixes: set[str], limit: int) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        str(path.relative_to(root.parent))
        for path in root.rglob("*")
        if path.is_file() and path.suffix in suffixes
    )[:limit]


def _read_first_existing(files: list[str], web_root: Path) -> str:
    for relative in files[:5]:
        text = _read_text(web_root / relative)
        if text:
            return text
    return ""


def _probe_frontend_with_playwright(routes: list[str], task_dir: Path) -> BrowserObservation:
    if not settings.qa_browser_enabled:
        return BrowserObservation(ran=False, reachable=False, details=["브라우저 관찰 비활성화: QA_BROWSER_ENABLED=false"])
    if not _is_frontend_reachable():
        return BrowserObservation(
            ran=False,
            reachable=False,
            details=[f"프론트엔드가 응답하지 않아 Playwright 관찰을 생략했습니다: {settings.frontend_base_url}"],
        )

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return BrowserObservation(
            ran=False,
            reachable=True,
            details=[f"Playwright import 실패: {exc}"],
        )

    screenshot_dir = task_dir / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    details: list[str] = []
    screenshots: list[Path] = []
    console_errors: list[str] = []
    network_failures: list[str] = []
    viewports = [
        ("mobile", {"width": 390, "height": 844}),
        ("desktop", {"width": 1440, "height": 900}),
    ]

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=settings.qa_browser_headless)
            context = browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul")
            page = context.new_page()
            page.on("console", lambda message: _collect_console_error(console_errors, message))
            page.on("pageerror", lambda error: console_errors.append(str(error)))
            page.on("response", lambda response: _collect_network_failure(network_failures, response))
            for route in routes:
                for viewport_name, viewport in viewports:
                    page.set_viewport_size(viewport)
                    url = _route_url(route)
                    response = page.goto(url, wait_until="domcontentloaded", timeout=settings.qa_browser_timeout_ms)
                    status = response.status if response else None
                    filename = f"{_safe_route_name(route)}-{viewport_name}.png"
                    screenshot_path = screenshot_dir / filename
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    screenshots.append(screenshot_path)
                    details.append(f"{route} {viewport_name}: status={status}, screenshot={filename}")
            context.close()
            browser.close()
    except Exception as exc:  # noqa: BLE001 - 브리프에 관찰 실패 원인을 남긴다.
        details.append(f"Playwright 관찰 중 오류: {exc}")

    return BrowserObservation(
        ran=True,
        reachable=True,
        details=details,
        screenshots=screenshots,
        console_errors=console_errors,
        network_failures=network_failures,
    )


def _is_frontend_reachable() -> bool:
    try:
        request = Request(settings.frontend_base_url, method="GET")
        with urlopen(request, timeout=2) as response:  # noqa: S310 - local configured URL probe
            return response.status < 500
    except Exception:  # noqa: BLE001 - unreachable means optional browser evidence is skipped.
        return False


def _route_url(route: str) -> str:
    return urljoin(settings.frontend_base_url.rstrip("/") + "/", route.lstrip("/"))


def _safe_route_name(route: str) -> str:
    normalized = route.strip("/") or "home"
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", normalized).strip("-") or "home"


def _collect_console_error(console_errors: list[str], message: object) -> None:
    if getattr(message, "type", "") == "error":
        console_errors.append(getattr(message, "text", "console error"))


def _collect_network_failure(network_failures: list[str], response: object) -> None:
    url = getattr(response, "url", "")
    status = int(getattr(response, "status", 0) or 0)
    if "favicon" in url or status < 400:
        return
    if url.startswith(settings.frontend_base_url) or url.startswith(settings.target_api_base_url):
        request = getattr(response, "request", None)
        method = getattr(request, "method", "GET")
        network_failures.append(f"{status} {method} {url}")


def _build_design_brief(
    topic: str,
    note: str,
    target_user: str,
    routes: list[str],
    snapshot: FrontendSnapshot,
    observation: BrowserObservation,
) -> str:
    now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d %H:%M:%S")
    return "\n".join(
        [
            f"# UI/UX Design Brief: {topic}",
            "",
            f"- 작성 시각: {now}",
            f"- 대상 사용자: {target_user}",
            f"- 확인 route: {', '.join(routes)}",
            "",
            "## Goal",
            f"{topic}의 사용자 목표와 화면 방향을 먼저 정리하고, 구현 계획은 Planning Agent가 이어받게 한다.",
            "",
            "## User Request",
            note or "추가 요청 메모 없음",
            "",
            "## Current Evidence",
            f"- target repo: `{snapshot.repo}`",
            f"- web root: `{snapshot.web_root}`",
            f"- page files: {', '.join(snapshot.page_files[:8]) if snapshot.page_files else '확인된 page 파일 없음'}",
            f"- component files: {', '.join(snapshot.component_files[:8]) if snapshot.component_files else '확인된 component 파일 없음'}",
            f"- style: {', '.join(snapshot.style_markers)}",
            f"- icon library: {snapshot.icon_library}",
            *_browser_evidence_lines(observation),
            "",
            "## Design Direction",
            "- 첫 화면에서 사용자가 다음 행동을 빠르게 식별할 수 있게 한다.",
            "- 화면 설명보다 사용자 행동, 상태, 피드백을 먼저 설계한다.",
            "- 모바일에서는 한 번에 하나의 핵심 행동이 보이도록 정보 밀도를 조정한다.",
            "- 기존 디자인 시스템과 컴포넌트 패턴을 우선 사용한다.",
            "",
            "## Interaction Model",
            "- primary action은 첫 viewport 안에서 발견 가능해야 한다.",
            "- secondary action은 사용 빈도와 위험도에 따라 menu, tab, 또는 하단 영역으로 분리한다.",
            "- loading, empty, error, success 상태를 화면 단위로 정의한다.",
            "",
            "## Accessibility And Responsive Criteria",
            "- 390px 모바일 폭에서 horizontal scroll이 없어야 한다.",
            "- 아이콘 버튼은 접근성 이름을 가져야 한다.",
            "- 폼 입력과 에러 메시지는 label, description, focus 이동 기준을 가져야 한다.",
            "- 텍스트와 주요 버튼은 WCAG AA 수준의 대비를 목표로 한다.",
            "",
            "## Suggested Planning Questions",
            *_conversation_questions(topic, target_user),
            "",
            "## Non Goals",
            "- 이 에이전트는 파일을 수정하지 않는다.",
            "- 이 에이전트는 QA 통과 여부를 판정하지 않는다.",
            "- 구현 상세는 Planning Agent와 Dev Agent가 담당한다.",
        ]
    )


def _browser_evidence_lines(observation: BrowserObservation) -> list[str]:
    lines = [
        f"- Playwright observation: {'ran' if observation.ran else 'not-run'}",
        f"- frontend reachable: {'Y' if observation.reachable else 'N'}",
    ]
    lines.extend([f"- observation: {detail}" for detail in observation.details] or ["- observation: 기록 없음"])
    if observation.console_errors:
        lines.append("- console errors: " + "; ".join(observation.console_errors[:5]))
    if observation.network_failures:
        lines.append("- network failures: " + "; ".join(observation.network_failures[:5]))
    if observation.screenshots:
        lines.append("- screenshots: " + ", ".join(str(path) for path in observation.screenshots[:6]))
    return lines


def _build_planning_handoff(
    topic: str,
    note: str,
    target_user: str,
    routes: list[str],
    snapshot: FrontendSnapshot,
    observation: BrowserObservation,
) -> str:
    return "\n".join(
        [
            f"# Planning Handoff: {topic}",
            "",
            "## 목표",
            f"{topic}를 {target_user}가 이해하고 사용할 수 있는 화면 흐름으로 구체화한다.",
            "",
            "## 작업 범위",
            "- UI/UX Designer Brief를 바탕으로 화면 진입점, 사용자 흐름, 상태 표현을 설계한다.",
            "- 구현 파일과 컴포넌트 영향 범위는 Planning Agent가 코드베이스 기준으로 확정한다.",
            "- 기존 디자인 시스템, 스타일 방식, 아이콘 라이브러리를 우선 사용한다.",
            "",
            "## 디자인 방향",
            "- primary action, secondary action, feedback 상태를 명확히 분리한다.",
            "- 모바일과 데스크톱에서 정보 위계가 유지되도록 설계한다.",
            "- 감상적 리디자인보다 사용자의 다음 행동을 줄이는 쪽을 우선한다.",
            "",
            "## 화면/라우트",
            *[f"- {route}" for route in routes],
            "",
            "## 현재 근거",
            f"- target repo: `{snapshot.repo}`",
            f"- web root: `{snapshot.web_root}`",
            f"- style: {', '.join(snapshot.style_markers)}",
            f"- icon library: {snapshot.icon_library}",
            f"- browser observation: {'ran' if observation.ran else 'not-run'}",
            "",
            "## 요청 메모",
            note or "- 추가 요청 메모 없음",
            "",
            "## 완료 기준",
            "- 사용자가 첫 화면에서 핵심 다음 행동을 식별할 수 있다.",
            "- 390px 모바일 폭에서 텍스트 겹침과 horizontal scroll이 없다.",
            "- 주요 버튼, 입력, 메뉴가 keyboard/focus/accessibility 이름을 가진다.",
            "- loading, empty, error, success 상태 기준이 계획에 포함된다.",
            "",
            "## 미결정 사항",
            *_conversation_questions(topic, target_user),
            "",
            "## UI/UX Designer Note",
            "이 handoff는 구현 지시가 아니라 Planning Agent가 개발 가능한 설계로 바꿀 입력이다.",
            "GitHub Issue를 만들면 Design Agent 실행 전까지 Project Status는 반드시 Backlog에 둔다.",
            "화면 증거 이미지를 Git에 올릴 때는 증거 브랜치에서 끝내지 말고 stage 브랜치에 병합한다.",
        ]
    )


def _build_conversation_guide(topic: str, note: str, target_user: str) -> str:
    return "\n".join(
        [
            f"# UI/UX Conversation Guide: {topic}",
            "",
            "## Opening",
            f"{topic}에서 {target_user}가 가장 먼저 성공해야 하는 행동을 확인한다.",
            "",
            "## Questions",
            *_conversation_questions(topic, target_user),
            "",
            "## Notes From User",
            note or "아직 기록된 사용자 메모 없음",
            "",
            "## Handoff Rule",
            "방향성이 잡히면 `planning-handoff.md`를 GitHub Issue 본문 또는 `harness create-issue --body-file` 입력으로 넘긴다.",
            "사용자 명령으로 이슈를 만들면 GitHub Project 위치는 Todo가 아니라 Backlog로 둔다.",
            "UI 증거 이미지를 첨부해야 하면 `harness publish-ui-evidence --image <path> --issue <number>`로 stage 병합까지 끝낸다.",
        ]
    )


def _conversation_questions(topic: str, target_user: str) -> list[str]:
    return [
        f"- {target_user}는 {topic} 화면에서 5초 안에 무엇을 해야 한다고 느껴야 하는가?",
        "- 첫 화면에서 반드시 보여야 하는 정보와 숨겨도 되는 정보는 무엇인가?",
        "- 사용자가 막히는 순간에는 어떤 문구와 행동 선택지를 제공해야 하는가?",
        "- 모바일에서 primary action은 어디에 있어야 가장 자연스러운가?",
        "- 이번 작업에서 하지 않을 리디자인 범위는 어디까지인가?",
    ]


def _append_obsidian_uiux_brief(topic: str, brief: str) -> None:
    vault_path = settings.obsidian_vault_path.expanduser()
    if not vault_path.exists():
        return
    target = vault_path / "planning" / "uiux-design-briefs.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    separator = "\n\n---\n\n" if target.exists() else ""
    existing = target.read_text(encoding="utf-8") if target.exists() else "# UI/UX Design Briefs\n"
    target.write_text(f"{existing}{separator}## {topic}\n\n{brief}", encoding="utf-8")
