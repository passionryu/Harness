import json
from pathlib import Path

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

    def send(self, text: str) -> None:
        self.send_text(text)

    # Discord webhook에 텍스트와 파일 첨부를 함께 전송한다.
    def send_text_with_file(self, text: str, file_path: Path, filename: str | None = None) -> None:
        if not self.webhook_url:
            raise ValueError("Discord webhook URL이 설정되어 있지 않습니다.")
        if not file_path.exists():
            raise FileNotFoundError(f"첨부할 파일을 찾지 못했습니다. path={file_path}")

        payload = {
            "content": text,
            "allowed_mentions": {"parse": []},
        }
        with file_path.open("rb") as file:
            response = httpx.post(
                self.webhook_url,
                data={"payload_json": json.dumps(payload, ensure_ascii=False)},
                files={"files[0]": (filename or file_path.name, file, "application/pdf")},
                timeout=40,
            )
        response.raise_for_status()
