from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from orchestrator.core.settings import settings
from orchestrator.db.models import Task
from orchestrator.services.github_adapter import GitHubAdapter


class GitHubCommentMixin:
    # GitHub API 댓글 작성이 실패하면 gh CLI로 한 번 더 시도한다.
    def _comment_on_github_issue(
        self,
        task: Task,
        run_id: str | None,
        issue_number: int,
        body: str,
        success_event: str,
        failure_event: str,
    ) -> bool:
        api_error: str | None = None
        if not settings.github_token:
            if settings.github_use_gh_cli:
                gh_result = self._comment_on_github_issue_with_gh(issue_number, body)
                if gh_result[0]:
                    self._audit(
                        task.id,
                        run_id,
                        success_event,
                        {"issue_number": issue_number, "method": "gh_cli", "api_error": None},
                    )
                    return True
                self._audit(
                    task.id,
                    run_id,
                    failure_event,
                    {"issue_number": issue_number, "api_error": None, "gh_error": gh_result[1]},
                )
                return False
            self._audit(
                task.id,
                run_id,
                failure_event,
                {"issue_number": issue_number, "api_error": "GITHUB_TOKEN이 설정되어 있지 않습니다."},
            )
            return False

        if settings.github_token:
            try:
                GitHubAdapter(settings.github_token).create_issue_comment(
                    settings.github_owner,
                    settings.github_repo,
                    issue_number,
                    body,
                )
                self._audit(
                    task.id,
                    run_id,
                    success_event,
                    {"issue_number": issue_number, "method": "github_api"},
                )
                return True
            except Exception as exc:  # noqa: BLE001 - fallback decides final result
                api_error = str(exc)

        gh_result = self._comment_on_github_issue_with_gh(issue_number, body)
        if gh_result[0]:
            self._audit(
                task.id,
                run_id,
                success_event,
                {
                    "issue_number": issue_number,
                    "method": "gh_cli",
                    "api_error": api_error,
                },
            )
            return True

        self._audit(
            task.id,
            run_id,
            failure_event,
            {
                "issue_number": issue_number,
                "api_error": api_error,
                "gh_error": gh_result[1],
            },
        )
        return False

    # Plan/Replan 결과 댓글은 이슈당 하나만 남기도록 기존 댓글을 수정하고 오래된 중복 댓글을 정리한다.
    def _upsert_plan_comment_on_github_issue(
        self,
        task: Task,
        run_id: str | None,
        issue_number: int,
        body: str,
    ) -> bool:
        try:
            adapter = GitHubAdapter(settings.github_token, use_gh_cli=settings.github_use_gh_cli)
        except TypeError:
            adapter = GitHubAdapter(settings.github_token)
        is_configured = getattr(adapter, "is_configured", lambda: True)
        if not is_configured():
            self._audit(
                task.id,
                run_id,
                "github.plan_comment_failed",
                {"issue_number": issue_number, "reason": "GitHub 인증이 설정되어 있지 않습니다."},
            )
            return False

        try:
            comments = (
                adapter.list_issue_comments(settings.github_owner, settings.github_repo, issue_number)
                if hasattr(adapter, "list_issue_comments")
                else []
            )
            plan_comments = [
                comment
                for comment in comments
                if self._is_harness_plan_comment(str(comment.get("body", "")))
                and comment.get("id") is not None
            ]
            if plan_comments and hasattr(adapter, "update_issue_comment"):
                latest_comment = plan_comments[-1]
                adapter.update_issue_comment(
                    settings.github_owner,
                    settings.github_repo,
                    latest_comment["id"],
                    body,
                )
                for stale_comment in (plan_comments[:-1] if hasattr(adapter, "delete_issue_comment") else []):
                    adapter.delete_issue_comment(
                        settings.github_owner,
                        settings.github_repo,
                        stale_comment["id"],
                    )
                self._audit(
                    task.id,
                    run_id,
                    "github.plan_comment_upserted",
                    {
                        "issue_number": issue_number,
                        "method": "update",
                        "updated_comment_id": latest_comment["id"],
                        "deleted_duplicate_count": len(plan_comments[:-1]),
                    },
                )
                return True

            adapter.create_issue_comment(settings.github_owner, settings.github_repo, issue_number, body)
            self._audit(
                task.id,
                run_id,
                "github.plan_comment_upserted",
                {"issue_number": issue_number, "method": "create"},
            )
            return True
        except Exception as exc:  # noqa: BLE001 - audit records integration failure
            fallback_result = self._comment_on_github_issue(
                task,
                run_id,
                issue_number,
                body,
                "github.plan_comment_upserted",
                "github.plan_comment_failed",
            )
            if fallback_result:
                return True
            self._audit(
                task.id,
                run_id,
                "github.plan_comment_failed",
                {"issue_number": issue_number, "error": str(exc)},
            )
            return False

    # 하네스가 작성한 Design/Redesign 호환 댓글인지 판단한다.
    def _is_harness_plan_comment(self, body: str) -> bool:
        if "<!-- ai-harness-generated -->" not in body:
            return False
        return any(
            title in body
            for title in [
                "# 🏗️ AI Design:",
                "# ♻️ 🏗️ AI Re-Design:",
                "# 🏗️ AI Plan:",
                "# ♻️ 🏗️ AI Re-Plan:",
            ]
        )

    # gh CLI 인증을 사용해 GitHub 이슈 댓글을 작성한다.
    def _comment_on_github_issue_with_gh(self, issue_number: int, body: str) -> tuple[bool, str]:
        repo = f"{settings.github_owner}/{settings.github_repo}"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
            file.write(body)
            body_path = Path(file.name)
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "issue",
                    "comment",
                    str(issue_number),
                    "--repo",
                    repo,
                    "--body-file",
                    str(body_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if completed.returncode == 0:
                return True, ""
            return False, (completed.stderr or completed.stdout or f"exit_code={completed.returncode}").strip()
        except Exception as exc:  # noqa: BLE001 - caller records fallback failure
            return False, str(exc)
        finally:
            body_path.unlink(missing_ok=True)

    # task가 아직 없거나 로드되지 않은 안내 댓글도 가능한 범위에서 작성한다.
    def _comment_on_github_issue_best_effort(self, issue_number: int, body: str) -> bool:
        if settings.github_token:
            try:
                GitHubAdapter(settings.github_token).create_issue_comment(
                    settings.github_owner,
                    settings.github_repo,
                    issue_number,
                    body,
                )
                return True
            except Exception:  # noqa: BLE001 - gh CLI fallback is intentionally best-effort
                pass
        return self._comment_on_github_issue_with_gh(issue_number, body)[0]
