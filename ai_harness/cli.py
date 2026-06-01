import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import select

from orchestrator.api.schemas import EventResult, HumanApproval
from orchestrator.core.logging import configure_logging
from orchestrator.core.settings import settings
from orchestrator.db.models import Run, StateTransition, Task
from orchestrator.db.session import SessionLocal, create_db
from orchestrator.services.github_adapter import GitHubAdapter
from orchestrator.services.orchestration import OrchestrationService


# CLI 명령 실행 결과를 표현하기 쉬운 dict로 정규화한다.
def _normalize_result(result: EventResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, EventResult):
        return result.model_dump()
    return dict(result)


# 사람이 읽기 쉬운 CLI 결과 문자열을 만든다.
def _render_text_result(result: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in result.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


# CLI 결과를 JSON 또는 텍스트로 출력한다.
def _print_result(result: EventResult | dict[str, Any], as_json: bool) -> None:
    normalized = _normalize_result(result)
    if as_json:
        print(json.dumps(normalized, ensure_ascii=False, indent=2, default=str))
        return
    print(_render_text_result(normalized))


# GitHub 이슈 본문과 라벨을 하네스 실행 입력으로 변환한다.
def _fetch_issue_context(issue_number: int) -> dict[str, Any]:
    if not settings.github_token:
        raise ValueError("GitHub 이슈를 읽으려면 GITHUB_TOKEN이 필요합니다.")

    issue = GitHubAdapter(settings.github_token).get_issue(
        settings.github_owner,
        settings.github_repo,
        issue_number,
    )
    return {
        "issue_number": int(issue["number"]),
        "title": issue.get("title") or "",
        "body": issue.get("body") or "",
        "issue_url": issue.get("html_url") or "",
        "issue_labels": _labels_from_issue(issue),
    }


# GitHub 이슈 payload에서 label 이름만 추출한다.
def _labels_from_issue(issue: dict[str, Any]) -> list[str]:
    return sorted(
        item.get("name")
        for item in issue.get("labels", [])
        if isinstance(item, dict) and item.get("name")
    )


# CLI note 옵션과 note 파일 옵션을 하나의 요청 메모로 합친다.
def _resolve_note(args: argparse.Namespace, fallback: str) -> str:
    note_parts: list[str] = []
    if getattr(args, "note", None):
        note_parts.append(str(args.note).strip())
    if getattr(args, "note_file", None):
        note_parts.append(Path(args.note_file).expanduser().read_text(encoding="utf-8").strip())
    return "\n\n".join(part for part in note_parts if part).strip() or fallback


# GitHub 이슈 기반 명령을 OrchestrationService에 위임한다.
def _run_issue_command(args: argparse.Namespace) -> EventResult | dict[str, Any]:
    context = _fetch_issue_context(args.issue)
    with SessionLocal() as db:
        service = OrchestrationService(db)
        if args.command == "plan":
            return service.run_plan_for_github_issue(force=args.force, **context)
        if args.command == "replan":
            return service.run_replan_for_github_issue(
                replan_request=_resolve_note(args, "CLI에서 재설계가 요청되었습니다."),
                **context,
            )
        if args.command == "develop":
            return service.run_develop_for_github_issue(**context)
        if args.command == "fix-develop":
            return service.run_fix_develop_for_github_issue(**context)
        if args.command == "refactor":
            return service.run_refactor_for_github_issue(
                refactor_request=_resolve_note(args, "CLI에서 리팩터링이 요청되었습니다."),
                **context,
            )
        if args.command == "qa":
            return service.run_qa_for_github_issue(
                qa_request=_resolve_note(args, "CLI에서 QA가 요청되었습니다."),
                **context,
            )
        if args.command == "re-qa":
            return service.rerun_qa_for_github_issue(
                qa_request=_resolve_note(args, "CLI에서 QA 재검증이 요청되었습니다."),
                **context,
            )
        if args.command == "cancel":
            return service.cancel_github_issue_task(
                reason=_resolve_note(args, "CLI에서 작업 중지가 요청되었습니다."),
                **context,
            )
    raise ValueError(f"지원하지 않는 CLI 명령입니다: {args.command}")


# GitHub 이슈를 하네스 DB task로 동기화한다.
def _sync_issues(args: argparse.Namespace) -> dict[str, Any]:
    if not settings.github_token:
        raise ValueError("GitHub 이슈 동기화에는 GITHUB_TOKEN이 필요합니다.")

    adapter = GitHubAdapter(settings.github_token)
    issues = (
        [adapter.get_issue(settings.github_owner, settings.github_repo, args.issue)]
        if args.issue
        else adapter.list_issues(settings.github_owner, settings.github_repo)
    )
    with SessionLocal() as db:
        service = OrchestrationService(db)
        synced: list[int] = []
        for issue in issues:
            task = _sync_issue_task(service, issue)
            synced.append(task.github_issue_number or int(issue["number"]))
        db.commit()
    return {"status": "ok", "synced_count": len(synced), "issues": synced}


# GitHub 이슈 하나를 상태 전이 없이 로컬 task로 동기화한다.
def _sync_issue_task(service: OrchestrationService, issue: dict[str, Any]) -> Task:
    issue_number = int(issue["number"])
    task = service.db.scalar(select(Task).where(Task.github_issue_number == issue_number))
    body = service._append_issue_metadata(
        issue.get("body") or "",
        _labels_from_issue(issue),
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


# 로컬 DB에 저장된 task와 최근 실행 상태를 조회한다.
def _status(args: argparse.Namespace) -> dict[str, Any]:
    with SessionLocal() as db:
        task = db.scalar(select(Task).where(Task.github_issue_number == args.issue))
        if task is None:
            return {"status": "not_found", "reason": f"GitHub issue #{args.issue} task가 없습니다."}

        latest_run = db.scalar(
            select(Run).where(Run.task_id == task.id).order_by(Run.started_at.desc()).limit(1)
        )
        latest_transition = db.scalar(
            select(StateTransition)
            .where(StateTransition.task_id == task.id)
            .order_by(StateTransition.created_at.desc())
            .limit(1)
        )
        service = OrchestrationService(db)
        return {
            "status": "ok",
            "task_id": task.id,
            "issue": task.github_issue_number,
            "title": task.title,
            "state": task.state,
            "next": service._next_command_for_state(task.state),
            "latest_run": _run_payload(service, latest_run),
            "latest_transition": _transition_payload(service, latest_transition),
        }


# Human QA 승인 명령을 로컬 DB에 기록한다.
def _approve(args: argparse.Namespace) -> EventResult:
    with SessionLocal() as db:
        return OrchestrationService(db).approve_human_qa(
            args.task_id,
            HumanApproval(approved_by=args.approved_by, notes=args.notes or ""),
        )


# 최근 run 정보를 CLI 출력용 payload로 변환한다.
def _run_payload(service: OrchestrationService, run: Run | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "agent": run.agent_name,
        "status": run.status,
        "started_at": service._format_dt(run.started_at),
        "finished_at": service._format_dt(run.finished_at),
        "summary": run.summary,
        "error": run.error,
    }


# 최근 상태 전이 정보를 CLI 출력용 payload로 변환한다.
def _transition_payload(
    service: OrchestrationService,
    transition: StateTransition | None,
) -> dict[str, Any] | None:
    if transition is None:
        return None
    return {
        "from": transition.from_state,
        "to": transition.to_state,
        "reason": transition.reason,
        "at": service._format_dt(transition.created_at),
    }


# note를 받는 명령에 공통 옵션을 추가한다.
def _add_note_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--note", default="", help="Agent에 전달할 사람의 요청 메모")
    parser.add_argument("--note-file", default="", help="Agent에 전달할 요청 메모 파일 경로")


# issue 번호 기반 명령에 공통 옵션을 추가한다.
def _add_issue_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--issue", type=int, required=True, help="GitHub issue number")


# CLI 하위 명령과 handler를 등록한다.
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Codex가 호출하는 로컬 AI 개발 하네스 CLI",
    )
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="GitHub issue를 기반으로 Plan Agent를 실행")
    _add_issue_option(plan)
    plan.add_argument("--force", action="store_true", help="성공한 plan이 있어도 다시 실행")
    plan.set_defaults(handler=_run_issue_command)

    for command, help_text in [
        ("develop", "Plan 승인 후 Dev Agent 실행"),
        ("fix-develop", "최근 Dev 실패를 자동 복구"),
    ]:
        command_parser = subparsers.add_parser(command, help=help_text)
        _add_issue_option(command_parser)
        command_parser.set_defaults(handler=_run_issue_command)

    for command, help_text in [
        ("replan", "요청 메모를 반영해 Plan Agent 재실행"),
        ("refactor", "요청 메모 기준으로 구현 결과 리팩터링"),
        ("qa", "System QA Agent 실행"),
        ("re-qa", "System QA Agent 재실행"),
        ("cancel", "작업을 중지 상태로 전환"),
    ]:
        command_parser = subparsers.add_parser(command, help=help_text)
        _add_issue_option(command_parser)
        _add_note_options(command_parser)
        command_parser.set_defaults(handler=_run_issue_command)

    sync = subparsers.add_parser("sync", help="GitHub issue를 하네스 DB에 동기화")
    sync_group = sync.add_mutually_exclusive_group(required=True)
    sync_group.add_argument("--issue", type=int, help="동기화할 GitHub issue number")
    sync_group.add_argument("--all", action="store_true", help="open issue 전체 동기화")
    sync.set_defaults(handler=_sync_issues)

    status = subparsers.add_parser("status", help="로컬 DB 기준 작업 상태 조회")
    _add_issue_option(status)
    status.set_defaults(handler=_status)

    approve = subparsers.add_parser("approve", help="Human QA 승인을 기록")
    approve.add_argument("--task-id", required=True, help="승인할 task id")
    approve.add_argument("--approved-by", required=True, help="승인자 이름")
    approve.add_argument("--notes", default="", help="승인 메모")
    approve.set_defaults(handler=_approve)

    return parser


# CLI 프로세스의 전체 실행 흐름을 제어한다.
def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    configure_logging(settings.log_level, stream=sys.stderr)
    create_db()
    handler: Callable[[argparse.Namespace], EventResult | dict[str, Any]] = args.handler
    try:
        result = handler(args)
        _print_result(result, args.json)
        return 0
    except Exception as exc:
        error = {"status": "failed", "error": str(exc)}
        if args.json:
            print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


# python -m 실행 시 CLI를 시작한다.
if __name__ == "__main__":
    raise SystemExit(main())
