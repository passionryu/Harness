from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agents.base import AgentInput, AgentResult, AgentStatus
from orchestrator.api.schemas import EventResult, HumanApproval
from orchestrator.core.settings import settings
from orchestrator.services.agent_registry import AgentRegistry
from orchestrator.services.github_adapter import GitHubAdapter


KST = ZoneInfo("Asia/Seoul")
AI_HARNESS_GENERATED_MARKER = "<!-- ai-harness-generated -->"
APPROVAL_PROJECT_STATUS = {
    "plan": "Dev Ready",
    "dev": "QA Ready",
    "qa": "Ready To Deploy",
    "deploy": "Done",
}
MANUAL_COMPLETION_PROJECT_STATUS = {
    "dev": "Dev Review",
    "qa": "QA Review",
}


@dataclass(frozen=True)
class IssueContext:
    issue_number: int
    title: str
    body: str
    issue_url: str = ""
    issue_labels: tuple[str, ...] = ()

    @property
    def task_id(self) -> str:
        return f"issue-{self.issue_number}"


class OrchestrationService:
    """Stateless GitHub issue -> Markdown artifact orchestrator.

    The harness no longer owns a database, state machine, or implementation layer.
    Each command creates a deterministic artifact packet under
    `artifacts/issue-{number}/...` and optionally comments on GitHub.
    """

    def __init__(self) -> None:
        self.agent_registry = AgentRegistry()

    def run_plan_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        force: bool = False,
        replan_request: str | None = None,
        comment_on_duplicate: bool = False,
        issue_labels: list[str] | None = None,
    ) -> EventResult:
        context = self._context(issue_number, title, body, issue_url, issue_labels)
        body = self._append_issue_metadata(context.body, context.issue_labels, context.issue_number)
        if replan_request:
            body = self._append_named_section(body, "Human Redesign Request", replan_request)
        result = self._run_agent(context, "design", body, "Design Requested")
        self._comment_on_github_issue_best_effort(
            context.issue_number,
            self._agent_comment("Design Agent", context, result, "design"),
        )
        suffix = " 재설계 요청이 반영되었습니다." if replan_request or force else ""
        project_status = self._move_project_status_best_effort(context, "Plan Review")
        return self._event(
            context,
            "Design Artifact Ready",
            f"Design artifact를 생성했습니다.{suffix}",
            project_status,
        )

    def run_replan_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        replan_request: str,
        issue_labels: list[str] | None = None,
    ) -> EventResult:
        return self.run_plan_for_github_issue(
            issue_number=issue_number,
            title=title,
            body=body,
            issue_url=issue_url,
            force=True,
            replan_request=replan_request,
            issue_labels=issue_labels,
        )

    def run_develop_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
    ) -> EventResult:
        context = self._context(issue_number, title, body, issue_url, issue_labels)
        body = self._append_issue_metadata(context.body, context.issue_labels, context.issue_number)
        result = self._run_agent(context, "dev", body, "Codex Dev Requested")
        self._comment_on_github_issue_best_effort(
            context.issue_number,
            self._agent_comment("Codex Dev Handoff", context, result, "dev"),
        )
        project_status = self._move_project_status_best_effort(context, "Dev Review")
        return self._event(
            context,
            "Codex Dev Handoff Ready",
            "Codex가 직접 구현할 dev handoff artifact를 생성했습니다.",
            project_status,
        )

    def run_fix_develop_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
    ) -> dict[str, str]:
        context = self._context(issue_number, title, body, issue_url, issue_labels)
        reason = "fix-develop은 제거되었습니다. Codex가 issue와 artifact를 읽고 직접 수정합니다."
        self._write_note(context, "dev", "fix-develop-deprecated.md", ["# fix-develop Deprecated", "", reason])
        self._comment_on_github_issue_best_effort(
            context.issue_number,
            "\n".join([AI_HARNESS_GENERATED_MARKER, "", f"# fix-develop 제거 안내: {context.title}", "", reason]),
        )
        return {"status": "deprecated", "reason": reason, "task_id": context.task_id}

    def run_refactor_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        refactor_request: str,
        issue_labels: list[str] | None = None,
    ) -> EventResult:
        context = self._context(issue_number, title, body, issue_url, issue_labels)
        body = self._append_issue_metadata(context.body, context.issue_labels, context.issue_number)
        body = self._append_named_section(body, "Human Refactor Request", refactor_request)
        result = self._run_agent(context, "dev", body, "Codex Refactor Requested")
        self._comment_on_github_issue_best_effort(
            context.issue_number,
            self._agent_comment("Codex Refactor Handoff", context, result, "dev"),
        )
        project_status = self._move_project_status_best_effort(context, "Dev Review")
        return self._event(
            context,
            "Codex Refactor Handoff Ready",
            "Codex가 직접 리팩터링할 handoff artifact를 생성했습니다.",
            project_status,
        )

    def run_qa_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
        qa_request: str | None = None,
    ) -> EventResult:
        return self._run_qa_like(
            issue_number=issue_number,
            title=title,
            body=body,
            issue_url=issue_url,
            issue_labels=issue_labels,
            qa_request=qa_request,
            rerun=False,
        )

    def rerun_qa_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
        qa_request: str | None = None,
    ) -> EventResult:
        return self._run_qa_like(
            issue_number=issue_number,
            title=title,
            body=body,
            issue_url=issue_url,
            issue_labels=issue_labels,
            qa_request=qa_request,
            rerun=True,
        )

    def run_documentation_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
    ) -> EventResult:
        context = self._context(issue_number, title, body, issue_url, issue_labels)
        body = self._append_issue_metadata(context.body, context.issue_labels, context.issue_number)
        result = self._run_agent(context, "documentation", body, "Documentation Requested")
        self._comment_on_github_issue_best_effort(
            context.issue_number,
            self._agent_comment("Documentation Agent", context, result, "documentation"),
        )
        return self._event(context, "Documentation Artifact Ready", "Documentation artifact를 생성했습니다.")

    def run_domain_knowledge_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
    ) -> EventResult:
        context = self._context(issue_number, title, body, issue_url, issue_labels)
        body = self._append_issue_metadata(context.body, context.issue_labels, context.issue_number)
        result = self._run_agent(context, "domain_knowledge", body, "Domain Knowledge Requested")
        self._comment_on_github_issue_best_effort(
            context.issue_number,
            self._agent_comment("Domain Knowledge Agent", context, result, "domain-knowledge"),
        )
        return self._event(context, "Domain Knowledge Artifact Ready", "Domain knowledge artifact를 생성했습니다.")

    def comment_status_for_github_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
    ) -> dict[str, str]:
        context = self._context(issue_number, title, body, issue_url, issue_labels)
        status = self.status_for_github_issue(context.issue_number, context.title, context.body, context.issue_url)
        self._comment_on_github_issue_best_effort(
            context.issue_number,
            self._status_comment(context, status),
        )
        return {"status": "ok", "task_id": context.task_id, "message": "상태 artifact 기준 댓글을 생성했습니다."}

    def cancel_github_issue_task(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None = None,
        reason: str = "cancel requested",
    ) -> dict[str, str]:
        context = self._context(issue_number, title, body, issue_url, issue_labels)
        path = self._write_note(
            context,
            "control",
            "cancelled.md",
            ["# Cancelled", "", f"- reason: {reason}", f"- at: {self._now()}"],
        )
        self._comment_on_github_issue_best_effort(
            context.issue_number,
            "\n".join([AI_HARNESS_GENERATED_MARKER, "", f"# 작업 중지 기록: {context.title}", "", f"- reason: {reason}", f"- artifact: `{path}`"]),
        )
        return {"status": "ok", "task_id": context.task_id, "artifact": str(path)}

    def approve_stage_for_github_issue(
        self,
        issue_number: int,
        stage: str,
        payload: HumanApproval,
        issue_url: str = "",
    ) -> EventResult:
        context = self._context(issue_number, f"Issue #{issue_number}", "", issue_url, [])
        self._write_note(
            context,
            "approvals",
            f"{stage}-approval.md",
            [
                f"# {stage} Approval",
                "",
                f"- approved_by: {payload.approved_by}",
                f"- notes: {payload.notes or '기록 없음'}",
                f"- at: {self._now()}",
            ],
        )
        project_status = None
        if stage in APPROVAL_PROJECT_STATUS:
            project_status = self._move_project_status_best_effort(
                context,
                APPROVAL_PROJECT_STATUS[stage],
            )
        return self._event(
            context,
            f"{stage} Approved",
            f"{stage} 승인을 파일 artifact로 기록했습니다.",
            project_status,
        )

    def record_manual_completion_for_github_issue(
        self,
        issue_number: int,
        stage: str,
        completed_by: str,
        notes: str = "",
        issue_url: str = "",
    ) -> EventResult:
        context = self._context(issue_number, f"Issue #{issue_number}", "", issue_url, [])
        self._write_note(
            context,
            stage,
            "manual-completion.md",
            [
                f"# Manual {stage.upper()} Completion",
                "",
                f"- completed_by: {completed_by}",
                f"- at: {self._now()}",
                "",
                "## Notes",
                notes or "기록 없음",
            ],
        )
        project_status = None
        if stage in MANUAL_COMPLETION_PROJECT_STATUS:
            project_status = self._move_project_status_best_effort(
                context,
                MANUAL_COMPLETION_PROJECT_STATUS[stage],
            )
        return self._event(
            context,
            f"Manual {stage} Completed",
            f"{stage} 수동 완료를 파일 artifact로 기록했습니다.",
            project_status,
        )

    def comment_command_failure(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None,
        command: str | None,
        error: str,
    ) -> dict[str, str]:
        context = self._context(issue_number, title, body, issue_url, issue_labels)
        self._write_note(
            context,
            "errors",
            f"{self._timestamp()}-command-failure.md",
            ["# Command Failure", "", f"- command: `{command or 'unknown'}`", f"- error: {error}"],
        )
        self._comment_on_github_issue_best_effort(
            context.issue_number,
            "\n".join([AI_HARNESS_GENERATED_MARKER, "", f"# ⚠️ Harness command failure: {context.title}", "", f"- command: `{command or 'unknown'}`", f"- error: `{error}`"]),
        )
        return {"status": "failed", "reason": error, "task_id": context.task_id}

    def status_for_github_issue(
        self,
        issue_number: int,
        title: str = "",
        body: str = "",
        issue_url: str = "",
    ) -> dict[str, str | list[str]]:
        context = self._context(issue_number, title or f"Issue #{issue_number}", body, issue_url, [])
        task_dir = self._task_dir(context)
        artifacts = sorted(str(path.relative_to(task_dir)) for path in task_dir.rglob("*") if path.is_file()) if task_dir.exists() else []
        return {
            "status": "ok" if task_dir.exists() else "not_found",
            "task_id": context.task_id,
            "issue": str(context.issue_number),
            "title": context.title,
            "artifact_root": str(task_dir),
            "artifacts": artifacts[-20:],
            "next": "Codex가 GitHub issue와 artifacts를 읽고 다음 작업을 직접 수행합니다.",
        }

    def sync_github_issue(self, issue: dict) -> dict[str, str]:
        context = self._context(
            int(issue["number"]),
            issue.get("title") or "",
            issue.get("body") or "",
            issue.get("html_url") or "",
            [item.get("name") for item in issue.get("labels", []) if item.get("name")],
        )
        path = self._write_note(
            context,
            "sync",
            "issue-context.md",
            [
                f"# GitHub Issue Context #{context.issue_number}",
                "",
                f"- title: {context.title}",
                f"- url: {context.issue_url or 'N/A'}",
                f"- labels: {', '.join(context.issue_labels) or 'none'}",
                f"- synced_at: {self._now()}",
                "",
                "## Body",
                context.body or "기록 없음",
            ],
        )
        return {"status": "ok", "task_id": context.task_id, "artifact": str(path)}

    def _run_qa_like(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | None,
        qa_request: str | None,
        rerun: bool,
    ) -> EventResult:
        context = self._context(issue_number, title, body, issue_url, issue_labels)
        agent_body = self._append_issue_metadata(context.body, context.issue_labels, context.issue_number)
        if qa_request:
            agent_body = self._append_named_section(agent_body, "Human QA Request", qa_request)
        result = self._run_agent(context, "qa", agent_body, "Codex QA Requested")
        label = "Codex QA Re-Handoff" if rerun else "Codex QA Handoff"
        self._comment_on_github_issue_best_effort(
            context.issue_number,
            self._agent_comment(label, context, result, "qa"),
        )
        project_status = self._move_project_status_best_effort(context, "QA Review")
        return self._event(
            context,
            "Codex QA Handoff Ready",
            "Codex가 직접 검증할 QA handoff artifact를 생성했습니다.",
            project_status,
        )

    def _run_agent(self, context: IssueContext, agent_name: str, body: str, state: str) -> AgentResult:
        agent = self.agent_registry.get(agent_name)
        result = agent.run(
            AgentInput(
                task_id=context.task_id,
                title=context.title,
                body=body,
                state=state,
                artifacts_root=settings.artifact_root,
                timeout_seconds=settings.agent_timeout_seconds,
                retry_count=0,
                retry_limit=0,
            )
        )
        self._write_run_summary(context, agent_name, result)
        if result.status != AgentStatus.SUCCESS:
            raise ValueError(result.error or result.summary)
        return result

    def _write_run_summary(self, context: IssueContext, agent_name: str, result: AgentResult) -> Path:
        artifact_lines = [f"- {artifact.kind}: `{artifact.path}`" for artifact in result.artifacts]
        return self._write_note(
            context,
            "_runs",
            f"{self._timestamp()}-{agent_name}.md",
            [
                f"# {agent_name} Run",
                "",
                f"- status: `{result.status.value}`",
                f"- summary: {result.summary}",
                f"- error: {result.error or 'none'}",
                "",
                "## Artifacts",
                *(artifact_lines or ["- 기록 없음"]),
            ],
        )

    def _agent_comment(self, heading: str, context: IssueContext, result: AgentResult, stage: str) -> str:
        artifact_lines = [f"- `{artifact.path}`" for artifact in result.artifacts]
        return "\n".join(
            [
                AI_HARNESS_GENERATED_MARKER,
                "",
                f"# {heading}: {context.title}",
                "",
                f"Task ID: `{context.task_id}`",
                "",
                "## 결과",
                f"- status: `{result.status.value}`",
                f"- summary: {result.summary}",
                "",
                "## Artifact",
                *(artifact_lines or ["- 기록 없음"]),
                "",
                "## 다음 행동",
                f"- Codex가 `artifacts/{context.task_id}/{stage}`와 `agents/specs`, `agents/playbooks`를 읽고 직접 진행합니다.",
            ]
        )

    def _status_comment(self, context: IssueContext, status: dict[str, str | list[str]]) -> str:
        artifacts = status.get("artifacts", [])
        artifact_lines = [f"- `{item}`" for item in artifacts] if isinstance(artifacts, list) else []
        return "\n".join(
            [
                AI_HARNESS_GENERATED_MARKER,
                "",
                f"# Harness Status: {context.title}",
                "",
                f"- task_id: `{context.task_id}`",
                f"- artifact_root: `{status.get('artifact_root', '')}`",
                "",
                "## 최근 Artifact",
                *(artifact_lines or ["- 기록 없음"]),
                "",
                "## 다음 행동",
                "- Codex가 GitHub issue와 artifact를 읽고 직접 판단합니다.",
            ]
        )

    def _context(
        self,
        issue_number: int,
        title: str,
        body: str,
        issue_url: str,
        issue_labels: list[str] | tuple[str, ...] | None,
    ) -> IssueContext:
        return IssueContext(
            issue_number=issue_number,
            title=title,
            body=body,
            issue_url=issue_url,
            issue_labels=tuple(label for label in (issue_labels or []) if label),
        )

    def _task_dir(self, context: IssueContext) -> Path:
        return settings.artifact_root / context.task_id

    def _write_note(self, context: IssueContext, stage: str, filename: str, lines: list[str]) -> Path:
        path = self._task_dir(context) / stage / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _event(
        self,
        context: IssueContext,
        state: str,
        message: str,
        project_status_result: str | None = None,
    ) -> EventResult:
        if project_status_result:
            message = f"{message} Project Status: {project_status_result}"
        return EventResult(
            task_id=context.task_id,
            previous_state="stateless",
            current_state=state,
            message=message,
        )

    def _move_project_status_best_effort(self, context: IssueContext, status_name: str) -> str:
        if not settings.github_project_number:
            result = "skipped: GITHUB_PROJECT_NUMBER is not configured"
            self._write_project_status_note(context, status_name, result)
            return result
        if not settings.github_token and not settings.github_use_gh_cli:
            result = "skipped: GitHub auth is not configured"
            self._write_project_status_note(context, status_name, result)
            return result
        try:
            GitHubAdapter(settings.github_token, use_gh_cli=settings.github_use_gh_cli).move_issue_project_status(
                settings.github_owner,
                settings.github_repo,
                context.issue_number,
                int(settings.github_project_number),
                status_name,
            )
            result = f"moved to {status_name}"
        except Exception as exc:
            result = f"failed: {exc}"
        self._write_project_status_note(context, status_name, result)
        return result

    def _write_project_status_note(self, context: IssueContext, status_name: str, result: str) -> Path:
        slug = status_name.lower().replace(" ", "-")
        return self._write_note(
            context,
            "project-status",
            f"{self._timestamp()}-{slug}.md",
            [
                "# GitHub Project Status Sync",
                "",
                f"- target_status: {status_name}",
                f"- result: {result}",
                f"- at: {self._now()}",
            ],
        )

    def _append_issue_metadata(self, body: str, issue_labels: tuple[str, ...], issue_number: int) -> str:
        metadata = "\n".join(
            [
                "## Harness Metadata",
                f"- issue_number: {issue_number}",
                f"- labels: {', '.join(issue_labels)}",
            ]
        )
        if "## Harness Metadata" in body:
            return body
        return "\n\n".join(part for part in [body.strip(), metadata] if part)

    def _append_named_section(self, body: str, heading: str, content: str) -> str:
        return "\n\n".join(part for part in [body.strip(), f"## {heading}\n{content.strip()}"] if part)

    def _comment_on_github_issue_best_effort(self, issue_number: int, body: str) -> bool:
        if settings.github_token:
            try:
                GitHubAdapter(settings.github_token, use_gh_cli=settings.github_use_gh_cli).create_issue_comment(
                    settings.github_owner,
                    settings.github_repo,
                    issue_number,
                    body,
                )
                return True
            except Exception:
                pass
        return self._comment_on_github_issue_with_gh(issue_number, body)[0]

    def _comment_on_github_issue_with_gh(self, issue_number: int, body: str) -> tuple[bool, str]:
        if not settings.github_use_gh_cli:
            return False, "github cli disabled"
        body_path = settings.artifact_root / f"comment-{issue_number}-{self._timestamp()}.md"
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_text(body, encoding="utf-8")
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "issue",
                    "comment",
                    str(issue_number),
                    "--repo",
                    f"{settings.github_owner}/{settings.github_repo}",
                    "--body-file",
                    str(body_path),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if completed.returncode == 0:
                return True, completed.stdout.strip()
            return False, (completed.stderr or completed.stdout).strip()
        except Exception as exc:
            return False, str(exc)
        finally:
            body_path.unlink(missing_ok=True)

    def _now(self) -> str:
        return datetime.now(KST).strftime("%Y.%m.%d %H:%M:%S")

    def _timestamp(self) -> str:
        return datetime.now(KST).strftime("%Y%m%d-%H%M%S")
