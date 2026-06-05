import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import select

from agents.documentation_agent import publish_harness_history_record
from orchestrator.api.schemas import EventResult, HumanApproval
from orchestrator.core.logging import configure_logging
from orchestrator.core.settings import settings
from orchestrator.db.models import Run, StateTransition, Task
from orchestrator.db.session import SessionLocal, create_db
from orchestrator.services.discord import DiscordNotifier
from orchestrator.services.github_adapter import GitHubAdapter
from orchestrator.services.orchestration import OrchestrationService
from workflows.state_machine import KanbanState


# 테스트 fake adapter와 실제 gh CLI adapter 생성 방식을 함께 지원한다.
def _github_adapter() -> GitHubAdapter:
    try:
        return GitHubAdapter(settings.github_token, settings.github_use_gh_cli)
    except TypeError:
        return GitHubAdapter(settings.github_token)


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
    if not settings.github_token and not settings.github_use_gh_cli:
        raise ValueError("GitHub 이슈를 읽으려면 GITHUB_TOKEN이 필요합니다.")

    issue = _github_adapter().get_issue(
        settings.github_owner,
        settings.github_repo,
        issue_number,
    )
    return {
        "issue_number": int(issue["number"]),
        "title": issue.get("title") or "",
        "body": issue.get("body") or "",
        "issue_url": issue.get("html_url") or "",
        "issue_labels": _labels_from_issue_or_title(issue),
    }


# GitHub 라벨이 없을 때 이슈 제목 prefix로 하네스 타입 라벨을 보강한다.
def _labels_from_issue_or_title(issue: dict[str, Any]) -> list[str]:
    labels = _labels_from_issue(issue)
    if any(label.startswith("type: ") for label in labels):
        return labels

    inferred_label = _infer_type_label_from_title(issue.get("title") or "")
    if inferred_label:
        return sorted([*labels, inferred_label])
    return labels


# 이슈 제목의 작업 타입 prefix를 하네스 내부 type 라벨로 변환한다.
def _infer_type_label_from_title(title: str) -> str:
    normalized = title.strip().lower()
    prefix_map = {
        "[fe]": "type: feFeature",
        "[be]": "type: beFeature",
        "[fs]": "type: fullstackFeature",
        "[api]": "type: apiConnect",
        "[config]": "type: config",
        "[infra]": "type: infra",
        "[docs]": "type: docs",
        "[bugfix]": "type: bugfix",
        "[hotfix]": "type: hotfix",
    }
    for prefix, label in prefix_map.items():
        if normalized.startswith(prefix):
            return label
    return ""


# 하네스 내부 구현 타입을 GitHub 이슈 제목 prefix로 변환한다.
def _title_prefix_for_type(issue_type: str) -> str:
    return {
        "feFeature": "[FE]",
        "beFeature": "[BE]",
        "fullstackFeature": "[FS]",
        "apiConnect": "[API]",
        "config": "[Config]",
        "infra": "[Infra]",
        "docs": "[Docs]",
        "bugfix": "[Bugfix]",
        "hotfix": "[Hotfix]",
    }.get(issue_type, "")


# 제목에 구현 타입 prefix가 없으면 지정한 타입 prefix를 붙인다.
def _normalize_issue_title(title: str, issue_type: str) -> str:
    prefix = _title_prefix_for_type(issue_type)
    if not prefix:
        return title
    return title if title.strip().lower().startswith(prefix.lower()) else f"{prefix} {title}"


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
        if args.command == "document":
            return service.run_documentation_for_github_issue(**context)
        if args.command == "cancel":
            return service.cancel_github_issue_task(
                reason=_resolve_note(args, "CLI에서 작업 중지가 요청되었습니다."),
                **context,
            )
    raise ValueError(f"지원하지 않는 CLI 명령입니다: {args.command}")


# 여러 issue 입력 형식을 정수 목록으로 정리한다.
def _resolve_auto_run_issues(args: argparse.Namespace) -> list[int]:
    if getattr(args, "issue", None) is not None:
        return [int(args.issue)]
    return [
        int(item.strip())
        for item in str(args.issues).split(",")
        if item.strip()
    ]


# 자동 진행 중 agent 실행 결과가 실패/중단 상태인지 검증한다.
def _ensure_auto_step_succeeded(step_name: str, result: EventResult | dict[str, Any]) -> None:
    normalized = _normalize_result(result)
    status = str(normalized.get("status", "success"))
    if status in {"failed", "needs_human", "deprecated"}:
        raise ValueError(f"{step_name} 단계가 완료되지 않았습니다: {normalized}")


# 현재 task 상태를 기준으로 필요한 approval gate만 자동 승인한다.
def _approve_if_waiting(
    service: OrchestrationService,
    issue_number: int,
    stage: str,
    expected_state: KanbanState,
    approved_by: str,
    note: str,
    issue_url: str,
) -> dict[str, Any]:
    task = service._find_github_issue_task(issue_number, issue_url)
    if task is None:
        raise ValueError(f"GitHub issue #{issue_number} 작업을 찾을 수 없습니다.")
    if task.state != expected_state.value:
        return {"status": "skipped", "stage": stage, "reason": f"current_state={task.state}"}
    result = service.approve_stage_for_github_issue(
        issue_number,
        stage,
        HumanApproval(approved_by=approved_by, notes=note),
        issue_url=issue_url,
    )
    return _normalize_result(result)


# 공식 Plan/Dev/QA Agent 흐름을 승인 로그와 함께 Human QA 직전까지 실행한다.
def _auto_run_single_issue(
    service: OrchestrationService,
    issue_number: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    context = _fetch_issue_context(issue_number)
    steps: list[dict[str, Any]] = []

    plan_result = service.run_plan_for_github_issue(force=args.force_plan, **context)
    _ensure_auto_step_succeeded("plan", plan_result)
    steps.append({"step": "plan", "result": _normalize_result(plan_result)})

    plan_approval = _approve_if_waiting(
        service,
        issue_number,
        "plan",
        KanbanState.PLAN_REVIEW,
        args.approved_by,
        _resolve_note(args, "auto-run이 Plan 승인을 자동 기록했습니다."),
        context["issue_url"],
    )
    steps.append({"step": "approve_plan", "result": plan_approval})

    task = service._find_github_issue_task(issue_number, context["issue_url"])
    if task is None:
        raise ValueError(f"GitHub issue #{issue_number} 작업을 찾을 수 없습니다.")
    if task.state in {KanbanState.DEV_READY.value, KanbanState.DEV_REVIEW.value}:
        dev_result = service.run_develop_for_github_issue(**context)
        _ensure_auto_step_succeeded("develop", dev_result)
        steps.append({"step": "develop", "result": _normalize_result(dev_result)})
    else:
        steps.append({"step": "develop", "result": {"status": "skipped", "reason": f"current_state={task.state}"}})

    dev_approval = _approve_if_waiting(
        service,
        issue_number,
        "dev",
        KanbanState.DEV_REVIEW,
        args.approved_by,
        _resolve_note(args, "auto-run이 Dev 승인을 자동 기록했습니다."),
        context["issue_url"],
    )
    steps.append({"step": "approve_dev", "result": dev_approval})

    task = service._find_github_issue_task(issue_number, context["issue_url"])
    if task is None:
        raise ValueError(f"GitHub issue #{issue_number} 작업을 찾을 수 없습니다.")
    if args.until == "qa" and task.state == KanbanState.QA_READY.value:
        qa_result = service.run_qa_for_github_issue(
            qa_request=_resolve_note(args, "auto-run이 QA를 요청했습니다."),
            **context,
        )
        _ensure_auto_step_succeeded("qa", qa_result)
        steps.append({"step": "qa", "result": _normalize_result(qa_result)})
    else:
        steps.append({"step": "qa", "result": {"status": "skipped", "reason": f"current_state={task.state}"}})

    task = service._find_github_issue_task(issue_number, context["issue_url"])
    return {
        "issue": issue_number,
        "task_id": task.id if task else "",
        "title": context["title"],
        "state": task.state if task else "unknown",
        "steps": steps,
        "next": "사람이 Human QA를 직접 검증한 뒤 approve --stage qa를 실행하세요.",
    }


# 여러 이슈를 순서대로 자동 진행하고 중간 실패 시 해당 이슈에서 멈춘다.
def _auto_run(args: argparse.Namespace) -> dict[str, Any]:
    issues = _resolve_auto_run_issues(args)
    results: list[dict[str, Any]] = []
    with SessionLocal() as db:
        service = OrchestrationService(db)
        for issue_number in issues:
            results.append(_auto_run_single_issue(service, issue_number, args))
    return {"status": "ok", "mode": "auto-run", "until": args.until, "results": results}


# GitHub 이슈를 생성하고 하네스 DB에 동기화한 뒤 Discord 알림을 보낸다.
def _create_issue(args: argparse.Namespace) -> dict[str, Any]:
    if not settings.github_token and not settings.github_use_gh_cli:
        raise ValueError("GitHub 이슈 생성에는 GITHUB_TOKEN이 필요합니다.")
    body = Path(args.body_file).expanduser().read_text(encoding="utf-8")
    title = _normalize_issue_title(args.title, args.type)
    issue = _github_adapter().create_issue(
        settings.github_owner,
        settings.github_repo,
        title,
        body,
    )
    with SessionLocal() as db:
        service = OrchestrationService(db)
        task = _sync_issue_task(service, issue)
        task_id = task.id
        db.commit()

    notification = _notify_issue_created(issue, task_id)
    return {
        "status": "created",
        "issue_number": int(issue["number"]),
        "title": issue.get("title") or title,
        "url": issue.get("html_url") or "",
        "task_id": task_id,
        "notification": notification,
        "next": f"harness plan --issue {int(issue['number'])}",
    }


# 이슈 생성 완료 사실을 Discord에 알린다.
def _notify_issue_created(issue: dict[str, Any], task_id: str) -> str:
    if not settings.allow_external_notifications:
        return "skipped: ALLOW_EXTERNAL_NOTIFICATIONS=false"
    notifier = DiscordNotifier(settings.discord_webhook_url)
    if not notifier.is_configured():
        return "skipped: DISCORD_WEBHOOK_URL is not configured"
    issue_number = int(issue["number"])
    issue_url = issue.get("html_url") or ""
    message = "\n".join(
        [
            f"[{settings.github_repo} 이슈 생성 완료]",
            "",
            f"작업: {issue.get('title') or ''}",
            f"GitHub Issue: {issue_url}",
            f"Task ID: {task_id}",
            "",
            "다음 단계:",
            f"harness plan --issue {issue_number}",
        ]
    )
    notifier.send_text(message)
    return "sent"


# GitHub 이슈를 하네스 DB task로 동기화한다.
def _sync_issues(args: argparse.Namespace) -> dict[str, Any]:
    if not settings.github_token and not settings.github_use_gh_cli:
        raise ValueError("GitHub 이슈 동기화에는 GITHUB_TOKEN이 필요합니다.")

    adapter = _github_adapter()
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
    issue_url = issue.get("html_url") or ""
    task = service._find_github_issue_task(issue_number, issue_url)
    body = service._append_issue_metadata(
        issue.get("body") or "",
        _labels_from_issue_or_title(issue),
        issue_number,
    )
    if task is None:
        task = Task(
            title=issue.get("title") or "",
            body=body,
            github_issue_url=issue_url,
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
    task.github_issue_url = issue_url or task.github_issue_url
    service._audit(
        task.id,
        None,
        "task.refreshed_from_github",
        {"issue_number": issue_number, "issue_url": task.github_issue_url},
    )
    return task


# 로컬 DB에 저장된 task와 최근 실행 상태를 조회한다.
def _status(args: argparse.Namespace) -> dict[str, Any]:
    context = _optional_issue_context(args.issue)
    with SessionLocal() as db:
        service = OrchestrationService(db)
        task = service._find_github_issue_task(args.issue, context["issue_url"])
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


# 단계별 Human Approval Gate 통과를 로컬 DB에 기록한다.
def _approve(args: argparse.Namespace) -> EventResult:
    payload = HumanApproval(approved_by=args.approved_by, notes=args.notes or "")
    with SessionLocal() as db:
        service = OrchestrationService(db)
        if args.issue is not None:
            context = _optional_issue_context(args.issue)
            return service.approve_stage_for_github_issue(
                args.issue,
                args.stage,
                payload,
                issue_url=context["issue_url"],
            )
        if args.task_id is not None:
            if args.stage != "deploy":
                raise ValueError("--task-id 승인은 deploy stage에서만 지원합니다. plan/dev/qa는 --issue를 사용하세요.")
            return service.approve_human_qa(args.task_id, payload)
    raise ValueError("--issue 또는 --task-id 중 하나가 필요합니다.")


# 하네스 세팅 변경 이력을 Notion History 표에 기록한다.
def _document_harness(args: argparse.Namespace) -> dict[str, Any]:
    result = publish_harness_history_record(
        title=args.title,
        category=args.category,
        feature=args.feature,
        usage=args.usage,
    )
    return {
        "status": result["status"],
        "target": "harness-history",
        "title": args.title,
        "category": args.category,
        "url": result.get("url", ""),
        "reason": result.get("reason", ""),
    }


# GitHub 조회가 불가능한 환경에서는 로컬 DB 조회용 빈 issue_url을 반환한다.
def _optional_issue_context(issue_number: int) -> dict[str, Any]:
    try:
        return _fetch_issue_context(issue_number)
    except Exception:
        return {
            "issue_number": issue_number,
            "title": "",
            "body": "",
            "issue_url": "",
            "issue_labels": [],
        }


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

    create_issue = subparsers.add_parser("create-issue", help="GitHub issue 생성 후 하네스 DB 동기화와 Discord 알림 전송")
    create_issue.add_argument("--title", required=True, help="생성할 GitHub issue 제목")
    create_issue.add_argument("--body-file", required=True, help="생성할 GitHub issue 본문 Markdown 파일")
    create_issue.add_argument(
        "--type",
        default="",
        choices=[
            "",
            "feFeature",
            "beFeature",
            "fullstackFeature",
            "apiConnect",
            "config",
            "infra",
            "docs",
            "bugfix",
            "hotfix",
        ],
        help="제목 prefix 보강에 사용할 구현 타입",
    )
    create_issue.set_defaults(handler=_create_issue)

    for command, help_text in [
        ("develop", "Plan 승인 후 Dev Agent 실행"),
        ("fix-develop", "Deprecated: Dev Agent 내부 복구 또는 Codex 대화형 수정 흐름을 사용"),
    ]:
        command_parser = subparsers.add_parser(command, help=help_text)
        _add_issue_option(command_parser)
        command_parser.set_defaults(handler=_run_issue_command)

    for command, help_text in [
        ("replan", "요청 메모를 반영해 Plan Agent 재실행"),
        ("refactor", "요청 메모 기준으로 구현 결과 리팩터링"),
        ("qa", "System QA Agent 실행"),
        ("re-qa", "System QA Agent 재실행"),
        ("document", "Documentation Agent로 Notion 입력용 작업 기록 생성"),
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

    auto_run = subparsers.add_parser("auto-run", help="Plan/Dev/QA Agent를 공식 흐름으로 Human QA 직전까지 자동 실행")
    auto_run_target = auto_run.add_mutually_exclusive_group(required=True)
    auto_run_target.add_argument("--issue", type=int, help="자동 진행할 GitHub issue number")
    auto_run_target.add_argument("--issues", help="자동 진행할 GitHub issue number 목록. 예: 5,6,7")
    auto_run.add_argument("--until", default="qa", choices=["qa"], help="자동 진행 종료 단계")
    auto_run.add_argument("--approved-by", required=True, help="자동 approval gate 기록에 사용할 승인자 이름")
    auto_run.add_argument("--force-plan", action="store_true", help="성공한 plan이 있어도 다시 설계")
    _add_note_options(auto_run)
    auto_run.set_defaults(handler=_auto_run)

    document_harness = subparsers.add_parser("document-harness", help="하네스 세팅 변경 이력을 Notion History 표에 기록")
    document_harness.add_argument("--title", required=True, help="하네스 변경 이력 제목")
    document_harness.add_argument(
        "--category",
        required=True,
        choices=["스킬 생성", "에이전트 생성", "에이전트 보강", "하네스 강화", "스킬 강화", "기획 변경"],
        help="Notion History 표의 다중 선택 값",
    )
    document_harness.add_argument("--feature", required=True, help="유비쿼터스 언어로 정리한 기능 설명")
    document_harness.add_argument("--usage", required=True, help="사용 방법 또는 호출 방식")
    document_harness.set_defaults(handler=_document_harness)

    approve = subparsers.add_parser("approve", help="Plan/Dev/QA/Deploy 승인 gate를 기록")
    approve_target = approve.add_mutually_exclusive_group(required=True)
    approve_target.add_argument("--issue", type=int, help="승인할 GitHub issue number")
    approve_target.add_argument("--task-id", help="승인할 task id. deploy stage 호환용")
    approve.add_argument("--stage", required=True, choices=["plan", "dev", "qa", "deploy"], help="승인할 단계")
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
