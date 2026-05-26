import httpx


class DiscordNotifier:
    def __init__(self, webhook_url: str | None):
        self.webhook_url = webhook_url

    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    def send_text(self, text: str) -> None:
        if not self.webhook_url:
            raise ValueError("Discord webhook URL이 설정되어 있지 않습니다.")

        response = httpx.post(
            self.webhook_url,
            json={
                "content": text,
                "allowed_mentions": {"parse": []},
            },
            timeout=20,
        )
        response.raise_for_status()
