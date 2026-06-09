from __future__ import annotations

import logging

from orchestrator.core.settings import settings
from orchestrator.db.models import Task
from orchestrator.services.discord import DiscordNotifier
from orchestrator.services.google_chat import GoogleChatNotifier
from orchestrator.services.qa_pdf import build_qa_pdf_report

logger = logging.getLogger(__name__)


class NotificationMixin:
    def _build_qa_notification_message(self, task: Task, rerun: bool) -> str:
        return self._build_human_qa_message(task, rerun, github_comment=False)

    # Design 완료 후 Discord에 전달할 짧은 사람용 메시지를 만든다.
    def _build_plan_notification_message(self, task: Task, force: bool) -> str:
        title = f"♻️ 🏗️ Re-Design 완료: {task.title}" if force else f"🏗️ Design 완료: {task.title}"
        return "\n".join(
            [
                title,
                "",
                f"작업 타입: {self._issue_type_label(self._extract_issue_type(task.body, task.title))}",
                f"현재 상태: {task.state}",
                "",
                "엔지니어링 설계 산출물이 생성되었습니다.",
                "내용을 검토한 뒤 충분하면 Design 승인을 기록하세요.",
                "",
                "다음 명령:",
                self._approval_command(task, "plan"),
                "",
                "GitHub Issue:",
                task.github_issue_url or "",
            ]
        )

    # Dev 완료 후 Discord에 전달할 짧은 사람용 메시지를 만든다.
    def _build_dev_notification_message(self, task: Task) -> str:
        latest_run = self._latest_run(task.id)
        run_summary = latest_run.summary if latest_run and latest_run.summary else "Dev Agent 실행이 완료되었습니다."
        return "\n".join(
            [
                f"🛠️ 개발 완료: {task.title}",
                "",
                f"작업 타입: {self._issue_type_label(self._extract_issue_type(task.body, task.title))}",
                f"브랜치 명: {self._branch_name_for_task(task)}",
                f"현재 상태: {task.state}",
                "",
                "실행 결과:",
                run_summary,
                "",
                "개발 결과를 확인한 뒤 Dev 승인을 기록하세요.",
                "",
                "다음 명령:",
                self._approval_command(task, "dev"),
                "",
                "GitHub Issue:",
                task.github_issue_url or "",
            ]
        )

    # Discord 채널 노이즈를 줄이기 위해 Design 완료는 알림 없이 audit만 남긴다.
    def _notify_after_plan(self, task: Task, run_id: str | None, force: bool) -> None:
        self._audit(
            task.id,
            run_id,
            "discord.design_notification_skipped",
            {"reason": "Discord 알림은 QA 완료 시점에만 전송합니다.", "force": force},
        )

    # Discord 채널 노이즈를 줄이기 위해 Dev 완료는 알림 없이 audit만 남긴다.
    def _notify_after_dev(self, task: Task, run_id: str | None) -> None:
        self._audit(
            task.id,
            run_id,
            "discord.dev_notification_skipped",
            {"reason": "Discord 알림은 QA 완료 시점에만 전송합니다."},
        )

    # 특정 단계 완료 메시지를 Discord로 보내고 실패해도 workflow를 중단하지 않는다.
    def _notify_discord_for_stage(self, task: Task, run_id: str | None, stage: str, message: str) -> None:
        notifier = DiscordNotifier(settings.discord_webhook_url)
        if not notifier.is_configured():
            self._audit(
                task.id,
                run_id,
                f"discord.{stage}_notification_skipped",
                {"reason": "DISCORD_WEBHOOK_URL이 설정되어 있지 않습니다."},
            )
            return

        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001 - notification failure must not fail workflow
            logger.warning(
                "Discord 단계 완료 알림 전송 실패",
                extra={"task_id": task.id, "run_id": run_id, "stage": stage, "error": str(exc)},
            )
            self._audit(
                task.id,
                run_id,
                f"discord.{stage}_notification_failed",
                {"error": str(exc)},
            )
            return

        self._audit(task.id, run_id, f"discord.{stage}_notified", {})

    def _notify_after_qa(self, task: Task, run_id: str | None, rerun: bool) -> None:
        if not settings.allow_external_notifications:
            self._audit(
                task.id,
                run_id,
                "external_notifications.skipped",
                {"reason": "ALLOW_EXTERNAL_NOTIFICATIONS가 false입니다.", "rerun": rerun},
            )
            return

        message = self._build_qa_notification_message(task, rerun)
        self._notify_google_chat_after_qa(task, run_id, rerun, message)
        self._notify_discord_after_qa(task, run_id, rerun, message)

    def _notify_google_chat_after_qa(
        self, task: Task, run_id: str | None, rerun: bool, message: str
    ) -> None:
        notifier = GoogleChatNotifier(settings.google_chat_webhook_url)
        if not notifier.is_configured():
            self._audit(
                task.id,
                run_id,
                "google_chat.qa_notification_skipped",
                {"reason": "GOOGLE_CHAT_WEBHOOK_URL이 설정되어 있지 않습니다."},
            )
            return

        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001 - notification failure must not fail QA
            logger.warning(
                "Google Chat QA 알림 전송 실패",
                extra={"task_id": task.id, "run_id": run_id, "error": str(exc)},
            )
            self._audit(
                task.id,
                run_id,
                "google_chat.qa_notification_failed",
                {"error": str(exc)},
            )
            return

        self._audit(
            task.id,
            run_id,
            "google_chat.qa_notified",
            {"rerun": rerun},
        )

    def _notify_discord_after_qa(
        self, task: Task, run_id: str | None, rerun: bool, message: str
    ) -> None:
        notifier = DiscordNotifier(settings.discord_webhook_url)
        if not notifier.is_configured():
            self._audit(
                task.id,
                run_id,
                "discord.qa_notification_skipped",
                {"reason": "DISCORD_WEBHOOK_URL이 설정되어 있지 않습니다."},
            )
            return

        try:
            pdf_path = build_qa_pdf_report(task)
        except Exception as exc:  # noqa: BLE001 - PDF 생성 실패는 텍스트 알림을 막지 않는다.
            logger.warning(
                "Discord QA PDF 보고서 생성 실패",
                extra={"task_id": task.id, "run_id": run_id, "error": str(exc)},
            )
            self._audit(
                task.id,
                run_id,
                "discord.qa_pdf_failed",
                {"error": str(exc)},
            )
            pdf_path = None

        try:
            if pdf_path:
                pdf_message = "\n".join(
                    [
                        message,
                        "",
                        "QA PDF 보고서를 첨부했습니다.",
                    ]
                )
                notifier.send_text_with_file(
                    pdf_message,
                    pdf_path,
                    filename=f"qa-report-issue-{task.github_issue_number or 'unknown'}.pdf",
                )
            else:
                notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001 - notification failure must not fail QA
            logger.warning(
                "Discord QA 알림 전송 실패",
                extra={"task_id": task.id, "run_id": run_id, "error": str(exc)},
            )
            self._audit(
                task.id,
                run_id,
                "discord.qa_notification_failed",
                {"error": str(exc)},
            )
            return

        self._audit(
            task.id,
            run_id,
            "discord.qa_notified",
            {"rerun": rerun},
        )
