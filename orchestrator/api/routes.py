from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from orchestrator.api.schemas import EventResult, HumanApproval, ManualEvent, TaskCreate, TaskRead
from orchestrator.core.security import verify_github_signature
from orchestrator.core.settings import settings
from orchestrator.db.session import get_db
from orchestrator.services.github_adapter import GitHubAdapter
from orchestrator.services.orchestration import OrchestrationService

router = APIRouter()
AI_HARNESS_GENERATED_MARKER = "<!-- ai-harness-generated -->"


# 테스트 fake adapter와 실제 gh CLI adapter 생성 방식을 함께 지원한다.
def _github_adapter() -> GitHubAdapter:
    try:
        return GitHubAdapter(settings.github_token, settings.github_use_gh_cli)
    except TypeError:
        return GitHubAdapter(settings.github_token)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/tasks", response_model=TaskRead)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    return OrchestrationService(db).create_task(payload)


@router.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = OrchestrationService(db).get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    return task


@router.post("/events/manual", response_model=EventResult)
def manual_event(payload: ManualEvent, db: Session = Depends(get_db)):
    try:
        return OrchestrationService(db).handle_manual_event(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/approve-human-qa", response_model=EventResult)
def approve_human_qa(task_id: str, payload: HumanApproval, db: Session = Depends(get_db)):
    try:
        return OrchestrationService(db).approve_human_qa(task_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/webhooks/github", response_model=EventResult | dict[str, str])
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
    if not verify_github_signature(
        raw_body,
        x_hub_signature_256,
        settings.github_webhook_secret,
    ):
        raise HTTPException(status_code=401, detail="GitHub webhook 서명이 올바르지 않습니다.")

    payload = await request.json()

    if x_github_event == "issue_comment" and not settings.enable_github_comment_commands:
        return {"status": "ignored", "reason": "GitHub 댓글 명령 추적은 비활성화되어 있습니다."}

    if x_github_event == "issue_comment":
        return _handle_issue_comment_webhook(payload, db)

    if x_github_event != "issues":
        return {"status": "ignored", "reason": f"지원하지 않는 이벤트입니다: {x_github_event}"}

    action = payload.get("action")
    issue = payload.get("issue") or {}
    label = payload.get("label") or {}
    issue_labels = {item.get("name") for item in issue.get("labels", [])}

    is_plan_label = label.get("name") == settings.plan_trigger_label
    has_plan_label = settings.plan_trigger_label in issue_labels
    if action != "labeled" or not (is_plan_label and has_plan_label):
        return {"status": "ignored", "reason": "plan label 트리거가 아닙니다."}

    try:
        return OrchestrationService(db).run_plan_for_github_issue(
            issue_number=int(issue["number"]),
            title=issue.get("title") or "",
            body=issue.get("body") or "",
            issue_url=issue.get("html_url") or "",
            issue_labels=sorted(item for item in issue_labels if item),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sync/github/issues/{issue_number}/plan", response_model=EventResult)
def sync_github_issue_plan(
    issue_number: int,
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    if not settings.github_token and not settings.github_use_gh_cli:
        raise HTTPException(status_code=400, detail="이슈 동기화에는 GITHUB_TOKEN이 필요합니다.")

    try:
        issue = _github_adapter().get_issue(
            settings.github_owner,
            settings.github_repo,
            issue_number,
        )
        labels = {item["name"] for item in issue.get("labels", [])}
        if settings.plan_trigger_label not in labels:
            raise ValueError(f"이슈에 필요한 라벨이 없습니다: {settings.plan_trigger_label}")

        return OrchestrationService(db).run_plan_for_github_issue(
            issue_number=int(issue["number"]),
            title=issue.get("title") or "",
            body=issue.get("body") or "",
            issue_url=issue.get("html_url") or "",
            force=force,
            issue_labels=sorted(labels),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _handle_issue_comment_webhook(payload: dict, db: Session) -> EventResult | dict[str, str]:
    action = payload.get("action")
    if action != "created":
        return {"status": "ignored", "reason": "생성된 이슈 댓글이 아닙니다."}

    issue = payload.get("issue") or {}
    if issue.get("pull_request"):
        return {"status": "ignored", "reason": "Pull Request 댓글은 처리하지 않습니다."}

    comment = payload.get("comment") or {}
    comment_body = comment.get("body") or ""
    if AI_HARNESS_GENERATED_MARKER in comment_body:
        return {"status": "ignored", "reason": "AI Harness가 생성한 댓글입니다."}

    issue_number = int(issue["number"])
    issue_body = issue.get("body") or ""
    issue_title = issue.get("title") or ""
    issue_url = issue.get("html_url") or ""
    issue_labels = sorted(
        item.get("name") for item in issue.get("labels", []) if item.get("name")
    )
    command, command_body = _parse_issue_comment_command(comment_body)

    if command == settings.plan_command:
        try:
            return OrchestrationService(db).run_plan_for_github_issue(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
                comment_on_duplicate=True,
            )
        except ValueError as exc:
            return OrchestrationService(db).comment_command_failure(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
                command=command,
                error=str(exc),
            )

    if command == settings.develop_command:
        try:
            return OrchestrationService(db).run_develop_for_github_issue(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
            )
        except ValueError as exc:
            return OrchestrationService(db).comment_command_failure(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
                command=command,
                error=str(exc),
            )

    if command == settings.fix_develop_command:
        try:
            return OrchestrationService(db).run_fix_develop_for_github_issue(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
            )
        except ValueError as exc:
            return OrchestrationService(db).comment_command_failure(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
                command=command,
                error=str(exc),
            )

    if command == settings.refactor_command:
        refactor_request = command_body or "추가 상세 내용 없이 리팩터링이 요청되었습니다."
        try:
            return OrchestrationService(db).run_refactor_for_github_issue(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
                refactor_request=refactor_request,
            )
        except ValueError as exc:
            return OrchestrationService(db).comment_command_failure(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
                command=command,
                error=str(exc),
            )

    if command == settings.qa_command:
        qa_request = command_body or "추가 상세 내용 없이 QA가 요청되었습니다."
        try:
            return OrchestrationService(db).run_qa_for_github_issue(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
                qa_request=qa_request,
            )
        except ValueError as exc:
            return OrchestrationService(db).comment_command_failure(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
                command=command,
                error=str(exc),
            )

    if command == settings.reqa_command:
        qa_request = command_body or "추가 상세 내용 없이 재검증 QA가 요청되었습니다."
        try:
            return OrchestrationService(db).rerun_qa_for_github_issue(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
                qa_request=qa_request,
            )
        except ValueError as exc:
            return OrchestrationService(db).comment_command_failure(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
                command=command,
                error=str(exc),
            )

    if command == settings.status_command:
        return OrchestrationService(db).comment_status_for_github_issue(
            issue_number=issue_number,
            title=issue_title,
            body=issue_body,
            issue_url=issue_url,
            issue_labels=issue_labels,
        )

    if command == settings.cancel_command:
        return OrchestrationService(db).cancel_github_issue_task(
            issue_number=issue_number,
            title=issue_title,
            body=issue_body,
            issue_url=issue_url,
            issue_labels=issue_labels,
            reason=command_body or "cancel requested by GitHub comment",
        )

    if command != settings.replan_command:
        return {"status": "ignored", "reason": "AI Harness 이슈 명령이 아닙니다."}

    replan_request = command_body
    if not replan_request:
        replan_request = "추가 상세 내용 없이 재설계가 요청되었습니다."

    try:
        return OrchestrationService(db).run_replan_for_github_issue(
            issue_number=issue_number,
            title=issue_title,
            body=issue_body,
            issue_url=issue_url,
            issue_labels=issue_labels,
            replan_request=replan_request,
        )
    except ValueError as exc:
        return OrchestrationService(db).comment_command_failure(
            issue_number=issue_number,
            title=issue_title,
            body=issue_body,
            issue_url=issue_url,
            issue_labels=issue_labels,
            command=command,
            error=str(exc),
        )


def _parse_issue_comment_command(comment_body: str) -> tuple[str | None, str]:
    lines = comment_body.splitlines()
    for index, line in enumerate(lines):
        command = line.strip()
        if not command:
            continue
        remaining = "\n".join(lines[index + 1 :]).strip()
        return command, remaining
    return None, ""
