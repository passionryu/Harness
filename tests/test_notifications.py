from orchestrator.db.models import AuditLog, Task
from orchestrator.db.session import SessionLocal, create_db
from orchestrator.services import notifications
from orchestrator.services import orchestration
from orchestrator.services.orchestration import OrchestrationService


# Design/Dev 완료는 Discord 채널 노이즈를 만들지 않고 audit만 남긴다.
def test_design_and_dev_notifications_are_discord_silent(monkeypatch):
    class FailingDiscordNotifier:
        def __init__(self, webhook_url: str | None):
            raise AssertionError("Design/Dev 단계에서 DiscordNotifier가 호출되면 안 됩니다.")

    monkeypatch.setattr(notifications, "DiscordNotifier", FailingDiscordNotifier)
    monkeypatch.setattr(orchestration.settings, "allow_external_notifications", True)
    monkeypatch.setattr(orchestration.settings, "discord_webhook_url", "https://discord.example/webhook")
    create_db()

    with SessionLocal() as db:
        task = Task(
            title="[FE] Discord 노이즈 줄이기",
            body="## Harness Metadata\n- labels: type: feFeature",
            github_issue_number=123,
            github_issue_url="https://github.com/passionryu/targetApp/issues/123",
            state="Plan Review",
        )
        db.add(task)
        db.flush()

        service = OrchestrationService(db)
        service._notify_after_plan(task, run_id=None, force=False)
        service._notify_after_dev(task, run_id=None)
        db.flush()

        events = {
            row.event_type
            for row in db.query(AuditLog).filter(AuditLog.task_id == task.id).all()
        }

    assert "discord.design_notification_skipped" in events
    assert "discord.dev_notification_skipped" in events
    assert "discord.design_notified" not in events
    assert "discord.dev_notified" not in events
