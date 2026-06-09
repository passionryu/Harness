from __future__ import annotations

import base64
import html
import re
from pathlib import Path

from orchestrator.core.settings import settings
from orchestrator.db.models import Task


# QA Markdown 산출물을 사람이 읽기 쉬운 PDF 보고서로 렌더링한다.
def build_qa_pdf_report(task: Task) -> Path | None:
    if not settings.qa_pdf_enabled:
        return None

    qa_dir = settings.artifact_root / task.id / "qa"
    qa_report = qa_dir / "qa-report.md"
    if not qa_report.exists():
        return None

    playwright_report = qa_dir / "playwright-report.md"
    screenshot_dir = qa_dir / "screenshots"
    pdf_path = qa_dir / f"qa-report-issue-{task.github_issue_number or 'unknown'}.pdf"

    html_content = _build_html_document(
        title=task.title,
        issue_number=task.github_issue_number,
        qa_markdown=qa_report.read_text(encoding="utf-8"),
        playwright_markdown=playwright_report.read_text(encoding="utf-8") if playwright_report.exists() else "",
        screenshot_dir=screenshot_dir,
    )
    _render_html_to_pdf(html_content, pdf_path)
    return pdf_path


# HTML 문자열을 Chromium print PDF로 변환한다.
def _render_html_to_pdf(html_content: str, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1600})
        page.set_content(html_content, wait_until="load")
        page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            margin={"top": "18mm", "right": "14mm", "bottom": "18mm", "left": "14mm"},
        )
        browser.close()


# QA 보고서와 Playwright 스크린샷을 하나의 HTML 보고서로 합친다.
def _build_html_document(
    title: str,
    issue_number: int | None,
    qa_markdown: str,
    playwright_markdown: str,
    screenshot_dir: Path,
) -> str:
    screenshots = _render_screenshots(screenshot_dir)
    playwright_section = (
        f"<section><h1>Playwright 상세 보고서</h1>{_markdown_to_html(playwright_markdown)}</section>"
        if playwright_markdown
        else ""
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>QA Report</title>
  <style>
    body {{
      color: #182018;
      font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
      line-height: 1.62;
      background: #fbfaf6;
    }}
    .cover {{
      border: 1px solid #dfd7c8;
      border-radius: 18px;
      padding: 28px;
      margin-bottom: 28px;
      background: #fffaf1;
    }}
    .eyebrow {{
      color: #b46b4d;
      font-size: 13px;
      font-weight: 800;
      letter-spacing: 0;
      margin: 0 0 8px;
    }}
    h1 {{
      border-bottom: 1px solid #d8d0c2;
      color: #111811;
      font-size: 25px;
      margin: 30px 0 14px;
      padding-bottom: 8px;
    }}
    h2 {{
      color: #223522;
      font-size: 20px;
      margin: 24px 0 10px;
    }}
    h3 {{
      color: #315433;
      font-size: 16px;
      margin: 18px 0 8px;
    }}
    p, li {{
      font-size: 12px;
    }}
    code {{
      background: #f0eadf;
      border-radius: 4px;
      padding: 1px 4px;
    }}
    pre {{
      background: #172019;
      border-radius: 12px;
      color: #f4f1e8;
      font-size: 10px;
      overflow-wrap: anywhere;
      padding: 14px;
      white-space: pre-wrap;
    }}
    .screenshot {{
      break-inside: avoid;
      margin: 18px 0 28px;
    }}
    .screenshot img {{
      border: 1px solid #d8d0c2;
      border-radius: 12px;
      max-width: 100%;
    }}
  </style>
</head>
<body>
  <section class="cover">
    <p class="eyebrow">myMentalCare QA Report</p>
    <h1>{html.escape(title)}</h1>
    <p>GitHub Issue: #{issue_number or "unknown"}</p>
    <p>System QA 결과와 Playwright 브라우저 검증 결과를 하나의 PDF로 정리했습니다.</p>
  </section>
  <section>
    {_markdown_to_html(qa_markdown)}
  </section>
  {playwright_section}
  {screenshots}
</body>
</html>"""


# 스크린샷 디렉토리의 PNG 파일을 PDF 보고서 이미지 섹션으로 렌더링한다.
def _render_screenshots(screenshot_dir: Path) -> str:
    if not screenshot_dir.exists():
        return ""

    blocks: list[str] = ["<section><h1>브라우저 스크린샷</h1>"]
    for image_path in sorted(screenshot_dir.glob("*.png")):
        data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        blocks.append(
            "<div class=\"screenshot\">"
            f"<h2>{html.escape(image_path.name)}</h2>"
            f"<img src=\"data:image/png;base64,{data}\" alt=\"{html.escape(image_path.name)}\" />"
            "</div>"
        )
    blocks.append("</section>")
    return "\n".join(blocks)


# QA Markdown의 주요 표현을 PDF용 HTML로 변환한다.
def _markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    in_code = False
    list_open = False
    code_lines: list[str] = []

    for line in lines:
        stripped = line.rstrip()
        if stripped.startswith("```"):
            if in_code:
                output.append(f"<pre>{html.escape(chr(10).join(code_lines))}</pre>")
                code_lines = []
                in_code = False
            else:
                _close_list(output, list_open)
                list_open = False
                in_code = True
            continue

        if in_code:
            code_lines.append(stripped)
            continue

        if not stripped:
            _close_list(output, list_open)
            list_open = False
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            _close_list(output, list_open)
            list_open = False
            level = len(heading.group(1))
            output.append(f"<h{level}>{_inline_markdown(heading.group(2))}</h{level}>")
            continue

        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet:
            if not list_open:
                output.append("<ul>")
                list_open = True
            output.append(f"<li>{_inline_markdown(_normalize_check_marker(bullet.group(1)))}</li>")
            continue

        _close_list(output, list_open)
        list_open = False
        output.append(f"<p>{_inline_markdown(stripped)}</p>")

    if in_code:
        output.append(f"<pre>{html.escape(chr(10).join(code_lines))}</pre>")
    _close_list(output, list_open)
    return "\n".join(output)


# Markdown 목록 태그가 열려 있으면 닫는다.
def _close_list(output: list[str], list_open: bool) -> None:
    if list_open:
        output.append("</ul>")


# 인라인 코드와 굵은 글씨 정도만 HTML로 변환한다.
def _inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


# PDF에서는 완료 체크를 X가 아닌 V로 통일한다. 기존 artifact의 [x]도 렌더링 시 보정한다.
def _normalize_check_marker(text: str) -> str:
    return re.sub(r"^\[[xX]\]\s+", "[V] ", text)
