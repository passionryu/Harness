from fastapi import FastAPI

from orchestrator.api.dashboard import router as dashboard_router
from orchestrator.api.routes import router
from orchestrator.core.logging import configure_logging
from orchestrator.core.settings import settings


def create_app() -> FastAPI:
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.include_router(router)
    app.include_router(dashboard_router)
    return app


app = create_app()
