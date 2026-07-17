from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from orchestrator.core.settings import settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_class=HTMLResponse)
def dashboard_home() -> HTMLResponse:
    artifact_root = settings.artifact_root.expanduser().resolve()
    return HTMLResponse(
        "\n".join(
            [
                "<!doctype html>",
                "<html lang=\"ko\">",
                "<head><meta charset=\"utf-8\"><title>AI Harness</title></head>",
                "<body>",
                "<h1>AI Harness Stateless Mode</h1>",
                "<p>DB 기반 dashboard는 제거되었습니다.</p>",
                "<p>현재 하네스는 GitHub Issue와 Markdown artifact를 기준으로 동작합니다.</p>",
                f"<p>Artifact root: <code>{artifact_root}</code></p>",
                "</body>",
                "</html>",
            ]
        )
    )
