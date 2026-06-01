import html
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.db.models import Artifact, Run, StateTransition, Task
from orchestrator.db.session import get_db
from orchestrator.services.orchestration import OrchestrationService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# 작업 목록을 서버 사이드 HTML로 렌더링한다.
@router.get("", response_class=HTMLResponse)
def dashboard_home(include_internal: bool = False, db: Session = Depends(get_db)) -> HTMLResponse:
    query = select(Task).order_by(Task.updated_at.desc()).limit(50)
    if not include_internal:
        query = (
            select(Task)
            .where(Task.github_issue_number.is_not(None))
            .order_by(Task.updated_at.desc())
            .limit(50)
        )
    tasks = list(db.scalars(query))
    latest_runs = _latest_runs_by_task(db, [task.id for task in tasks])
    rows = "\n".join(_task_row(task, latest_runs.get(task.id)) for task in tasks)
    toggle_href = "/dashboard" if include_internal else "/dashboard?include_internal=true"
    toggle_label = "GitHub 이슈만 보기" if include_internal else "내부 task 포함"
    return HTMLResponse(
        _page(
            title="AI Harness Dashboard",
            active="tasks",
            content=f"""
            <section class="toolbar">
              <div>
                <p class="eyebrow">Human-in-the-loop control panel</p>
                <h1>작업 목록</h1>
              </div>
              <div class="button-row compact">
                <a class="button secondary" href="{toggle_href}">{toggle_label}</a>
                <a class="button secondary" href="/health">Health 확인</a>
              </div>
            </section>
            <p class="hint">
              기본 목록은 GitHub issue number가 있는 실제 StudyHub 작업만 보여줍니다.
              과거 테스트/수동 task는 “내부 task 포함”에서 확인할 수 있습니다.
            </p>
            <section class="panel">
              <table>
                <thead>
                  <tr>
                    <th>Issue</th>
                    <th>작업</th>
                    <th>상태</th>
                    <th>마지막 실행</th>
                    <th>다음 추천</th>
                  </tr>
                </thead>
                <tbody>{rows or _empty_row()}</tbody>
              </table>
            </section>
            """,
        )
    )


# 특정 작업의 실행 이력, 산출물, 명령 패널을 렌더링한다.
@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def dashboard_task_detail(
    task_id: str,
    message: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

    service = OrchestrationService(db)
    runs = list(
        db.scalars(
            select(Run).where(Run.task_id == task.id).order_by(Run.started_at.desc()).limit(20)
        )
    )
    artifacts = list(
        db.scalars(
            select(Artifact).where(Artifact.task_id == task.id).order_by(Artifact.created_at.desc())
        )
    )
    transitions = list(
        db.scalars(
            select(StateTransition)
            .where(StateTransition.task_id == task.id)
            .order_by(StateTransition.created_at.desc())
            .limit(12)
        )
    )
    return HTMLResponse(
        _page(
            title=task.title,
            active="detail",
            content=f"""
            {_notice(message, error)}
            <section class="toolbar">
              <div>
                <p class="eyebrow">Task ID: {_e(task.id)}</p>
                <h1>{_e(task.title)}</h1>
              </div>
              <a class="button secondary" href="/dashboard">목록으로</a>
            </section>
            <section class="grid">
              <article class="panel">
                <h2>현재 상태</h2>
                <dl class="kv">
                  <dt>GitHub Issue</dt><dd>{_issue_link(task)}</dd>
                  <dt>State</dt><dd><span class="pill">{_e(task.state)}</span></dd>
                  <dt>다음 추천</dt><dd>{_e(service._next_command_for_state(task.state))}</dd>
                  <dt>Updated</dt><dd>{_e(service._format_dt(task.updated_at))}</dd>
                </dl>
              </article>
              <article class="panel">
                <h2>명령 실행</h2>
                {_command_panel(task)}
              </article>
            </section>
            <section class="grid three">
              <article class="panel">
                <h2>Run Timeline</h2>
                {_run_list(service, runs)}
              </article>
              <article class="panel">
                <h2>Artifacts</h2>
                {_artifact_list(artifacts)}
              </article>
              <article class="panel">
                <h2>State 변경</h2>
                {_transition_list(service, transitions)}
              </article>
            </section>
            """,
        )
    )


# 대시보드 버튼에서 들어온 명령을 기존 OrchestrationService 명령으로 위임한다.
@router.post("/tasks/{task_id}/commands/{command}")
async def dashboard_run_command(
    task_id: str,
    command: str,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

    try:
        form = _parse_urlencoded_body(await request.body())
        message = _execute_dashboard_command(db, task, command, form)
        return _redirect_to_task(task.id, message=message)
    except Exception as exc:
        return _redirect_to_task(task.id, error=str(exc))


# 최근 run을 task id 기준으로 조회해 목록 화면에서 즉시 보여준다.
def _latest_runs_by_task(db: Session, task_ids: list[str]) -> dict[str, Run]:
    if not task_ids:
        return {}
    runs = list(
        db.scalars(
            select(Run).where(Run.task_id.in_(task_ids)).order_by(Run.started_at.desc())
        )
    )
    latest: dict[str, Run] = {}
    for run in runs:
        latest.setdefault(run.task_id, run)
    return latest


# 작업 목록 테이블의 한 행을 생성한다.
def _task_row(task: Task, latest_run: Run | None) -> str:
    run_label = "실행 없음"
    if latest_run:
        run_label = f"{latest_run.agent_name} / {latest_run.status}"
    next_command = OrchestrationService.__new__(OrchestrationService)._next_command_for_state(task.state)
    issue = f"#{task.github_issue_number}" if task.github_issue_number else "-"
    return f"""
    <tr>
      <td>{_e(issue)}</td>
      <td><a href="/dashboard/tasks/{_e(task.id)}">{_e(task.title)}</a></td>
      <td><span class="pill">{_e(task.state)}</span></td>
      <td>{_e(run_label)}</td>
      <td><code>{_e(next_command)}</code></td>
    </tr>
    """


# 작업이 없을 때 표시할 빈 행을 생성한다.
def _empty_row() -> str:
    return '<tr><td colspan="5" class="empty">아직 등록된 작업이 없습니다.</td></tr>'


# task command 요청을 실제 하네스 명령 실행으로 변환한다.
def _execute_dashboard_command(
    db: Session,
    task: Task,
    command: str,
    form: dict[str, str],
) -> str:
    issue_number = _require_issue_number(task)
    labels = _labels_from_task(task)
    note = form.get("note", "").strip()
    service = OrchestrationService(db)
    if command == "plan":
        result = service.run_plan_for_github_issue(
            issue_number, task.title, task.body, task.github_issue_url or "", issue_labels=labels
        )
    elif command == "replan":
        result = service.run_replan_for_github_issue(
            issue_number,
            task.title,
            task.body,
            task.github_issue_url or "",
            note or "대시보드에서 재설계가 요청되었습니다.",
            issue_labels=labels,
        )
    elif command == "develop":
        result = service.run_develop_for_github_issue(
            issue_number, task.title, task.body, task.github_issue_url or "", issue_labels=labels
        )
    elif command == "fix-develop":
        result = service.run_fix_develop_for_github_issue(
            issue_number, task.title, task.body, task.github_issue_url or "", issue_labels=labels
        )
    elif command == "qa":
        result = service.run_qa_for_github_issue(
            issue_number,
            task.title,
            task.body,
            task.github_issue_url or "",
            issue_labels=labels,
            qa_request=note or "대시보드에서 QA가 요청되었습니다.",
        )
    elif command == "re-qa":
        result = service.rerun_qa_for_github_issue(
            issue_number,
            task.title,
            task.body,
            task.github_issue_url or "",
            issue_labels=labels,
            qa_request=note or "대시보드에서 QA 재검증이 요청되었습니다.",
        )
    elif command == "refactor":
        result = service.run_refactor_for_github_issue(
            issue_number,
            task.title,
            task.body,
            task.github_issue_url or "",
            refactor_request=note or "대시보드에서 리팩터링이 요청되었습니다.",
            issue_labels=labels,
        )
    elif command == "status":
        result = service.comment_status_for_github_issue(
            issue_number, task.title, task.body, task.github_issue_url or "", issue_labels=labels
        )
    elif command == "cancel":
        result = service.cancel_github_issue_task(
            issue_number,
            task.title,
            task.body,
            task.github_issue_url or "",
            issue_labels=labels,
            reason=note or "대시보드에서 작업 중지가 요청되었습니다.",
        )
    else:
        raise ValueError(f"지원하지 않는 대시보드 명령입니다: {command}")
    if isinstance(result, dict):
        return result.get("message") or result.get("reason") or result.get("status") or "명령을 처리했습니다."
    return result.message


# task에 GitHub issue number가 없으면 명령 실행을 중단한다.
def _require_issue_number(task: Task) -> int:
    if task.github_issue_number is None:
        raise ValueError("GitHub issue number가 없는 작업은 대시보드 명령을 실행할 수 없습니다.")
    return task.github_issue_number


# task body의 Harness Metadata에서 labels 값을 복원한다.
def _labels_from_task(task: Task) -> list[str]:
    labels: list[str] = []
    for line in task.body.splitlines():
        stripped = line.strip()
        if stripped.startswith("- labels:"):
            raw = stripped.removeprefix("- labels:").strip()
            labels = [item.strip() for item in raw.split(",") if item.strip() and item.strip() != "none"]
    return labels


# x-www-form-urlencoded 본문을 단순 문자열 dict로 파싱한다.
def _parse_urlencoded_body(raw_body: bytes) -> dict[str, str]:
    parsed = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


# 작업 상세 화면으로 flash 메시지를 포함해 리다이렉트한다.
def _redirect_to_task(task_id: str, message: str | None = None, error: str | None = None) -> RedirectResponse:
    params = {key: value for key, value in {"message": message, "error": error}.items() if value}
    suffix = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"/dashboard/tasks/{task_id}{suffix}", status_code=303)


# 명령 실행 버튼과 메모 입력 UI를 생성한다.
def _command_panel(task: Task) -> str:
    commands = [
        ("plan", "Plan"),
        ("replan", "Replan"),
        ("develop", "Develop"),
        ("fix-develop", "Fix Develop"),
        ("qa", "System QA"),
        ("re-qa", "Re-QA"),
        ("refactor", "Refactor"),
        ("status", "Status Comment"),
        ("cancel", "Cancel"),
    ]
    buttons = "\n".join(
        f'<button class="button" type="submit" formaction="/dashboard/tasks/{_e(task.id)}/commands/{_e(command)}">{_e(label)}</button>'
        for command, label in commands
    )
    return f"""
    <form method="post" class="command-form">
      <label for="note">요청 메모</label>
      <textarea id="note" name="note" rows="5" placeholder="replan, refactor, qa 요청사항을 적습니다."></textarea>
      <div class="button-row">{buttons}</div>
    </form>
    """


# run 목록을 최신순으로 렌더링한다.
def _run_list(service: OrchestrationService, runs: list[Run]) -> str:
    if not runs:
        return '<p class="empty">아직 실행 이력이 없습니다.</p>'
    return "<ol class=\"timeline\">" + "\n".join(_run_item(service, run) for run in runs) + "</ol>"


# run 하나의 상태와 요약을 렌더링한다.
def _run_item(service: OrchestrationService, run: Run) -> str:
    error = f"<p class=\"danger\">{_e(run.error)}</p>" if run.error else ""
    return f"""
    <li>
      <strong>{_e(run.agent_name)} · {_e(run.status)}</strong>
      <span>{_e(service._format_dt(run.started_at))}</span>
      <p>{_e(run.summary)}</p>
      {error}
    </li>
    """


# artifact 목록을 로컬 경로 중심으로 렌더링한다.
def _artifact_list(artifacts: list[Artifact]) -> str:
    if not artifacts:
        return '<p class="empty">아직 산출물이 없습니다.</p>'
    items = []
    for artifact in artifacts:
        path = Path(artifact.path)
        open_command = f'open -a "IntelliJ IDEA" {path}'
        items.append(
            f"""
            <li>
              <strong>{_e(artifact.kind)}</strong>
              <code>{_e(str(path))}</code>
              <small>{_e(open_command)}</small>
            </li>
            """
        )
    return "<ul class=\"artifact-list\">" + "\n".join(items) + "</ul>"


# state transition 목록을 렌더링한다.
def _transition_list(service: OrchestrationService, transitions: list[StateTransition]) -> str:
    if not transitions:
        return '<p class="empty">상태 변경 이력이 없습니다.</p>'
    items = [
        f"""
        <li>
          <strong>{_e(item.from_state or 'none')} → {_e(item.to_state)}</strong>
          <span>{_e(service._format_dt(item.created_at))}</span>
          <p>{_e(item.reason)}</p>
        </li>
        """
        for item in transitions
    ]
    return "<ol class=\"timeline\">" + "\n".join(items) + "</ol>"


# GitHub issue 링크를 안전한 HTML로 만든다.
def _issue_link(task: Task) -> str:
    if not task.github_issue_url:
        return "-"
    label = f"#{task.github_issue_number}" if task.github_issue_number else task.github_issue_url
    return f'<a href="{_e(task.github_issue_url)}" target="_blank" rel="noreferrer">{_e(label)}</a>'


# 성공 또는 실패 flash notice를 렌더링한다.
def _notice(message: str | None, error: str | None) -> str:
    if error:
        return f'<div class="notice error">{_e(error)}</div>'
    if message:
        return f'<div class="notice success">{_e(message)}</div>'
    return ""


# 공통 HTML layout과 스타일을 생성한다.
def _page(title: str, active: str, content: str) -> str:
    return f"""
    <!doctype html>
    <html lang="ko">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>{_e(title)}</title>
        <style>{_style()}</style>
      </head>
      <body data-active="{_e(active)}">
        <header class="topbar">
          <a class="brand" href="/dashboard">AI Harness</a>
          <nav>
            <a href="/dashboard">Tasks</a>
            <a href="/health">Health</a>
          </nav>
        </header>
        <main>{content}</main>
      </body>
    </html>
    """


# 대시보드 MVP에 필요한 CSS를 반환한다.
def _style() -> str:
    return """
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #0f141b; color: #e8edf4; }
    a { color: #93c5fd; text-decoration: none; }
    a:hover { text-decoration: underline; }
    main { width: min(1440px, calc(100vw - 48px)); margin: 0 auto; padding: 28px 0 48px; }
    .topbar { height: 58px; display: flex; align-items: center; justify-content: space-between; padding: 0 24px; border-bottom: 1px solid #273241; background: #111820; position: sticky; top: 0; z-index: 2; }
    .brand { color: #f8fafc; font-weight: 800; letter-spacing: 0; }
    nav { display: flex; gap: 18px; font-size: 14px; }
    .toolbar { display: flex; justify-content: space-between; gap: 16px; align-items: flex-end; margin-bottom: 18px; }
    .eyebrow { color: #94a3b8; font-size: 13px; margin: 0 0 6px; }
    h1 { font-size: 26px; line-height: 1.25; margin: 0; letter-spacing: 0; }
    h2 { font-size: 16px; line-height: 1.35; margin: 0 0 16px; letter-spacing: 0; }
    .panel { border: 1px solid #273241; background: #151d27; border-radius: 8px; padding: 18px; overflow: hidden; }
    .grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 0.62fr); gap: 18px; margin-bottom: 18px; }
    .grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); align-items: start; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { text-align: left; padding: 13px 12px; border-bottom: 1px solid #273241; vertical-align: middle; }
    th { color: #94a3b8; font-weight: 600; }
    code { background: #0f141b; border: 1px solid #273241; border-radius: 6px; padding: 3px 6px; color: #cbd5e1; word-break: break-word; }
    .pill { display: inline-flex; align-items: center; min-height: 26px; padding: 3px 9px; border-radius: 999px; background: #1e293b; border: 1px solid #334155; color: #dbeafe; font-size: 13px; }
    .button { display: inline-flex; align-items: center; justify-content: center; min-height: 36px; padding: 8px 12px; border-radius: 7px; border: 1px solid #3b82f6; background: #2563eb; color: #fff; font-weight: 700; cursor: pointer; font-size: 13px; }
    .button.secondary { background: #1e293b; border-color: #334155; color: #e2e8f0; }
    .button:hover { filter: brightness(1.05); text-decoration: none; }
    .button-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .button-row.compact { margin-top: 0; }
    .hint { color: #94a3b8; margin: -6px 0 18px; font-size: 14px; }
    .command-form label { display: block; color: #cbd5e1; font-size: 13px; margin-bottom: 8px; }
    textarea { width: 100%; resize: vertical; border: 1px solid #334155; border-radius: 7px; background: #0f141b; color: #e2e8f0; padding: 10px; font: inherit; line-height: 1.5; }
    .kv { display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 12px; margin: 0; }
    .kv dt { color: #94a3b8; }
    .kv dd { margin: 0; min-width: 0; }
    .timeline, .artifact-list { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 14px; }
    .timeline li span { display: block; margin: 4px 0; color: #94a3b8; font-size: 12px; }
    .timeline li p { margin: 4px 0 0; color: #cbd5e1; line-height: 1.45; }
    .artifact-list li { display: grid; gap: 7px; }
    .artifact-list small { color: #94a3b8; word-break: break-word; }
    .empty { color: #94a3b8; }
    .notice { border-radius: 8px; padding: 12px 14px; margin-bottom: 18px; border: 1px solid; }
    .notice.success { border-color: #15803d; background: #052e16; color: #bbf7d0; }
    .notice.error { border-color: #b91c1c; background: #450a0a; color: #fecaca; }
    .danger { color: #fecaca !important; }
    @media (max-width: 980px) {
      main { width: min(100vw - 28px, 760px); }
      .toolbar, .grid, .grid.three { grid-template-columns: 1fr; display: grid; }
      table { min-width: 760px; }
      .panel { overflow-x: auto; }
    }
    """


# HTML escaping을 짧고 일관되게 적용한다.
def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
