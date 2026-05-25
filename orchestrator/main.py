from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from orchestrator.api.routes import router
from orchestrator.core.logging import configure_logging
from orchestrator.core.settings import settings
from orchestrator.db.session import create_db


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_db()
    yield


def create_app() -> FastAPI:
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.include_router(router)

    return app


app = create_app()
