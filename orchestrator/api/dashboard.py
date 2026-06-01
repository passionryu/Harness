import html
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.core.settings import settings
from orchestrator.db.models import Artifact, Run, StateTransition, Task
from orchestrator.db.session import get_db
from orchestrator.services.github_adapter import GitHubAdapter
from orchestrator.services.orchestration import OrchestrationService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# 작업 목록을 서버 사이드 HTML로 렌더링한다.
@router.get("", response_class=HTMLResponse)
def dashboard_home(
    include_internal: bool = False,
    message: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
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
            {_notice(message, error)}
            <section class="toolbar">
              <div>
                <p class="eyebrow">Human-in-the-loop control panel</p>
                <h1>작업 목록</h1>
              </div>
              <div class="button-row compact">
                <form method="post" action="/dashboard/sync/github/issues">
                  <button class="button" type="submit">Sync All GitHub Issues</button>
                </form>
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


# GitHub repo의 open issue를 하네스 DB에 동기화한다.
@router.post("/sync/github/issues")
def dashboard_sync_github_issues(db: Session = Depends(get_db)) -> RedirectResponse:
    try:
        synced_count = _sync_github_issues(db)
        return _redirect_to_dashboard(message=f"GitHub issue {synced_count}개를 동기화했습니다.")
    except Exception as exc:
        return _redirect_to_dashboard(error=str(exc))


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
                <div class="task-workspace">
                  <section class="memo-box">
                    <div class="subhead">
                      <h2>작업 메모</h2>
                      <span>이 이슈를 진행하면서 남기는 개인 메모입니다.</span>
                    </div>
                    {_memo_panel(task)}
                  </section>
                  <section class="agent-board">
                    <div class="subhead">
                      <h2>Agent 호출 이력</h2>
                      <span>최신 실행순입니다. 카드를 누르면 반환 내용을 확인할 수 있습니다.</span>
                    </div>
                    {_agent_history(service, task, runs, artifacts)}
                  </section>
                </div>
              </article>
              <article class="panel">
                <h2>명령 실행</h2>
                <p class="section-help">
                  버튼을 누르면 GitHub 댓글 명령과 같은 하네스 작업이 실행됩니다.
                  요청 메모는 Replan, QA, Re-QA, Refactor, Cancel에서 사람이 남긴 지시사항으로 전달됩니다.
                </p>
                {_command_panel(task)}
              </article>
            </section>
            <section class="state-section">
              <article class="panel state-panel">
                <div class="subhead">
                  <h2>State 변경 흐름</h2>
                  <span>최신 변경이 위에 표시되며, 번호는 최초 변경부터 순서대로 부여됩니다.</span>
                </div>
                {_transition_list(service, transitions)}
              </article>
            </section>
            """,
        )
    )


# 대시보드 메모를 task body에 저장한다.
@router.post("/tasks/{task_id}/memo")
async def dashboard_save_memo(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

    form = _parse_urlencoded_body(await request.body())
    task.body = _replace_dashboard_memo(task.body, form.get("memo", ""))
    db.commit()
    return _redirect_to_task(task.id, message="작업 메모를 저장했습니다.")


# GitHub issue 목록을 읽어 신규 task를 Backlog로 만들고 기존 task 정보를 갱신한다.
def _sync_github_issues(db: Session) -> int:
    if not settings.github_token:
        raise ValueError("GitHub issue 동기화에는 GITHUB_TOKEN이 필요합니다.")

    service = OrchestrationService(db)
    issues = GitHubAdapter(settings.github_token).list_issues(
        settings.github_owner,
        settings.github_repo,
    )
    for issue in issues:
        labels = [item.get("name") for item in issue.get("labels", []) if item.get("name")]
        _upsert_synced_issue(service, issue, labels)
    db.commit()
    return len(issues)


# GitHub issue 하나를 하네스 task로 동기화하되 기존 상태는 보존한다.
def _upsert_synced_issue(
    service: OrchestrationService,
    issue: dict,
    labels: list[str],
) -> Task:
    issue_number = int(issue["number"])
    task = service.db.scalar(select(Task).where(Task.github_issue_number == issue_number))
    body = service._append_issue_metadata(
        issue.get("body") or "",
        labels,
        issue_number,
    )
    if task is None:
        task = Task(
            title=issue.get("title") or "",
            body=body,
            github_issue_url=issue.get("html_url") or "",
            github_issue_number=issue_number,
            state="Backlog",
            retry_limit=settings.agent_retry_limit,
        )
        service.db.add(task)
        service.db.flush()
        service._record_transition(task.id, None, task.state, "GitHub issue synced", "system")
        service._audit(
            task.id,
            None,
            "task.synced_from_github",
            {"issue_number": issue_number, "issue_url": task.github_issue_url},
        )
        return task

    task.title = issue.get("title") or task.title
    task.body = body
    task.github_issue_url = issue.get("html_url") or task.github_issue_url
    service._audit(
        task.id,
        None,
        "task.refreshed_from_github",
        {"issue_number": issue_number, "issue_url": task.github_issue_url},
    )
    return task


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


# task body에서 대시보드 메모 섹션을 추출한다.
def _dashboard_memo(body: str) -> str:
    return "\n".join(_extract_markdown_section(body, "Dashboard Memo")).strip()


# task body의 대시보드 메모 섹션을 새 내용으로 교체한다.
def _replace_dashboard_memo(body: str, memo: str) -> str:
    lines = body.rstrip().splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped == "## Dashboard Memo":
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("## "):
                index += 1
            continue
        output.append(lines[index])
        index += 1

    cleaned_memo = memo.strip()
    if cleaned_memo:
        if output and output[-1].strip():
            output.append("")
        output.extend(["## Dashboard Memo", cleaned_memo])
    return "\n".join(output).strip() + "\n"


# markdown body에서 특정 2단계 heading 아래의 내용을 반환한다.
def _extract_markdown_section(body: str, heading: str) -> list[str]:
    lines = body.splitlines()
    collected: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_section:
                break
            in_section = stripped.removeprefix("## ").strip() == heading
            continue
        if in_section:
            collected.append(line)
    return collected


# 작업 상세 화면으로 flash 메시지를 포함해 리다이렉트한다.
def _redirect_to_task(task_id: str, message: str | None = None, error: str | None = None) -> RedirectResponse:
    params = {key: value for key, value in {"message": message, "error": error}.items() if value}
    suffix = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"/dashboard/tasks/{task_id}{suffix}", status_code=303)


# 작업 목록 화면으로 flash 메시지를 포함해 리다이렉트한다.
def _redirect_to_dashboard(message: str | None = None, error: str | None = None) -> RedirectResponse:
    params = {key: value for key, value in {"message": message, "error": error}.items() if value}
    suffix = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"/dashboard{suffix}", status_code=303)


# 작업 메모 입력 패널을 렌더링한다.
def _memo_panel(task: Task) -> str:
    memo = _dashboard_memo(task.body)
    return f"""
    <form method="post" action="/dashboard/tasks/{_e(task.id)}/memo" class="memo-form">
      <textarea name="memo" rows="8" placeholder="예: 로그인 ID 정책은 4~20자, email은 선택값. QA 때 중복 loginId와 email nullable을 꼭 확인.">{_e(memo)}</textarea>
      <div class="memo-actions">
        <button class="button secondary" type="submit">메모 저장</button>
      </div>
    </form>
    """


# 에이전트 실행 이력을 클릭 가능한 카드와 모달로 렌더링한다.
def _agent_history(
    service: OrchestrationService,
    task: Task,
    runs: list[Run],
    artifacts: list[Artifact],
) -> str:
    if not runs:
        return '<p class="empty">아직 호출된 에이전트가 없습니다.</p>'
    artifact_map = _artifacts_by_run(artifacts)
    cards = "\n".join(_agent_card(service, run) for run in runs)
    modals = "\n".join(_agent_modal(service, task, run, artifact_map.get(run.id, [])) for run in runs)
    return f"""
    <div class="agent-list">{cards}</div>
    {modals}
    <script>
      document.querySelectorAll('[data-modal-open]').forEach((button) => {{
        button.addEventListener('click', () => {{
          const dialog = document.getElementById(button.dataset.modalOpen);
          if (dialog) dialog.showModal();
        }});
      }});
      document.querySelectorAll('[data-modal-close]').forEach((button) => {{
        button.addEventListener('click', () => button.closest('dialog')?.close());
      }});
    </script>
    """


# run id별 artifact 목록을 만든다.
def _artifacts_by_run(artifacts: list[Artifact]) -> dict[str, list[Artifact]]:
    grouped: dict[str, list[Artifact]] = {}
    for artifact in artifacts:
        if artifact.run_id:
            grouped.setdefault(artifact.run_id, []).append(artifact)
    return grouped


# 에이전트 실행 카드 하나를 렌더링한다.
def _agent_card(service: OrchestrationService, run: Run) -> str:
    status_class = _status_class(run.status)
    return f"""
    <button class="agent-card" type="button" data-modal-open="run-{_e(run.id)}">
      <span class="agent-main">
        <strong>{_e(run.agent_name)}</strong>
        <span class="status-dot {status_class}">{_e(run.status)}</span>
      </span>
      <span class="agent-time">{_e(service._format_dt(run.started_at))}</span>
      <span class="agent-summary">{_e(run.summary or '요약 없음')}</span>
    </button>
    """


# 에이전트 실행 상세 모달을 렌더링한다.
def _agent_modal(
    service: OrchestrationService,
    task: Task,
    run: Run,
    artifacts: list[Artifact],
) -> str:
    payload = _agent_return_payload(service, task, run, artifacts)
    artifact_lines = "\n".join(
        f"<li><code>{_e(artifact.kind)}</code> {_e(artifact.path)}</li>" for artifact in artifacts
    )
    artifact_section = (
        f"<ul class=\"modal-artifacts\">{artifact_lines}</ul>"
        if artifacts
        else '<p class="empty">이 run에 직접 연결된 artifact가 없습니다.</p>'
    )
    return f"""
    <dialog id="run-{_e(run.id)}" class="run-modal">
      <div class="modal-header">
        <div>
          <p class="eyebrow">Agent 반환 데이터</p>
          <h2>{_e(run.agent_name)} · {_e(run.status)}</h2>
        </div>
        <button class="icon-button" type="button" data-modal-close>닫기</button>
      </div>
      <div class="modal-body">
        <pre>{_e(payload)}</pre>
        <h3>연결된 산출물</h3>
        {artifact_section}
      </div>
    </dialog>
    """


# 모달에 표시할 에이전트 반환 데이터를 GitHub 댓글과 비슷한 구조로 만든다.
def _agent_return_payload(
    service: OrchestrationService,
    task: Task,
    run: Run,
    artifacts: list[Artifact],
) -> str:
    lines = [
        f"작업: {task.title}",
        f"Task ID: {task.id}",
        f"GitHub Issue: #{task.github_issue_number}" if task.github_issue_number else "GitHub Issue: 없음",
        "",
        "Agent 실행",
        f"- agent: {run.agent_name}",
        f"- status: {run.status}",
        f"- started_at: {service._format_dt(run.started_at)}",
        f"- finished_at: {service._format_dt(run.finished_at)}",
        "",
        "반환 요약",
        run.summary or "요약 없음",
    ]
    if run.error:
        lines.extend(["", "실패 이유", run.error])
    if artifacts:
        lines.extend(["", "상세 Artifacts"])
        lines.extend(f"- {artifact.kind}: {artifact.path}" for artifact in artifacts)
        lines.extend(["", "Artifact 주요 내용"])
        lines.extend(_artifact_preview_sections(run, artifacts))
    return "\n".join(lines)


# 에이전트가 GitHub 댓글에 담았던 핵심 artifact 내용을 모달에 함께 표시한다.
def _artifact_preview_sections(run: Run, artifacts: list[Artifact]) -> list[str]:
    selected_artifacts = _selected_artifacts_for_modal(run, artifacts)
    if not selected_artifacts:
        return ["- 미리볼 수 있는 artifact 파일이 없습니다."]

    sections: list[str] = []
    for artifact in selected_artifacts:
        label, _ = _artifact_label_and_description(artifact)
        sections.extend(
            [
                "",
                f"## {label} ({artifact.kind})",
                f"path: {artifact.path}",
                "",
                _read_artifact_preview(artifact),
            ]
        )
    return sections


# run 종류별로 모달에 우선 표시할 artifact를 고른다.
def _selected_artifacts_for_modal(run: Run, artifacts: list[Artifact]) -> list[Artifact]:
    preferred_by_agent = {
        "plan": [
            "architecture-doc",
            "sequence-diagram",
            "flow-chart",
            "edge-case-checklist",
        ],
        "dev": [
            "dev-status",
            "commit-plan",
            "test-report",
            "patch",
        ],
        "fix_develop": [
            "fix-develop-report",
        ],
        "qa": [
            "qa-report",
            "qa-checklist",
        ],
    }
    preferred = preferred_by_agent.get(run.agent_name, [])
    ordered: list[Artifact] = []
    for kind in preferred:
        ordered.extend(artifact for artifact in artifacts if artifact.kind == kind)
    if ordered:
        return ordered
    return artifacts[:4]


# artifact 파일 내용을 읽어 모달에서 안전하게 미리볼 수 있는 길이로 제한한다.
def _read_artifact_preview(artifact: Artifact, max_chars: int = 8000) -> str:
    path = Path(artifact.path)
    if not path.exists():
        return "파일을 찾을 수 없습니다. artifact 경로를 직접 확인하세요."
    content = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(content) <= max_chars:
        return content
    return f"{content[:max_chars]}\n\n... 내용이 길어 일부만 표시합니다."


# run 상태에 맞는 시각적 class를 반환한다.
def _status_class(status: str) -> str:
    return {
        "success": "ok",
        "failed": "bad",
        "needs_human": "wait",
        "running": "run",
    }.get(status, "idle")


# 명령 실행 버튼과 메모 입력 UI를 생성한다.
def _command_panel(task: Task) -> str:
    commands = [
        ("plan", "Plan", "최초 설계를 생성합니다. 이미 성공한 Plan이 있으면 중복 실행을 막습니다."),
        ("replan", "Replan", "기존 설계가 마음에 들지 않을 때 요청 메모를 반영해 다시 설계합니다."),
        ("develop", "Develop", "사람이 Plan을 승인하고 개발 에이전트를 실행합니다."),
        ("fix-develop", "Fix Develop", "최근 개발 실패 로그를 읽고 자동 복구를 시도합니다."),
        ("qa", "System QA", "개발 결과를 시스템 검증으로 넘깁니다. In Progress 상태에서 사용합니다."),
        ("re-qa", "Re-QA", "System QA 이후 같은 작업을 다시 검증합니다."),
        ("refactor", "Refactor", "이미 구현된 결과를 요청 메모 기준으로 구조 개선합니다."),
        ("status", "Status Comment", "현재 상태와 마지막 실행 결과를 GitHub 댓글로 남깁니다."),
        ("cancel", "Cancel", "작업을 중지 상태로 바꿉니다. 요청 메모에 중지 사유를 적습니다."),
    ]
    command_cards = "\n".join(
        _command_card(task, command, label, description)
        for command, label, description in commands
    )
    return f"""
    <form method="post" class="command-form">
      <label for="note">요청 메모</label>
      <textarea id="note" name="note" rows="5" placeholder="예: DDD 경계를 유지해서 controller DTO를 분리해줘. / QA에서 로그인 실패 케이스를 함께 봐줘."></textarea>
      <div class="command-grid">{command_cards}</div>
    </form>
    """


# 명령 버튼 하나와 사용 설명을 함께 렌더링한다.
def _command_card(task: Task, command: str, label: str, description: str) -> str:
    return f"""
    <div class="command-card">
      <button class="button" type="submit" formaction="/dashboard/tasks/{_e(task.id)}/commands/{_e(command)}">{_e(label)}</button>
      <p>{_e(description)}</p>
    </div>
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


# artifact 목록을 역할별 묶음과 설명 중심으로 렌더링한다.
def _artifact_list(artifacts: list[Artifact]) -> str:
    if not artifacts:
        return '<p class="empty">아직 산출물이 없습니다.</p>'
    groups = _group_artifacts(artifacts)
    sections = []
    for group_name, grouped_artifacts in groups.items():
        items = "\n".join(_artifact_item(artifact) for artifact in grouped_artifacts)
        sections.append(
            f"""
            <section class="artifact-group">
              <h3>{_e(group_name)}</h3>
              <ul class="artifact-list">{items}</ul>
            </section>
            """
        )
    return "\n".join(sections)


# artifact 경로와 종류를 기준으로 사람이 이해할 수 있는 묶음을 만든다.
def _group_artifacts(artifacts: list[Artifact]) -> dict[str, list[Artifact]]:
    group_order = ["Plan 산출물", "Dev 산출물", "QA 산출물", "기타 산출물"]
    groups: dict[str, list[Artifact]] = {name: [] for name in group_order}
    seen: set[tuple[str, str]] = set()
    for artifact in artifacts:
        key = (artifact.kind, artifact.path)
        if key in seen:
            continue
        seen.add(key)
        groups[_artifact_group_name(artifact)].append(artifact)
    return {name: items for name, items in groups.items() if items}


# artifact가 속한 하네스 실행 단계를 판별한다.
def _artifact_group_name(artifact: Artifact) -> str:
    path = artifact.path
    if "/plans/" in path or artifact.kind in {"architecture-doc", "flow", "flow-chart", "sequence-diagram", "edge-case-checklist"}:
        return "Plan 산출물"
    if "/qa/" in path or artifact.kind.startswith("qa-"):
        return "QA 산출물"
    if "/dev/" in path or artifact.kind in {"commit-plan", "dev-status", "patch", "test-report"}:
        return "Dev 산출물"
    return "기타 산출물"


# artifact 하나를 목적, 경로, 여는 명령과 함께 렌더링한다.
def _artifact_item(artifact: Artifact) -> str:
    path = Path(artifact.path)
    open_command = f'open -a "IntelliJ IDEA" {path}'
    label, description = _artifact_label_and_description(artifact)
    return f"""
    <li>
      <div class="artifact-heading">
        <strong>{_e(label)}</strong>
        <span>{_e(artifact.kind)}</span>
      </div>
      <p>{_e(description)}</p>
      <code>{_e(str(path))}</code>
      <small>IntelliJ에서 열기: <code>{_e(open_command)}</code></small>
    </li>
    """


# artifact kind를 사람이 읽기 좋은 이름과 설명으로 바꾼다.
def _artifact_label_and_description(artifact: Artifact) -> tuple[str, str]:
    mapping = {
        "architecture-doc": ("설계 요약", "작업 범위, 구현 방향, 미결정 사항을 보는 문서입니다."),
        "sequence-diagram": ("시퀀스 다이어그램", "사용자와 시스템 사이의 유스케이스 흐름을 순서대로 봅니다."),
        "flow": ("작업 흐름", "화면/API/상태가 어떤 순서로 이어지는지 텍스트로 정리한 문서입니다."),
        "flow-chart": ("플로우 차트", "분기와 흐름을 빠르게 이해하기 위한 다이어그램 문서입니다."),
        "edge-case-checklist": ("엣지 케이스 체크리스트", "구현 전후에 놓치기 쉬운 예외 케이스를 확인합니다."),
        "commit-plan": ("커밋 계획", "개발 에이전트가 어떤 단위로 커밋했거나 커밋할지 확인합니다."),
        "dev-status": ("개발 상태 보고서", "개발 runner가 어디까지 처리했고 어디서 멈췄는지 봅니다."),
        "patch": ("구현 패치", "코드 변경 diff를 확인합니다."),
        "test-report": ("개발 테스트 리포트", "개발 단계에서 실행한 테스트 명령과 결과를 봅니다."),
        "fix-develop-report": ("개발 실패 수정 리포트", "fix-develop이 실패 원인을 어떻게 분석하고 고쳤는지 봅니다."),
        "qa-report": ("시스템 QA 리포트", "자동 QA가 실제로 무엇을 검증했고 통과/실패했는지 확인합니다."),
        "qa-checklist": ("Human QA 체크리스트", "사람이 브라우저/API/DB에서 직접 확인할 항목입니다."),
    }
    if artifact.kind in mapping:
        return mapping[artifact.kind]
    return (artifact.kind, "에이전트가 남긴 보조 산출물입니다. 상세 내용은 파일을 열어 확인합니다.")


# state transition 목록을 렌더링한다.
def _transition_list(service: OrchestrationService, transitions: list[StateTransition]) -> str:
    if not transitions:
        return '<p class="empty">상태 변경 이력이 없습니다.</p>'
    total = len(transitions)
    items = []
    for index, item in enumerate(transitions):
        display_number = total - index
        connector = '<div class="state-arrow">↑ 이전 단계</div>' if index < total - 1 else ""
        items.append(
            f"""
            <li class="state-step">
              <div class="step-index">{display_number}</div>
              <div class="step-body">
                <div class="state-route">
                  <span>{_e(item.from_state or 'none')}</span>
                  <strong>→</strong>
                  <span>{_e(item.to_state)}</span>
                </div>
                <time>{_e(service._format_dt(item.created_at))}</time>
                <p>{_e(item.reason)}</p>
                {connector}
              </div>
            </li>
            """
        )
    return "<ol class=\"state-flow\">" + "\n".join(items) + "</ol>"


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
    .state-section { margin-top: 18px; }
    .state-panel { overflow: visible; }
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
    .button-row form { margin: 0; }
    .hint { color: #94a3b8; margin: -6px 0 18px; font-size: 14px; }
    .section-help { color: #94a3b8; line-height: 1.55; margin: -6px 0 14px; font-size: 14px; }
    .task-workspace { margin-top: 34px; display: grid; grid-template-columns: minmax(320px, 0.9fr) minmax(360px, 1.1fr); gap: 18px; align-items: start; }
    .memo-box, .agent-board { border-top: 1px solid #273241; padding-top: 18px; min-width: 0; }
    .subhead { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
    .subhead h2 { margin: 0; }
    .subhead span { color: #94a3b8; font-size: 12px; line-height: 1.4; text-align: right; }
    .memo-form { display: grid; gap: 10px; }
    .memo-actions { display: flex; justify-content: flex-end; }
    .agent-list { display: grid; gap: 10px; max-height: 360px; overflow: auto; padding-right: 4px; }
    .agent-card { width: 100%; text-align: left; display: grid; gap: 6px; border: 1px solid #273241; background: #111820; color: #e2e8f0; border-radius: 8px; padding: 11px; cursor: pointer; font: inherit; }
    .agent-card:hover { border-color: #60a5fa; background: #142033; }
    .agent-main { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
    .agent-time { color: #94a3b8; font-size: 12px; }
    .agent-summary { color: #cbd5e1; line-height: 1.4; font-size: 13px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .status-dot { border-radius: 999px; padding: 2px 8px; font-size: 12px; border: 1px solid #334155; color: #cbd5e1; }
    .status-dot.ok { border-color: #15803d; color: #bbf7d0; background: #052e16; }
    .status-dot.bad { border-color: #b91c1c; color: #fecaca; background: #450a0a; }
    .status-dot.wait { border-color: #b45309; color: #fde68a; background: #451a03; }
    .status-dot.run { border-color: #2563eb; color: #bfdbfe; background: #172554; }
    .run-modal { width: min(860px, calc(100vw - 36px)); border: 1px solid #334155; border-radius: 10px; background: #151d27; color: #e8edf4; padding: 0; box-shadow: 0 24px 80px rgba(0,0,0,0.5); }
    .run-modal::backdrop { background: rgba(2, 6, 23, 0.72); }
    .modal-header { display: flex; justify-content: space-between; gap: 18px; align-items: center; padding: 18px 20px; border-bottom: 1px solid #273241; }
    .modal-header h2 { margin: 0; }
    .icon-button { border: 1px solid #334155; background: #1e293b; color: #e2e8f0; border-radius: 7px; min-height: 34px; padding: 6px 10px; cursor: pointer; }
    .modal-body { padding: 18px 20px 20px; display: grid; gap: 16px; }
    .modal-body pre { margin: 0; white-space: pre-wrap; word-break: break-word; background: #0f141b; border: 1px solid #273241; border-radius: 8px; padding: 14px; color: #dbeafe; line-height: 1.55; max-height: 440px; overflow: auto; }
    .modal-body h3 { margin: 0; font-size: 15px; }
    .modal-artifacts { margin: 0; padding-left: 20px; display: grid; gap: 8px; color: #cbd5e1; }
    .command-form label { display: block; color: #cbd5e1; font-size: 13px; margin-bottom: 8px; }
    textarea { width: 100%; resize: vertical; border: 1px solid #334155; border-radius: 7px; background: #0f141b; color: #e2e8f0; padding: 10px; font: inherit; line-height: 1.5; }
    .command-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
    .command-card { border: 1px solid #273241; background: #111820; border-radius: 8px; padding: 10px; display: grid; gap: 8px; align-content: start; }
    .command-card .button { width: 100%; }
    .command-card p { margin: 0; color: #aab6c5; line-height: 1.45; font-size: 12px; }
    .kv { display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 12px; margin: 0; }
    .kv dt { color: #94a3b8; }
    .kv dd { margin: 0; min-width: 0; }
    .timeline, .artifact-list { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 14px; }
    .timeline li span { display: block; margin: 4px 0; color: #94a3b8; font-size: 12px; }
    .timeline li p { margin: 4px 0 0; color: #cbd5e1; line-height: 1.45; }
    .state-flow { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }
    .state-step { display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 12px; align-items: start; }
    .step-index { width: 34px; height: 34px; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; background: #2563eb; color: #fff; font-weight: 800; border: 1px solid #60a5fa; }
    .step-body { border: 1px solid #273241; border-radius: 8px; background: #111820; padding: 13px; display: grid; gap: 7px; }
    .state-route { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
    .state-route span { display: inline-flex; align-items: center; min-height: 26px; padding: 3px 9px; border-radius: 999px; background: #1e293b; border: 1px solid #334155; color: #dbeafe; font-size: 13px; }
    .state-route strong { color: #93c5fd; }
    .state-step time { color: #94a3b8; font-size: 12px; }
    .state-step p { margin: 0; color: #cbd5e1; line-height: 1.45; }
    .state-arrow { color: #64748b; font-size: 12px; padding-top: 2px; }
    .artifact-group { border-top: 1px solid #273241; padding-top: 14px; margin-top: 14px; }
    .artifact-group:first-of-type { border-top: 0; padding-top: 0; margin-top: 0; }
    .artifact-group h3 { margin: 0 0 10px; font-size: 14px; color: #dbeafe; letter-spacing: 0; }
    .artifact-list li { display: grid; gap: 7px; }
    .artifact-list p { margin: 0; color: #cbd5e1; line-height: 1.45; font-size: 13px; }
    .artifact-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .artifact-heading span { color: #94a3b8; font-size: 12px; }
    .artifact-list small { color: #94a3b8; word-break: break-word; }
    .empty { color: #94a3b8; }
    .notice { border-radius: 8px; padding: 12px 14px; margin-bottom: 18px; border: 1px solid; }
    .notice.success { border-color: #15803d; background: #052e16; color: #bbf7d0; }
    .notice.error { border-color: #b91c1c; background: #450a0a; color: #fecaca; }
    .danger { color: #fecaca !important; }
    @media (max-width: 980px) {
      main { width: min(100vw - 28px, 760px); }
      .toolbar, .grid, .grid.three { grid-template-columns: 1fr; display: grid; }
      .task-workspace { grid-template-columns: 1fr; }
      .subhead { display: grid; }
      .subhead span { text-align: left; }
      .command-grid { grid-template-columns: 1fr; }
      table { min-width: 760px; }
      .panel { overflow-x: auto; }
    }
    """


# HTML escaping을 짧고 일관되게 적용한다.
def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
