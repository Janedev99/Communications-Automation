"""
FastAPI application entry point.

Registers all routers, middleware, lifespan events, and exception handlers.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, dashboard, drafts, emails, escalations, knowledge
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Logging configuration ──────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.app_log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ── Lifespan ───────────────────────────────────────────────────────────────────

_polling_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Start background tasks on startup, cancel them on shutdown."""
    global _polling_task

    logger.info("Starting Jane Communication Automation backend (env=%s)", settings.app_env)

    # Start email polling background task
    from app.services.email_intake import start_polling_loop
    _polling_task = asyncio.create_task(start_polling_loop(), name="email-polling")
    logger.info("Email polling task started")

    yield  # Application is running

    # Shutdown
    if _polling_task and not _polling_task.done():
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:
            pass
    logger.info("Shutdown complete")


# ── App factory ────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Jane Communication Automation",
        description=(
            "Backend API for the tax firm email automation system. "
            "Handles email intake, AI categorization, escalation detection, "
            "AI-assisted draft generation, and staff workflow."
        ),
        version="1.1.0",
        lifespan=lifespan,
        # Disable default docs in production
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    # ── CORS ───────────────────────────────────────────────────────────────────
    # In production, replace "*" with the actual frontend origin.
    # We use allow_credentials=True so the HttpOnly session cookie is sent.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002", "http://localhost:3003", "http://localhost:3004", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ─────────────────────────────────────────────────────

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled exception on %s %s: %s",
            request.method, request.url.path, exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal error occurred. Please try again later."},
        )

    # ── Routers ────────────────────────────────────────────────────────────────
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(emails.router, prefix="/api/v1")
    app.include_router(escalations.router, prefix="/api/v1")
    app.include_router(dashboard.router, prefix="/api/v1")
    # Phase 2
    app.include_router(knowledge.router, prefix="/api/v1")
    app.include_router(drafts.router, prefix="/api/v1")

    # ── Root ───────────────────────────────────────────────────────────────────
    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {
            "service": "Jane Communication Automation",
            "version": "1.1.0",
            "docs": "/docs" if not settings.is_production else None,
        }

    return app


app = create_app()
