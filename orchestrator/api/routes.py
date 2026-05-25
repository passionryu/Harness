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
        raise HTTPException(status_code=404, detail="task not found")
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
        raise HTTPException(status_code=401, detail="invalid GitHub webhook signature")

    payload = await request.json()

    if x_github_event == "issue_comment":
        return _handle_issue_comment_webhook(payload, db)

    if x_github_event != "issues":
        return {"status": "ignored", "reason": f"unsupported event: {x_github_event}"}

    action = payload.get("action")
    issue = payload.get("issue") or {}
    label = payload.get("label") or {}
    issue_labels = {item.get("name") for item in issue.get("labels", [])}

    is_plan_label = label.get("name") == settings.plan_trigger_label
    has_plan_label = settings.plan_trigger_label in issue_labels
    if action != "labeled" or not (is_plan_label and has_plan_label):
        return {"status": "ignored", "reason": "not a plan label trigger"}

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
    if not settings.github_token:
        raise HTTPException(status_code=400, detail="GITHUB_TOKEN is required for issue sync")

    try:
        issue = GitHubAdapter(settings.github_token).get_issue(
            settings.github_owner,
            settings.github_repo,
            issue_number,
        )
        labels = {item["name"] for item in issue.get("labels", [])}
        if settings.plan_trigger_label not in labels:
            raise ValueError(f"issue does not have label: {settings.plan_trigger_label}")

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
        return {"status": "ignored", "reason": "issue comment action is not created"}

    issue = payload.get("issue") or {}
    if issue.get("pull_request"):
        return {"status": "ignored", "reason": "pull request comments are not handled"}

    comment = payload.get("comment") or {}
    comment_body = comment.get("body") or ""
    if AI_HARNESS_GENERATED_MARKER in comment_body:
        return {"status": "ignored", "reason": "ai-harness generated comment"}

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if command == settings.qa_command:
        try:
            return OrchestrationService(db).run_qa_for_github_issue(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if command == settings.reqa_command:
        try:
            return OrchestrationService(db).rerun_qa_for_github_issue(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if command != settings.replan_command:
        return {"status": "ignored", "reason": "not an ai-harness issue command"}

    replan_request = command_body
    if not replan_request:
        replan_request = "Replan requested without additional detail."

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
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _parse_issue_comment_command(comment_body: str) -> tuple[str | None, str]:
    lines = comment_body.splitlines()
    for index, line in enumerate(lines):
        command = line.strip()
        if not command:
            continue
        remaining = "\n".join(lines[index + 1 :]).strip()
        return command, remaining
    return None, ""
