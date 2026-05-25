import httpx


class GoogleChatNotifier:
    def __init__(self, webhook_url: str | None):
        self.webhook_url = webhook_url

    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    def send_text(self, text: str) -> None:
        if not self.webhook_url:
            raise ValueError("Google Chat webhook URL is not configured")

        response = httpx.post(self.webhook_url, json={"text": text}, timeout=20)
        response.raise_for_status()
