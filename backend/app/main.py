"""
FastAPI application entry point.

Registers all routers, middleware, lifespan events, and exception handlers.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Callable

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import audit_log, auth, dashboard, drafts, emails, escalations, integrations, knowledge, runpod, system_settings, tier_rules
from app.config import get_settings

settings = get_settings()

# ── Request ID context var — populated per request ────────────────────────────
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)
_user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "user_id", default="-"
)


# ── JSON log formatter ─────────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line for structured log ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": _request_id_var.get("-"),
            "user_id": _user_id_var.get("-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _LoggingFilter(logging.Filter):
    """Inject request_id + user_id into every log record from the context vars."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get("-")  # type: ignore[attr-defined]
        record.user_id = _user_id_var.get("-")  # type: ignore[attr-defined]
        return True


# ── Configure logging ──────────────────────────────────────────────────────────

def _configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.app_log_level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    if settings.is_production:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
    handler.addFilter(_LoggingFilter())

    # Replace any existing handlers
    root.handlers = [handler]


_configure_logging()
logger = logging.getLogger(__name__)


# ── Request ID middleware ──────────────────────────────────────────────────────

class RequestIdMiddleware:
    """
    Generate a UUID per request, expose it as X-Request-ID response header,
    and inject it into the logging context var so all log lines from the
    same request carry the same ID.
    """

    def __init__(self, app: Callable) -> None:
        self._app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        request = Request(scope)
        # Honour client-supplied request ID (e.g. from a load balancer) or generate a new one
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = _request_id_var.set(request_id)

        # Try to extract user_id from session cookie for log context; best-effort only
        user_id_token = _user_id_var.set("-")

        async def send_with_header(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append(
                    (b"x-request-id", request_id.encode())
                )
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self._app(scope, receive, send_with_header)
        finally:
            _request_id_var.reset(token)
            _user_id_var.reset(user_id_token)


# ── Lifespan ───────────────────────────────────────────────────────────────────

_polling_task: asyncio.Task | None = None
_session_cleanup_task: asyncio.Task | None = None
_runpod_watchdog_task: asyncio.Task | None = None


def _sync_cleanup_sessions() -> int:
    """Synchronous helper: delete expired sessions and return the count removed."""
    from sqlalchemy import text
    from app.database import SessionLocal
    with SessionLocal() as db:
        result = db.execute(text("DELETE FROM sessions WHERE expires_at < now()"))
        db.commit()
        return result.rowcount


async def _session_cleanup_loop() -> None:
    """Delete expired sessions every hour without blocking the event loop."""
    loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(3600)
        try:
            removed = await loop.run_in_executor(None, _sync_cleanup_sessions)
            logger.info("Session cleanup: removed %d expired session(s)", removed)
        except Exception as exc:
            logger.warning("Session cleanup failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Start background tasks on startup, cancel them on shutdown."""
    global _polling_task, _session_cleanup_task, _runpod_watchdog_task

    logger.info("Starting Jane Communication Automation backend (env=%s)", settings.app_env)

    # Start email polling background task
    from app.services.email_intake import start_polling_loop
    _polling_task = asyncio.create_task(start_polling_loop(), name="email-polling")
    logger.info("Email polling task started")

    # Start session cleanup background task
    _session_cleanup_task = asyncio.create_task(_session_cleanup_loop(), name="session-cleanup")
    logger.info("Session cleanup task started")

    # Start RunPod idle-stop watchdog. No-ops itself when orchestration is
    # disabled (no RUNPOD_POD_ID configured), so it's safe to start in every env.
    from app.services.runpod_watchdog import start_watchdog_loop
    _runpod_watchdog_task = asyncio.create_task(start_watchdog_loop(), name="runpod-watchdog")
    logger.info("RunPod watchdog task started")

    yield  # Application is running

    # Shutdown
    for task in (_polling_task, _session_cleanup_task, _runpod_watchdog_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
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

    # ── Request ID middleware (innermost — applied first on ingress) ───────────
    app.add_middleware(RequestIdMiddleware)

    # ── CORS ───────────────────────────────────────────────────────────────────
    # Explicit methods and headers are required when allow_credentials=True.
    # Wildcards ("*") are silently rejected by browsers for credentialed requests.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-CSRF-Token"],
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
    # Phase 3
    app.include_router(tier_rules.router, prefix="/api/v1")
    app.include_router(audit_log.router, prefix="/api/v1")
    app.include_router(system_settings.router, prefix="/api/v1")
    app.include_router(integrations.router, prefix="/api/v1")
    app.include_router(runpod.router, prefix="/api/v1")

    # ── Health check ───────────────────────────────────────────────────────────
    @app.get("/health", include_in_schema=False)
    async def health() -> dict:
        return {"status": "ok"}

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
