from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import BoundedSemaphore

from fastapi import FastAPI

from fintrack_common.api import make_app
from fintrack_core.config import Settings
from fintrack_core.database import build_engine
from fintrack_core.feedback.api import admin_router as feedback_admin_router
from fintrack_core.feedback.api import public_router as feedback_router
from fintrack_core.finance.api import router as core_router
from fintrack_core.routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    app = make_app("FinTrack development core API", config.cors_origins)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = (
            build_engine(config.database_url.get_secret_value()) if config.database_url else None
        )
        app.state.auth_engine = (
            build_engine(config.auth_database_url.get_secret_value())
            if config.auth_database_url
            else app.state.engine
        )
        try:
            yield
        finally:
            if app.state.auth_engine is not None and app.state.auth_engine is not app.state.engine:
                app.state.auth_engine.dispose()
            if app.state.engine is not None:
                app.state.engine.dispose()

    app.router.lifespan_context = lifespan
    app.state.settings = config
    app.state.core_capacity = BoundedSemaphore(8)
    app.include_router(router)
    app.include_router(core_router)
    app.include_router(feedback_router)
    app.include_router(feedback_admin_router)
    return app
