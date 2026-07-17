from fastapi import APIRouter, Header, HTTPException, Query, Request

from orchestrator.api.schemas import EventResult
from orchestrator.core.security import verify_github_signature
from orchestrator.core.settings import settings
from orchestrator.services.github_adapter import GitHubAdapter
from orchestrator.services.orchestration import OrchestrationService

router = APIRouter()
AI_HARNESS_GENERATED_MARKER = "<!-- ai-harness-generated -->"


def _github_adapter() -> GitHubAdapter:
    try:
        return GitHubAdapter(settings.github_token, settings.github_use_gh_cli)
    except TypeError:
        return GitHubAdapter(settings.github_token)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "stateless"}


@router.post("/webhooks/github", response_model=EventResult | dict[str, str])
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
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
        return _handle_issue_comment_webhook(payload)
    if x_github_event != "issues":
        return {"status": "ignored", "reason": f"지원하지 않는 이벤트입니다: {x_github_event}"}

    action = payload.get("action")
    issue = payload.get("issue") or {}
    label = payload.get("label") or {}
    issue_labels = {item.get("name") for item in issue.get("labels", [])}
    is_plan_label = label.get("name") == settings.plan_trigger_label
    has_plan_label = settings.plan_trigger_label in issue_labels
    if action != "labeled" or not (is_plan_label and has_plan_label):
        return {"status": "ignored", "reason": "design label 트리거가 아닙니다."}

    return OrchestrationService().run_plan_for_github_issue(
        issue_number=int(issue["number"]),
        title=issue.get("title") or "",
        body=issue.get("body") or "",
        issue_url=issue.get("html_url") or "",
        issue_labels=sorted(item for item in issue_labels if item),
    )


@router.post("/sync/github/issues/{issue_number}/plan", response_model=EventResult)
def sync_github_issue_plan(issue_number: int, force: bool = Query(default=False)):
    if not settings.github_token and not settings.github_use_gh_cli:
        raise HTTPException(status_code=400, detail="이슈 동기화에는 GITHUB_TOKEN 또는 gh CLI가 필요합니다.")
    issue = _github_adapter().get_issue(settings.github_owner, settings.github_repo, issue_number)
    labels = sorted(item.get("name") for item in issue.get("labels", []) if item.get("name"))
    return OrchestrationService().run_plan_for_github_issue(
        issue_number=int(issue["number"]),
        title=issue.get("title") or "",
        body=issue.get("body") or "",
        issue_url=issue.get("html_url") or "",
        force=force,
        issue_labels=labels,
    )


def _handle_issue_comment_webhook(payload: dict) -> EventResult | dict[str, str]:
    if payload.get("action") != "created":
        return {"status": "ignored", "reason": "생성된 이슈 댓글이 아닙니다."}

    issue = payload.get("issue") or {}
    if issue.get("pull_request"):
        return {"status": "ignored", "reason": "Pull Request 댓글은 처리하지 않습니다."}

    comment = payload.get("comment") or {}
    comment_body = comment.get("body") or ""
    if AI_HARNESS_GENERATED_MARKER in comment_body:
        return {"status": "ignored", "reason": "AI Harness가 생성한 댓글입니다."}

    command, command_body = _parse_issue_comment_command(comment_body)
    if not _is_harness_command(command):
        return {"status": "ignored", "reason": "AI Harness 이슈 명령이 아닙니다."}

    service = OrchestrationService()
    issue_number = int(issue["number"])
    issue_body = issue.get("body") or ""
    issue_title = issue.get("title") or ""
    issue_url = issue.get("html_url") or ""
    issue_labels = sorted(item.get("name") for item in issue.get("labels", []) if item.get("name"))

    try:
        if command in {settings.design_command, settings.plan_command}:
            result = service.run_plan_for_github_issue(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
                comment_on_duplicate=True,
            )
            if command == settings.plan_command:
                payload = result.model_dump()
                payload["warning"] = "@ai-harness plan은 deprecated입니다. @ai-harness design을 사용하세요."
                return payload
            return result
        if command in {settings.redesign_command, settings.replan_command}:
            return service.run_replan_for_github_issue(
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                issue_url=issue_url,
                issue_labels=issue_labels,
                replan_request=command_body or "추가 상세 내용 없이 재설계가 요청되었습니다.",
            )
        if command == settings.develop_command:
            return service.run_develop_for_github_issue(issue_number, issue_title, issue_body, issue_url, issue_labels)
        if command == settings.fix_develop_command:
            return service.run_fix_develop_for_github_issue(issue_number, issue_title, issue_body, issue_url, issue_labels)
        if command == settings.refactor_command:
            return service.run_refactor_for_github_issue(
                issue_number,
                issue_title,
                issue_body,
                issue_url,
                command_body or "추가 상세 내용 없이 리팩터링이 요청되었습니다.",
                issue_labels,
            )
        if command == settings.qa_command:
            return service.run_qa_for_github_issue(
                issue_number,
                issue_title,
                issue_body,
                issue_url,
                issue_labels,
                command_body or "추가 상세 내용 없이 QA가 요청되었습니다.",
            )
        if command == settings.reqa_command:
            return service.rerun_qa_for_github_issue(
                issue_number,
                issue_title,
                issue_body,
                issue_url,
                issue_labels,
                command_body or "추가 상세 내용 없이 QA 재검증이 요청되었습니다.",
            )
        if command == settings.status_command:
            return service.comment_status_for_github_issue(issue_number, issue_title, issue_body, issue_url, issue_labels)
        if command == settings.cancel_command:
            return service.cancel_github_issue_task(
                issue_number,
                issue_title,
                issue_body,
                issue_url,
                issue_labels,
                command_body or "cancel requested by GitHub comment",
            )
    except ValueError as exc:
        return service.comment_command_failure(
            issue_number=issue_number,
            title=issue_title,
            body=issue_body,
            issue_url=issue_url,
            issue_labels=issue_labels,
            command=command,
            error=str(exc),
        )
    return {"status": "ignored", "reason": "처리되지 않은 명령입니다."}


def _parse_issue_comment_command(comment_body: str) -> tuple[str | None, str]:
    lines = comment_body.splitlines()
    for index, line in enumerate(lines):
        command = line.strip()
        if not command:
            continue
        return command, "\n".join(lines[index + 1 :]).strip()
    return None, ""


def _is_harness_command(command: str | None) -> bool:
    return command in {
        settings.design_command,
        settings.redesign_command,
        settings.plan_command,
        settings.replan_command,
        settings.develop_command,
        settings.fix_develop_command,
        settings.refactor_command,
        settings.qa_command,
        settings.reqa_command,
        settings.status_command,
        settings.cancel_command,
    }
