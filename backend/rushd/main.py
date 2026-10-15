"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.formparsers import MultiPartParser
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .api import (
    academy,
    admin,
    auth,
    batches,
    doctors,
    drugs,
    errors,
    prescriptions,
    training,
    users,
)
from .config import Settings
from .context import AppContext, build_context
from .security.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from .services.training_runner import TrainingRunner
from .services.worker import Worker
from .training.local_engine import LocalEngine

log = logging.getLogger("rushd")

MB = 1024 * 1024


def configure_logging() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None, *, claude_client=None, start_background: bool = True) -> FastAPI:
    settings = settings or Settings()
    configure_logging()
    ctx: AppContext = build_context(settings, claude_client=claude_client)
    ctx.worker = Worker(ctx, settings.worker_threads)
    ctx.trainer = TrainingRunner(ctx)
    ctx.local = LocalEngine(ctx)

    # Keep uploaded images in memory rather than spilling plain bytes to /tmp.
    MultiPartParser.spool_max_size = 16 * MB

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_background:
            ctx.trainer.recover()
            ctx.worker.start()
        if not ctx.claude.available:
            log.warning("ANTHROPIC_API_KEY is not set: cloud reading is disabled")
        if not settings.cookie_secure:
            log.warning("RUSHD_COOKIE_SECURE=false - only acceptable for local testing without HTTPS")
        yield
        ctx.worker.stop()

    dev = settings.environment == "development"
    app = FastAPI(
        title="Rushd",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if dev else None,
    )
    app.state.ctx = ctx
    errors.install(app)
    for module in (auth, prescriptions, batches, drugs, doctors, training, academy, users, admin):
        app.include_router(module.router)

    if settings.frontend_dir.exists():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")

    # Each add_middleware wraps the previous ones, so the last added runs first:
    # security headers on every response, then the host check, then the size limit.
    app.add_middleware(
        BodySizeLimitMiddleware,
        default_limit=settings.max_body_mb * MB,
        bulk_limit=settings.max_bulk_body_mb * MB,
        bulk_prefixes=("/api/batches", "/api/drugs/import"),
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.cookie_secure)
    return app


def app_factory() -> FastAPI:  # used by `uvicorn --factory rushd.main:app_factory`
    return create_app()
