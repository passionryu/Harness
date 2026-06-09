from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from agents.base import AgentInput
from orchestrator.core.settings import settings


@dataclass(frozen=True)
class BrowserQaCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class BrowserScreenshotEvidence:
    file_name: str
    title: str
    description: str
    kind: str


@dataclass(frozen=True)
class PlaywrightBrowserQaResult:
    should_run: bool
    passed: bool
    report_path: Path
    screenshot_dir: Path
    checks: list[BrowserQaCheck] = field(default_factory=list)
    screenshots: list[BrowserScreenshotEvidence] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    network_failures: list[str] = field(default_factory=list)
    error: str | None = None


# 이슈 내용상 Playwright 브라우저 QA가 명시적으로 필요한 작업인지 판단한다.
def should_run_playwright_browser_qa(issue_type: str, title: str, body: str) -> bool:
    if not settings.qa_browser_enabled:
        return False
    haystack = f"{title}\n{body}".lower()
    browser_keywords = [
        "playwright",
        "e2e",
        "브라우저 qa",
        "브라우저 검증",
        "실제 브라우저",
        "시각 검증",
        "visual qa",
        "ui/ux 검증",
    ]
    return issue_type in {"feFeature", "apiConnect", "fullstackFeature", "beFeature"} and any(
        keyword in haystack for keyword in browser_keywords
    )


# 이슈 내용상 AI 채팅 화면 시나리오까지 검증해야 하는지 판단한다.
def should_run_ai_chat_scenario(title: str, body: str) -> bool:
    haystack = f"{title}\n{body}"
    return any(keyword in haystack for keyword in ["채팅", "AI 마음", "OpenAI", "마음이"])


# QA Agent가 Playwright 결과를 qa-report.md에 삽입할 Markdown으로 변환한다.
def format_playwright_report_section(result: PlaywrightBrowserQaResult) -> list[str]:
    lines = [
        "## Playwright 브라우저 QA 결과",
        "",
        f"- 실행 여부: {'Y' if result.should_run else 'N'}",
        f"- 결과: {'pass' if result.passed else 'fail'}",
        f"- 리포트: `{result.report_path}`",
        f"- 스크린샷 디렉토리: `{result.screenshot_dir}`",
        "",
    ]
    if result.error:
        lines.extend(["### 오류", "```text", result.error, "```", ""])
    lines.extend(["### 검증 항목"])
    lines.extend(
        [
            f"- [{'V' if check.passed else ' '}] {check.name} ({check.detail})"
            for check in result.checks
        ]
        or ["- 실행된 검증 항목이 없습니다."]
    )
    lines.append("")
    lines.extend(["### 콘솔 에러"])
    lines.extend([f"- {error}" for error in result.console_errors] or ["- 없음"])
    lines.append("")
    lines.extend(["### 네트워크 실패"])
    lines.extend([f"- {failure}" for failure in result.network_failures] or ["- 없음"])
    lines.append("")
    lines.extend(["### 브라우저 증거 캡처"])
    lines.extend(
        [
            f"- {evidence.kind}: {evidence.title} (`{evidence.file_name}`) - {evidence.description}"
            for evidence in result.screenshots
        ]
        or ["- 기능 플로우 증거 캡처가 없습니다."]
    )
    lines.append("")
    return lines


# Playwright로 실제 브라우저 사용자 흐름을 검증하고 별도 보고서를 생성한다.
def run_playwright_browser_qa(input_data: AgentInput, issue_type: str, task_dir: Path) -> PlaywrightBrowserQaResult:
    report_path = task_dir / "playwright-report.md"
    screenshot_dir = task_dir / "screenshots"
    _reset_screenshot_dir(screenshot_dir)

    if not should_run_playwright_browser_qa(issue_type, input_data.title, input_data.body):
        result = PlaywrightBrowserQaResult(
            should_run=False,
            passed=True,
            report_path=report_path,
            screenshot_dir=screenshot_dir,
        )
        _write_playwright_report(result)
        return result

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        result = PlaywrightBrowserQaResult(
            should_run=True,
            passed=False,
            report_path=report_path,
            screenshot_dir=screenshot_dir,
            checks=[BrowserQaCheck("Playwright 패키지 설치", False, "python package import 실패")],
            error=f"Playwright가 설치되어 있지 않습니다. {exc}",
        )
        _write_playwright_report(result)
        return result

    checks: list[BrowserQaCheck] = []
    screenshots: list[BrowserScreenshotEvidence] = []
    console_errors: list[str] = []
    network_failures: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=settings.qa_browser_headless)
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                locale="ko-KR",
                timezone_id="Asia/Seoul",
                record_video_dir=str(task_dir / "videos"),
            )
            page = context.new_page()
            page.on("console", lambda message: _collect_console_error(console_errors, message))
            page.on("pageerror", lambda error: console_errors.append(str(error)))
            page.on("response", lambda response: _collect_network_failure(network_failures, response))

            _open_home_page(page, screenshot_dir, checks)
            _login_if_needed(page, screenshot_dir, checks)

            if should_run_ai_chat_scenario(input_data.title, input_data.body):
                _run_ai_chat_flow(page, screenshot_dir, checks, screenshots)

            context.close()
            browser.close()
    except Exception as exc:  # noqa: BLE001 - QA 보고서에 실패 원인을 남겨야 한다.
        checks.append(BrowserQaCheck("Playwright 시나리오 완료", False, str(exc)))

    passed = all(check.passed for check in checks) and not console_errors and not network_failures
    result = PlaywrightBrowserQaResult(
        should_run=True,
        passed=passed,
        report_path=report_path,
        screenshot_dir=screenshot_dir,
        checks=checks,
        screenshots=screenshots,
        console_errors=console_errors,
        network_failures=network_failures,
    )
    _write_playwright_report(result)
    return result


# 브라우저 QA 상세 보고서를 별도 Markdown 파일로 저장한다.
def _write_playwright_report(result: PlaywrightBrowserQaResult) -> None:
    if result.screenshots:
        (result.screenshot_dir / "evidence.json").write_text(
            json.dumps([asdict(screenshot) for screenshot in result.screenshots], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    result.report_path.write_text(
        "\n".join(
            [
                "# Playwright Browser QA Report",
                "",
                *format_playwright_report_section(result),
            ]
        ),
        encoding="utf-8",
    )


def _reset_screenshot_dir(screenshot_dir: Path) -> None:
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    for image_path in screenshot_dir.glob("*.png"):
        image_path.unlink(missing_ok=True)
    (screenshot_dir / "evidence.json").unlink(missing_ok=True)


def _capture_evidence(
    page: Any,
    screenshot_dir: Path,
    screenshots: list[BrowserScreenshotEvidence],
    file_name: str,
    title: str,
    description: str,
    kind: str,
) -> None:
    image_path = screenshot_dir / file_name
    page.screenshot(path=str(image_path), full_page=True)
    screenshots.append(
        BrowserScreenshotEvidence(
            file_name=file_name,
            title=title,
            description=description,
            kind=kind,
        )
    )


# 콘솔 에러 메시지만 수집한다.
def _collect_console_error(console_errors: list[str], message: Any) -> None:
    if getattr(message, "type", "") == "error":
        console_errors.append(message.text)


# 서비스 대상 URL에서 발생한 4xx/5xx 응답을 수집한다.
def _collect_network_failure(network_failures: list[str], response: Any) -> None:
    url = response.url
    if "favicon" in url:
        return
    is_target_url = url.startswith(settings.frontend_base_url) or url.startswith(settings.target_api_base_url)
    if is_target_url and response.status >= 400:
        network_failures.append(f"{response.status} {response.request.method} {url}")


# 프론트엔드 첫 화면을 열고 기본 렌더링을 확인한다.
def _open_home_page(page: Any, screenshot_dir: Path, checks: list[BrowserQaCheck]) -> None:
    response = page.goto(settings.frontend_base_url, wait_until="domcontentloaded", timeout=settings.qa_browser_timeout_ms)
    status = response.status if response else None
    checks.append(BrowserQaCheck("프론트엔드 첫 화면 접근", status is not None and status < 400, f"url={settings.frontend_base_url}, status={status}"))


# 로그인 상태가 아니면 테스트 계정으로 로그인한다.
def _login_if_needed(page: Any, screenshot_dir: Path, checks: list[BrowserQaCheck]) -> None:
    try:
        if _first_visible_text(page, "로그아웃"):
            checks.append(BrowserQaCheck("테스트 계정 로그인", True, "이미 로그인 상태"))
            return

        login_button = page.get_by_role("button", name=re.compile("로그인")).first
        login_button.click(timeout=settings.qa_browser_timeout_ms)
        page.locator('input[name="loginId"]').last.fill(settings.qa_browser_login_id)
        page.locator('input[name="password"]').last.fill(settings.qa_browser_login_password)
        page.locator("form").last.get_by_role("button", name=re.compile("^로그인$")).click()
        page.get_by_role("button", name=re.compile("로그아웃|프로필")).first.wait_for(timeout=settings.qa_browser_timeout_ms)
        checks.append(BrowserQaCheck("테스트 계정 로그인", True, f"loginId={settings.qa_browser_login_id}"))
    except Exception as exc:  # noqa: BLE001 - 로그인 실패를 QA 항목으로 기록한다.
        setup_dir = screenshot_dir / "_setup"
        setup_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(setup_dir / "login-failed.png"), full_page=True)
        checks.append(BrowserQaCheck("테스트 계정 로그인", False, str(exc)))


# AI 마음 대화 화면에서 메시지 전송과 응답 표시를 검증한다.
def _run_ai_chat_flow(
    page: Any,
    screenshot_dir: Path,
    checks: list[BrowserQaCheck],
    screenshots: list[BrowserScreenshotEvidence],
) -> None:
    try:
        if _first_visible_text(page, "오늘의 대화 시작"):
            page.get_by_role("button", name=re.compile("오늘의 대화 시작")).click(timeout=settings.qa_browser_timeout_ms)
        else:
            page.goto(_frontend_path("/chat"), wait_until="domcontentloaded", timeout=settings.qa_browser_timeout_ms)

        page.get_by_text("마음이와 오늘의 대화").wait_for(timeout=settings.qa_browser_timeout_ms)
        checks.append(BrowserQaCheck("AI 채팅 화면 진입", True, _frontend_path("/chat")))
        _capture_evidence(
            page,
            screenshot_dir,
            screenshots,
            "01-ai-chat-entry.png",
            "AI 채팅 기능 시작 화면",
            "로그인 등 준비 단계를 제외하고 실제 검증 대상인 AI 채팅 화면에 진입한 상태입니다.",
            "success",
        )

        _capture_empty_message_edge(page, screenshot_dir, checks, screenshots)

        assistant_count = page.locator(".chat-bubble.is-assistant").count()
        message = "Playwright QA 확인이야. 오늘 대화 흐름을 차분히 이어갈 수 있는지 봐줘."
        page.locator("#ai-chat-message").fill(message)
        _capture_evidence(
            page,
            screenshot_dir,
            screenshots,
            "02-ai-chat-message-ready.png",
            "AI 채팅 메시지 입력",
            "사용자가 검증 메시지를 입력했고, 전송 직전 화면 상태를 기록했습니다.",
            "success",
        )
        with page.expect_response(
            lambda response: "/api/ai-chat/rooms/today/messages" in response.url
            and response.request.method == "POST",
            timeout=settings.qa_browser_timeout_ms,
        ) as response_info:
            page.get_by_role("button", name=re.compile("보내기")).click()

        response = response_info.value
        body = _safe_response_json(response)
        ai_reply_failed = bool(body.get("aiReplyFailed")) if isinstance(body, dict) else False
        checks.append(
            BrowserQaCheck(
                "AI 채팅 메시지 API 응답",
                response.status < 400 and not ai_reply_failed,
                f"status={response.status}, aiReplyFailed={ai_reply_failed}",
            )
        )
        page.wait_for_function(
            "count => document.querySelectorAll('.chat-bubble.is-assistant').length > count",
            arg=assistant_count,
            timeout=settings.qa_browser_timeout_ms,
        )
        _capture_evidence(
            page,
            screenshot_dir,
            screenshots,
            "03-ai-chat-response.png",
            "AI 응답 표시",
            "메시지 전송 후 AI 응답 말풍선이 추가되어 사용자의 대화 플로우가 끝까지 완료된 상태입니다.",
            "success",
        )
        checks.append(BrowserQaCheck("AI 응답 화면 표시", True, "03-ai-chat-response.png"))
    except Exception as exc:  # noqa: BLE001 - 채팅 실패를 QA 항목으로 기록한다.
        _capture_evidence(
            page,
            screenshot_dir,
            screenshots,
            "99-ai-chat-failed.png",
            "AI 채팅 실패 화면",
            f"AI 채팅 플로우 검증 중 실패한 시점의 화면입니다. 실패 원인: {exc}",
            "failure",
        )
        checks.append(BrowserQaCheck("AI 채팅 화면 검증", False, str(exc)))


def _capture_empty_message_edge(
    page: Any,
    screenshot_dir: Path,
    checks: list[BrowserQaCheck],
    screenshots: list[BrowserScreenshotEvidence],
) -> None:
    input_box = page.locator("#ai-chat-message")
    send_button = page.get_by_role("button", name=re.compile("보내기")).first
    input_box.fill("")
    try:
        blocked = send_button.is_disabled(timeout=1_000)
        detail = "빈 메시지 상태에서 전송 버튼이 비활성화되었습니다." if blocked else "빈 메시지 상태에서 전송 버튼이 활성 상태입니다."
    except Exception as exc:  # noqa: BLE001 - 버튼 상태 확인 실패도 엣지 케이스 증거로 남긴다.
        blocked = False
        detail = f"빈 메시지 전송 버튼 상태 확인 실패: {exc}"
    _capture_evidence(
        page,
        screenshot_dir,
        screenshots,
        "02-ai-chat-empty-message-edge.png",
        "엣지 케이스: 빈 메시지 전송 방지",
        detail,
        "edge",
    )
    checks.append(BrowserQaCheck("빈 AI 채팅 메시지 전송 방지", blocked, detail))


# 특정 문구가 화면에 보이는지 짧게 확인한다.
def _first_visible_text(page: Any, text: str) -> bool:
    locator = page.get_by_text(text).first
    try:
        return locator.is_visible(timeout=1_000)
    except Exception:  # noqa: BLE001 - 보이지 않는 경우 False로 처리한다.
        return False


# 프론트엔드 base URL에 path를 붙인다.
def _frontend_path(path: str) -> str:
    return urljoin(settings.frontend_base_url.rstrip("/") + "/", path.lstrip("/"))


# Playwright response body를 JSON으로 안전하게 변환한다.
def _safe_response_json(response: Any) -> dict[str, Any]:
    try:
        parsed = response.json()
        return parsed if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001 - JSON이 아닌 응답은 빈 dict로 처리한다.
        try:
            return json.loads(response.text())
        except Exception:  # noqa: BLE001 - QA 실패 원인은 status/check로 남긴다.
            return {}
