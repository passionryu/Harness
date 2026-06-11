from __future__ import annotations

import base64
import html
import json
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


# QA 보고서와 Playwright 스크린샷을 사람 중심 HTML 보고서로 재구성한다.
def _build_html_document(
    title: str,
    issue_number: int | None,
    qa_markdown: str,
    playwright_markdown: str,
    screenshot_dir: Path,
) -> str:
    metadata = _extract_report_metadata(qa_markdown)
    auto_checks = _extract_check_items(qa_markdown, "검증 체크리스트", blank_status="fail")
    human_checks = _extract_check_items(qa_markdown, "Human QA 체크리스트", blank_status="pending")
    qa_request = _extract_section_markdown(qa_markdown, "QA 요청사항")
    qa_plan = _extract_section_markdown(qa_markdown, "QA Plan")
    qa_plan_coverage = _extract_section_markdown(qa_markdown, "QA Plan 커버리지")
    api_summary = _extract_section_markdown(qa_markdown, "API Smoke Test 결과")
    evidence_items = _load_screenshot_evidence(screenshot_dir)
    screenshots = _render_screenshots(screenshot_dir, evidence_items)
    appendix = _render_appendix(qa_markdown, playwright_markdown)
    pass_count = sum(1 for item in auto_checks if item["status"] == "pass")
    fail_count = sum(1 for item in auto_checks if item["status"] == "fail")
    result = metadata.get("result", "unknown")
    result_class = "pass" if result == "pass" and fail_count == 0 else "fail"

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
    .result-badge {{
      border-radius: 999px;
      display: inline-block;
      font-size: 12px;
      font-weight: 800;
      margin: 8px 0 2px;
      padding: 5px 10px;
    }}
    .result-badge.pass {{
      background: #dff3df;
      color: #1f5b29;
    }}
    .result-badge.fail {{
      background: #f8ded8;
      color: #8a2c1d;
    }}
    .summary-grid {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin: 14px 0 20px;
    }}
    .summary-card {{
      background: #fffaf1;
      border: 1px solid #e3dacb;
      border-radius: 10px;
      padding: 12px;
    }}
    .summary-card strong {{
      display: block;
      font-size: 11px;
      color: #6c5b44;
      margin-bottom: 4px;
    }}
    .summary-card span {{
      font-size: 13px;
      font-weight: 700;
    }}
    .callout {{
      background: #edf6ed;
      border-left: 4px solid #3d7a47;
      border-radius: 8px;
      margin: 12px 0 18px;
      padding: 12px 14px;
    }}
    .risk {{
      background: #fff6dd;
      border-left-color: #b27718;
    }}
    table {{
      border-collapse: collapse;
      margin: 12px 0 18px;
      width: 100%;
    }}
    th, td {{
      border-bottom: 1px solid #e2d9cc;
      font-size: 11px;
      padding: 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #f4eee3;
      color: #354235;
      font-size: 10px;
      text-transform: uppercase;
    }}
    .status {{
      border-radius: 999px;
      display: inline-block;
      font-size: 10px;
      font-weight: 800;
      padding: 2px 7px;
      white-space: nowrap;
    }}
    .status.pass {{
      background: #dff3df;
      color: #1f5b29;
    }}
    .status.fail {{
      background: #f8ded8;
      color: #8a2c1d;
    }}
    .status.pending {{
      background: #f4ead2;
      color: #755417;
    }}
    .human-list li {{
      margin-bottom: 6px;
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
    .screenshot-kind {{
      color: #8a5b3f;
      font-size: 11px;
      font-weight: 800;
      margin: 0 0 4px;
    }}
    .screenshot img {{
      border: 1px solid #d8d0c2;
      border-radius: 12px;
      max-width: 100%;
    }}
    figcaption {{
      color: #3b463b;
      font-size: 12px;
      margin-top: 8px;
    }}
    .appendix {{
      break-before: page;
    }}
	  </style>
</head>
<body>
  <section class="cover">
	    <p class="eyebrow">myMentalCare QA Report</p>
	    <h1>{html.escape(title)}</h1>
	    <p class="result-badge {result_class}">자동 QA 결과: {html.escape(result.upper())}</p>
	    <p>GitHub Issue: #{issue_number or "unknown"}</p>
	    <p>사람 검토자가 핵심 결론, 확인 항목, 자동 검증 근거를 빠르게 판단할 수 있도록 정리했습니다.</p>
	  </section>
	  <section>
	    <h1>최종 QA 결론</h1>
	    <div class="summary-grid">
	      {_summary_card("작업 타입", metadata.get("issue_type", "unknown"))}
	      {_summary_card("브랜치", metadata.get("branch", "unknown"))}
	      {_summary_card("확인 대상", metadata.get("확인 URL", "unknown"))}
	      {_summary_card("자동 검증", f"{pass_count}개 통과 / {fail_count}개 실패")}
	    </div>
	    <div class="callout">
	      <p><strong>판정:</strong> 자동 QA는 {html.escape(result)}입니다. 아래 자동 검증 항목과 브라우저 증거를 기준으로 통과 근거를 확인하세요.</p>
	    </div>
	    {_render_risk_note(human_checks, fail_count)}
	  </section>
	  {_render_qa_plan(qa_plan, qa_plan_coverage)}
	  <section>
	    <h1>사람 QA 체크리스트</h1>
	    <p>자동화가 최종 판단하지 못하는 항목입니다. 이 섹션을 기준으로 직접 승인 여부를 결정하세요.</p>
	    {_render_check_table(human_checks, pending_label="확인 필요", css_class="human-list")}
	  </section>
	  <section>
	    <h1>자동 검증 요약</h1>
	    {_render_check_table(auto_checks, pending_label="미확인")}
	  </section>
	  {_render_qa_request(qa_request)}
	  {_render_api_summary(api_summary)}
	  {_render_evidence_overview(evidence_items)}
	  {screenshots}
	  {appendix}
	</body>
	</html>"""


def _extract_report_metadata(markdown: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in markdown.splitlines():
        if line.startswith("## "):
            break
        match = re.match(r"^-\s+([^:]+):\s+(.+)$", line.strip())
        if not match:
            continue
        metadata[match.group(1).strip()] = _strip_inline_markup(match.group(2).strip())
    return metadata


def _strip_inline_markup(value: str) -> str:
    return value.strip().strip("`")


def _extract_section_lines(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    collected: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped == f"## {heading}":
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section:
            collected.append(line)
    return collected


def _extract_section_markdown(markdown: str, heading: str) -> str:
    return "\n".join(_extract_section_lines(markdown, heading)).strip()


def _extract_prefixed_sections(markdown: str, prefix: str) -> list[str]:
    lines = markdown.splitlines()
    sections: list[list[str]] = []
    current: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"## {prefix}"):
            if current:
                sections.append(current)
            current = [line]
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            sections.append(current)
            current = []
            in_section = False
        if in_section:
            current.append(line)
    if current:
        sections.append(current)
    return ["\n".join(section).strip() for section in sections]


def _extract_check_items(markdown: str, heading: str, blank_status: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for line in _extract_section_lines(markdown, heading):
        match = re.match(r"^\s*[-*]\s+\[([^\]]*)\]\s+(.+)$", line)
        if not match:
            continue
        marker = match.group(1).strip().lower()
        if marker in {"v", "x"}:
            status = "pass"
        elif marker:
            status = "fail"
        else:
            status = blank_status
        items.append({"status": status, "text": match.group(2).strip()})
    return items


def _summary_card(label: str, value: str) -> str:
    return (
        "<div class=\"summary-card\">"
        f"<strong>{html.escape(label)}</strong>"
        f"<span>{html.escape(value)}</span>"
        "</div>"
    )


def _render_risk_note(human_checks: list[dict[str, str]], fail_count: int) -> str:
    if fail_count:
        return (
            "<div class=\"callout risk\">"
            f"<p><strong>주의:</strong> 자동 검증 실패 항목이 {fail_count}개 있습니다. "
            "실패 원인을 확인하기 전에는 승인하지 마세요.</p>"
            "</div>"
        )
    if human_checks:
        return (
            "<div class=\"callout risk\">"
            "<p><strong>남은 판단:</strong> 자동 검증은 통과했지만, 사람 QA 체크리스트 항목은 "
            "직접 확인해야 최종 승인할 수 있습니다.</p>"
            "</div>"
        )
    return ""


def _render_check_table(
    items: list[dict[str, str]],
    pending_label: str,
    css_class: str = "",
) -> str:
    if not items:
        return "<p>기록된 항목이 없습니다.</p>"
    rows = []
    for index, item in enumerate(items, start=1):
        status = item["status"]
        label = {"pass": "통과", "fail": "실패", "pending": pending_label}.get(status, status)
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td><span class=\"status {html.escape(status)}\">{html.escape(label)}</span></td>"
            f"<td>{_inline_markdown(item['text'])}</td>"
            "</tr>"
        )
    return (
        f"<table class=\"{html.escape(css_class)}\">"
        "<thead><tr><th>#</th><th>상태</th><th>검증 내용</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _render_qa_request(markdown: str) -> str:
    if not markdown:
        return ""
    return f"<section><h1>QA 요청사항</h1>{_markdown_to_html(markdown)}</section>"


def _render_qa_plan(plan_markdown: str, coverage_markdown: str) -> str:
    if not plan_markdown and not coverage_markdown:
        return ""
    plan_html = _markdown_to_html(plan_markdown) if plan_markdown else ""
    coverage_html = _markdown_to_html(coverage_markdown) if coverage_markdown else ""
    return (
        "<section><h1>기능별 QA Plan</h1>"
        "<p>기획/설계안에서 추출한 이번 작업 전용 검증 기준입니다.</p>"
        f"{plan_html}"
        f"{coverage_html}"
        "</section>"
    )


def _render_api_summary(markdown: str) -> str:
    if not markdown:
        return ""
    return f"<section><h1>API/시나리오 검증 요약</h1>{_markdown_to_html(markdown)}</section>"


def _render_evidence_overview(evidence_items: list[dict[str, str]]) -> str:
    if not evidence_items:
        return ""
    rows: list[str] = []
    for index, item in enumerate(evidence_items, start=1):
        kind = _evidence_kind_label(str(item.get("kind") or "evidence"))
        title = str(item.get("title") or item.get("file_name") or "브라우저 증거")
        description = str(item.get("description") or "")
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td><span class=\"status pending\">{html.escape(kind)}</span></td>"
            f"<td>{html.escape(title)}</td>"
            f"<td>{html.escape(description)}</td>"
            "</tr>"
        )
    return (
        "<section><h1>브라우저 증거 요약</h1>"
        "<p>각 캡처가 어떤 기능 단계와 판단 근거를 보여주는지 먼저 요약합니다.</p>"
        "<table><thead><tr><th>#</th><th>유형</th><th>캡처 제목</th><th>관찰 포인트</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def _evidence_kind_label(kind: str) -> str:
    return {
        "success": "정상",
        "edge": "엣지",
        "failure": "실패",
        "legacy": "기존",
    }.get(kind, kind)


def _render_appendix(qa_markdown: str, playwright_markdown: str) -> str:
    command_sections = _extract_prefixed_sections(qa_markdown, "Command:")
    blocks: list[str] = []
    if command_sections:
        blocks.append("<section class=\"appendix\"><h1>상세 로그 부록</h1>")
        blocks.append("<p>아래 내용은 재현과 감사 목적의 원본 명령 로그입니다.</p>")
        blocks.extend(_markdown_to_html(section) for section in command_sections)
        blocks.append("</section>")
    if playwright_markdown:
        blocks.append("<section class=\"appendix\"><h1>Playwright 원본 보고서 위치</h1>")
        blocks.append("<p>중복을 줄이기 위해 원본 Playwright 상세 보고서는 별도 artifact로 유지합니다.</p>")
        blocks.append("</section>")
    return "\n".join(blocks)


# 스크린샷 디렉토리의 PNG 파일을 PDF 보고서 이미지 섹션으로 렌더링한다.
def _render_screenshots(screenshot_dir: Path, evidence_items: list[dict[str, str]] | None = None) -> str:
    if not screenshot_dir.exists():
        return ""

    evidence_items = evidence_items if evidence_items is not None else _load_screenshot_evidence(screenshot_dir)
    if not evidence_items:
        evidence_items = [
            {
                "file_name": image_path.name,
                "title": image_path.name,
                "description": "이전 형식의 브라우저 캡처입니다. 기능 단계 설명 메타데이터가 없어 파일명 기준으로 표시합니다.",
                "kind": "legacy",
            }
            for image_path in sorted(screenshot_dir.glob("*.png"))
        ]
    if not evidence_items:
        return ""

    blocks: list[str] = ["<section><h1>브라우저 기능 검증 캡처</h1>"]
    for index, item in enumerate(evidence_items, start=1):
        file_name = str(item.get("file_name", ""))
        image_path = screenshot_dir / file_name
        if not file_name or not image_path.exists():
            continue
        data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        title = str(item.get("title") or image_path.name)
        description = str(item.get("description") or "설명이 없는 브라우저 검증 캡처입니다.")
        kind = str(item.get("kind") or "evidence")
        blocks.append(
            "<figure class=\"screenshot\">"
            f"<p class=\"screenshot-kind\">검증 단계 {index} · {html.escape(_evidence_kind_label(kind))}</p>"
            f"<h2>{html.escape(title)}</h2>"
            f"<img src=\"data:image/png;base64,{data}\" alt=\"{html.escape(title)}\" />"
            f"<figcaption>{html.escape(description)}</figcaption>"
            "</figure>"
        )
    blocks.append("</section>")
    return "\n".join(blocks)


def _load_screenshot_evidence(screenshot_dir: Path) -> list[dict[str, str]]:
    evidence_path = screenshot_dir / "evidence.json"
    if not evidence_path.exists():
        return []
    try:
        parsed = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


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
