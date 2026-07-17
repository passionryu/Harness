import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.agent_spec import DEFAULT_PLAYBOOK_DIR, DEFAULT_SPEC_DIR, list_markdown_specs, load_agent_spec
from agents.base import AgentInput, AgentStatus
from agents.documentation_agent import publish_harness_history_record
from agents.planning_assistant_agent import PlanningAssistantAgent
from orchestrator.api.schemas import EventResult, HumanApproval
from orchestrator.core.logging import configure_logging
from orchestrator.core.settings import settings
from orchestrator.services.discord import DiscordNotifier
from orchestrator.services.github_adapter import GitHubAdapter
from orchestrator.services.orchestration import OrchestrationService
from orchestrator.services.ui_evidence import publish_ui_evidence_to_stage


def _github_adapter() -> GitHubAdapter:
    try:
        return GitHubAdapter(settings.github_token, settings.github_use_gh_cli)
    except TypeError:
        return GitHubAdapter(settings.github_token)


def _normalize_result(result: EventResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, EventResult):
        return result.model_dump()
    return dict(result)


def _print_result(result: EventResult | dict[str, Any], as_json: bool) -> None:
    normalized = _normalize_result(result)
    if as_json:
        print(json.dumps(normalized, ensure_ascii=False, indent=2, default=str))
        return
    print("\n".join(f"{key}: {value}" for key, value in normalized.items()))


def _fetch_issue_context(issue_number: int) -> dict[str, Any]:
    if not settings.github_token and not settings.github_use_gh_cli:
        raise ValueError("GitHub 이슈를 읽으려면 GITHUB_TOKEN 또는 gh CLI가 필요합니다.")
    issue = _github_adapter().get_issue(settings.github_owner, settings.github_repo, issue_number)
    return {
        "issue_number": int(issue["number"]),
        "title": issue.get("title") or "",
        "body": issue.get("body") or "",
        "issue_url": issue.get("html_url") or "",
        "issue_labels": _labels_from_issue_or_title(issue),
    }


def _optional_issue_context(issue_number: int) -> dict[str, Any]:
    try:
        return _fetch_issue_context(issue_number)
    except Exception:
        return {
            "issue_number": issue_number,
            "title": f"Issue #{issue_number}",
            "body": "",
            "issue_url": "",
            "issue_labels": [],
        }


def _labels_from_issue_or_title(issue: dict[str, Any]) -> list[str]:
    labels = sorted(
        item.get("name")
        for item in issue.get("labels", [])
        if isinstance(item, dict) and item.get("name")
    )
    if any(label.startswith("type: ") for label in labels):
        return labels
    inferred_label = _infer_type_label_from_title(issue.get("title") or "")
    return sorted([*labels, inferred_label]) if inferred_label else labels


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


def _normalize_issue_title(title: str, issue_type: str) -> str:
    prefix = _title_prefix_for_type(issue_type)
    if not prefix:
        return title
    return title if title.strip().lower().startswith(prefix.lower()) else f"{prefix} {title}"


def _resolve_note(args: argparse.Namespace, fallback: str) -> str:
    note_parts: list[str] = []
    if getattr(args, "note", None):
        note_parts.append(str(args.note).strip())
    if getattr(args, "note_file", None):
        note_parts.append(Path(args.note_file).expanduser().read_text(encoding="utf-8").strip())
    return "\n\n".join(part for part in note_parts if part).strip() or fallback


def _run_issue_command(args: argparse.Namespace) -> EventResult | dict[str, Any]:
    context = _fetch_issue_context(args.issue)
    service = OrchestrationService()
    if args.command in {"design", "plan"}:
        result = service.run_plan_for_github_issue(force=getattr(args, "force", False), **context)
        if args.command == "plan":
            payload = _normalize_result(result)
            payload["warning"] = "plan 명령은 deprecated입니다. design 명령을 사용하세요."
            return payload
        return result
    if args.command in {"redesign", "replan"}:
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
    if args.command == "domain-knowledge":
        return service.run_domain_knowledge_for_github_issue(**context)
    if args.command == "cancel":
        return service.cancel_github_issue_task(
            reason=_resolve_note(args, "CLI에서 작업 중지가 요청되었습니다."),
            **context,
        )
    raise ValueError(f"지원하지 않는 CLI 명령입니다: {args.command}")


def _auto_run(args: argparse.Namespace) -> dict[str, Any]:
    service = OrchestrationService()
    issues = [int(args.issue)] if args.issue is not None else [int(item.strip()) for item in args.issues.split(",") if item.strip()]
    results: list[dict[str, Any]] = []
    for issue_number in issues:
        context = _fetch_issue_context(issue_number)
        steps = [
            {"step": "design", "result": _normalize_result(service.run_plan_for_github_issue(force=args.force_plan, **context))},
            {"step": "develop", "result": _normalize_result(service.run_develop_for_github_issue(**context))},
        ]
        if args.until == "qa":
            steps.append(
                {
                    "step": "qa",
                    "result": _normalize_result(
                        service.run_qa_for_github_issue(
                            qa_request=_resolve_note(args, "auto-run이 QA를 요청했습니다."),
                            **context,
                        )
                    ),
                }
            )
        results.append({"issue": issue_number, "task_id": f"issue-{issue_number}", "steps": steps})
    return {"status": "ok", "mode": "stateless-auto-run", "results": results}


def _create_issue(args: argparse.Namespace) -> dict[str, Any]:
    if not settings.github_token and not settings.github_use_gh_cli:
        raise ValueError("GitHub 이슈 생성에는 GITHUB_TOKEN 또는 gh CLI가 필요합니다.")
    body = Path(args.body_file).expanduser().read_text(encoding="utf-8")
    title = _normalize_issue_title(args.title, args.type)
    issue = _github_adapter().create_issue(settings.github_owner, settings.github_repo, title, body)
    service = OrchestrationService()
    sync_result = service.sync_github_issue(issue)
    issue_number = int(issue["number"])
    project_status = _move_created_issue_to_backlog(issue_number)
    notification = _notify_issue_created(issue, sync_result["task_id"])
    return {
        "status": "created",
        "issue_number": issue_number,
        "title": issue.get("title") or title,
        "url": issue.get("html_url") or "",
        "task_id": sync_result["task_id"],
        "artifact": sync_result["artifact"],
        "project_status": project_status,
        "notification": notification,
        "next": f"harness design --issue {issue_number}",
    }


def _move_created_issue_to_backlog(issue_number: int) -> str:
    if not settings.github_project_number:
        return "skipped: GITHUB_PROJECT_NUMBER is not configured"
    try:
        _github_adapter().move_issue_project_status(
            settings.github_owner,
            settings.github_repo,
            issue_number,
            int(settings.github_project_number),
            "Backlog",
        )
        return "Backlog"
    except Exception as exc:
        return f"failed: {exc}"


def _notify_issue_created(issue: dict[str, Any], task_id: str) -> str:
    if not settings.allow_external_notifications:
        return "skipped: ALLOW_EXTERNAL_NOTIFICATIONS=false"
    notifier = DiscordNotifier(settings.discord_webhook_url)
    if not notifier.is_configured():
        return "skipped: DISCORD_WEBHOOK_URL is not configured"
    issue_number = int(issue["number"])
    message = "\n".join(
        [
            f"[{settings.github_repo} 이슈 생성 완료]",
            "",
            f"작업: {issue.get('title') or ''}",
            f"GitHub Issue: {issue.get('html_url') or ''}",
            f"Task ID: {task_id}",
            "",
            "다음 단계:",
            f"harness design --issue {issue_number}",
        ]
    )
    notifier.send_text(message)
    return "sent"


def _sync_issues(args: argparse.Namespace) -> dict[str, Any]:
    if not settings.github_token and not settings.github_use_gh_cli:
        raise ValueError("GitHub 이슈 동기화에는 GITHUB_TOKEN 또는 gh CLI가 필요합니다.")
    adapter = _github_adapter()
    issues = [adapter.get_issue(settings.github_owner, settings.github_repo, args.issue)] if args.issue else adapter.list_issues(settings.github_owner, settings.github_repo)
    service = OrchestrationService()
    synced = [service.sync_github_issue(issue) for issue in issues]
    return {"status": "ok", "synced_count": len(synced), "issues": [item["task_id"] for item in synced]}


def _publish_ui_evidence(args: argparse.Namespace) -> dict[str, Any]:
    return publish_ui_evidence_to_stage(
        source_paths=[Path(path) for path in args.image],
        repo_path=settings.target_repo_path,
        target_branch=args.target_branch or settings.development_base_branch,
        slug=args.slug,
        issue_number=args.issue,
        push=not args.no_push,
    ).to_dict()


def _status(args: argparse.Namespace) -> dict[str, Any]:
    context = _optional_issue_context(args.issue)
    return OrchestrationService().status_for_github_issue(
        issue_number=context["issue_number"],
        title=context["title"],
        body=context["body"],
        issue_url=context["issue_url"],
    )


def _approve(args: argparse.Namespace) -> EventResult:
    return OrchestrationService().approve_stage_for_github_issue(
        issue_number=args.issue,
        stage=args.stage,
        payload=HumanApproval(approved_by=args.approved_by, notes=args.notes or ""),
    )


def _manual_complete(args: argparse.Namespace) -> EventResult:
    return OrchestrationService().record_manual_completion_for_github_issue(
        issue_number=args.issue,
        stage=args.stage,
        completed_by=args.completed_by,
        notes=args.notes or "",
    )


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


def _planning_assist(args: argparse.Namespace) -> dict[str, Any]:
    task_id = f"planning-assistant-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    note = _resolve_note(args, "")
    body = "\n".join([f"topic: {args.topic or ''}", "", "## 요청 메모", note or "기획 후보와 질문을 정리한다."])
    result = PlanningAssistantAgent().run(
        AgentInput(
            task_id=task_id,
            title=args.topic or "Planning Assistant",
            body=body,
            state="Planning",
            artifacts_root=settings.artifact_root,
            timeout_seconds=settings.agent_timeout_seconds,
            retry_count=0,
            retry_limit=0,
        )
    )
    if result.status != AgentStatus.SUCCESS:
        raise ValueError(result.error or result.summary)
    return {"status": result.status.value, "summary": result.summary, "artifacts": [str(artifact.path) for artifact in result.artifacts]}


def _add_note_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--note", default="", help="Agent에 전달할 사람의 요청 메모")
    parser.add_argument("--note-file", default="", help="Agent에 전달할 요청 메모 파일 경로")


def _add_issue_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--issue", type=int, required=True, help="GitHub issue number")


def _agent_specs(args: argparse.Namespace) -> dict[str, Any]:
    if args.name:
        spec = load_agent_spec(args.name)
        return {
            "status": "ok",
            "name": spec.name,
            "version": spec.version,
            "summary": spec.summary,
            "path": str(spec.path),
            "triggers": spec.triggers,
            "inputs": spec.inputs,
            "outputs": spec.outputs,
            "mission": spec.section("Mission"),
            "decision_rules": spec.section("Decision Rules"),
            "hard_rules": spec.section("Hard Rules"),
        }
    return {
        "status": "ok",
        "specs": [
            {"name": spec.name, "version": spec.version, "summary": spec.summary, "path": str(spec.path)}
            for spec in list_markdown_specs(DEFAULT_SPEC_DIR)
        ],
    }


def _playbooks(args: argparse.Namespace) -> dict[str, Any]:
    if args.name:
        spec = load_agent_spec(args.name, DEFAULT_PLAYBOOK_DIR)
        return {
            "status": "ok",
            "name": spec.name,
            "version": spec.version,
            "summary": spec.summary,
            "path": str(spec.path),
            "triggers": spec.triggers,
            "inputs": spec.inputs,
            "outputs": spec.outputs,
            "mission": spec.section("Mission"),
            "codex_execution_steps": spec.section("Codex Execution Steps"),
            "decision_rules": spec.section("Decision Rules"),
            "hard_rules": spec.section("Hard Rules"),
        }
    return {
        "status": "ok",
        "playbooks": [
            {"name": spec.name, "version": spec.version, "summary": spec.summary, "path": str(spec.path)}
            for spec in list_markdown_specs(DEFAULT_PLAYBOOK_DIR)
        ],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="Codex용 stateless AI 개발 하네스 CLI")
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    subparsers = parser.add_subparsers(dest="command", required=True)

    agent_specs = subparsers.add_parser("agent-specs", help="Markdown Agent spec 목록 또는 상세 조회")
    agent_specs.add_argument("--name", default="", help="상세 조회할 Agent spec 이름")
    agent_specs.set_defaults(handler=_agent_specs)

    playbooks = subparsers.add_parser("playbooks", help="Codex Markdown playbook 목록 또는 상세 조회")
    playbooks.add_argument("--name", default="", help="상세 조회할 playbook 이름")
    playbooks.set_defaults(handler=_playbooks)

    for command, help_text in [("design", "GitHub issue 기반 Design artifact 생성"), ("plan", "Deprecated alias: design")]:
        command_parser = subparsers.add_parser(command, help=help_text)
        _add_issue_option(command_parser)
        command_parser.add_argument("--force", action="store_true", help="stateless 모드에서는 재실행 기록만 남김")
        command_parser.set_defaults(handler=_run_issue_command)

    for command, help_text in [
        ("redesign", "요청 메모를 반영해 Design artifact 재생성"),
        ("replan", "Deprecated alias: redesign"),
        ("develop", "Codex Dev handoff artifact 생성"),
        ("fix-develop", "Deprecated: Codex 직접 수정 안내"),
        ("refactor", "Codex Refactor handoff artifact 생성"),
        ("qa", "Codex QA handoff artifact 생성"),
        ("re-qa", "Codex QA handoff artifact 재생성"),
        ("document", "Documentation Agent 실행"),
        ("domain-knowledge", "Domain Knowledge Agent 실행"),
        ("cancel", "작업 중지 artifact 생성"),
    ]:
        command_parser = subparsers.add_parser(command, help=help_text)
        _add_issue_option(command_parser)
        _add_note_options(command_parser)
        command_parser.set_defaults(handler=_run_issue_command)

    create_issue = subparsers.add_parser("create-issue", help="GitHub issue 생성 후 context artifact와 Discord 알림 전송")
    create_issue.add_argument("--title", required=True)
    create_issue.add_argument("--body-file", required=True)
    create_issue.add_argument("--type", default="", choices=["", "feFeature", "beFeature", "fullstackFeature", "apiConnect", "config", "infra", "docs", "bugfix", "hotfix"])
    create_issue.set_defaults(handler=_create_issue)

    sync = subparsers.add_parser("sync", help="GitHub issue context를 artifact로 저장")
    sync_group = sync.add_mutually_exclusive_group(required=True)
    sync_group.add_argument("--issue", type=int)
    sync_group.add_argument("--all", action="store_true")
    sync.set_defaults(handler=_sync_issues)

    status = subparsers.add_parser("status", help="artifact 기준 작업 상태 조회")
    _add_issue_option(status)
    status.set_defaults(handler=_status)

    auto_run = subparsers.add_parser("auto-run", help="design/develop/qa artifact를 순차 생성")
    auto_run_target = auto_run.add_mutually_exclusive_group(required=True)
    auto_run_target.add_argument("--issue", type=int)
    auto_run_target.add_argument("--issues")
    auto_run.add_argument("--until", default="qa", choices=["qa"])
    auto_run.add_argument("--approved-by", default="", help="호환 옵션. stateless 모드에서는 사용하지 않음")
    auto_run.add_argument("--force-plan", action="store_true")
    _add_note_options(auto_run)
    auto_run.set_defaults(handler=_auto_run)

    approve = subparsers.add_parser("approve", help="승인 내용을 artifact로 기록")
    _add_issue_option(approve)
    approve.add_argument("--stage", required=True, choices=["plan", "dev", "qa", "deploy"])
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--notes", default="")
    approve.set_defaults(handler=_approve)

    manual_complete = subparsers.add_parser("manual-complete", help="수동 완료 내용을 artifact로 기록")
    _add_issue_option(manual_complete)
    manual_complete.add_argument("--stage", required=True, choices=["dev", "qa"])
    manual_complete.add_argument("--completed-by", required=True)
    manual_complete.add_argument("--notes", default="")
    manual_complete.set_defaults(handler=_manual_complete)

    publish_ui_evidence = subparsers.add_parser("publish-ui-evidence", help="UI/UX 증거 이미지를 target repo에 반영")
    publish_ui_evidence.add_argument("--image", action="append", required=True)
    publish_ui_evidence.add_argument("--issue", type=int)
    publish_ui_evidence.add_argument("--slug")
    publish_ui_evidence.add_argument("--target-branch", default="")
    publish_ui_evidence.add_argument("--no-push", action="store_true")
    publish_ui_evidence.set_defaults(handler=_publish_ui_evidence)

    document_harness = subparsers.add_parser("document-harness", help="하네스 세팅 변경 이력을 Notion에 기록")
    document_harness.add_argument("--title", required=True)
    document_harness.add_argument("--category", required=True, choices=["스킬 생성", "에이전트 생성", "에이전트 보강", "하네스 강화", "스킬 강화", "기획 변경"])
    document_harness.add_argument("--feature", required=True)
    document_harness.add_argument("--usage", required=True)
    document_harness.set_defaults(handler=_document_harness)

    planning_assist = subparsers.add_parser("planning-assist", help="Obsidian 기반 기획 지원 Agent 실행")
    planning_assist.add_argument("--topic", default="")
    _add_note_options(planning_assist)
    planning_assist.set_defaults(handler=_planning_assist)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    configure_logging(settings.log_level, stream=sys.stderr)
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


if __name__ == "__main__":
    raise SystemExit(main())
