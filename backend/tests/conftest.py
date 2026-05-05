"""
Shared test fixtures for the Jane Communication Automation backend.

Strategy
--------
* SQLite in-memory database with StaticPool — all sessions share the same
  in-memory DB, so tables created by conftest are visible to app-layer sessions.
* `app.database` is monkey-patched to point to the shared test engine before
  any app code runs (env vars → settings LRU cache cleared → engine replaced).
* `KnowledgeEntry.tags` ARRAY column is replaced with JSON before create_all.
* Tests use regular sessions — no savepoint/rollback pattern (incompatible with
  StaticPool's single-connection model). Each test is responsible for creating
  its own distinct records. Between tests, table data accumulates in the
  in-memory DB; tests must not rely on absence of data created by other tests.
"""
from __future__ import annotations

import os
import warnings

# ── Set env vars BEFORE any app import (settings is lru_cache'd) ──────────────
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
os.environ["APP_SECRET_KEY"] = "test-secret-key-32-chars-minimum!!"
os.environ["APP_ENV"] = "development"
os.environ["EMAIL_PROVIDER"] = "imap"
os.environ["IMAP_USERNAME"] = "test@example.com"
os.environ["SMTP_USERNAME"] = "test@example.com"
os.environ["DRAFT_AUTO_GENERATE"] = "false"
os.environ["SHADOW_MODE"] = "false"

warnings.filterwarnings("ignore", category=UserWarning)

from datetime import datetime, timezone
from typing import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import JSON, StaticPool, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Clear the settings LRU cache so our env vars take effect
from app.config import get_settings
get_settings.cache_clear()

# ── Patch KnowledgeEntry.tags ARRAY → JSON before create_all ──────────────────
from app.models.email import KnowledgeEntry
KnowledgeEntry.__table__.c["tags"].type = JSON()

# ── Override app.database with a shared in-memory SQLite engine ───────────────
# StaticPool: all connections share one underlying connection → same in-memory DB.
import app.database as _app_db_module

_shared_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(
    bind=_shared_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

_app_db_module.engine = _shared_engine
_app_db_module.SessionLocal = _TestSession

# Import all models so they register with Base.metadata
import app.models  # noqa: F401
from app.database import Base

# Create tables once for the entire test session
Base.metadata.create_all(_shared_engine)

# ── Import app-level singletons to reset between tests ────────────────────────
import app.services.categorizer as _cat_module
import app.services.email_provider as _prov_module
from app.api import auth as _auth_module


# =============================================================================
# DB fixture — simple session, no rollback trick (StaticPool incompatible)
# =============================================================================

@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """
    Yield a plain SQLAlchemy session against the shared test DB.
    Does NOT roll back — tests accumulate data. Each test should create
    records with unique identifiers to avoid cross-test interference.
    """
    db = _TestSession()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# =============================================================================
# Seeded user fixtures
# =============================================================================

@pytest.fixture()
def admin_user(db_session: Session):
    """Create and return an admin user (Jane) — unique email per test run."""
    import uuid as _uuid
    from app.services.auth import create_user
    from app.models.user import UserRole
    suffix = str(_uuid.uuid4())[:8]
    user = create_user(
        db_session,
        email=f"jane-{suffix}@example.com",
        name="Jane Admin",
        password="AdminPass123!",
        role=UserRole.admin,
    )
    db_session.flush()
    return user


@pytest.fixture()
def staff_user(db_session: Session):
    """Create and return a staff user — unique email per test run."""
    import uuid as _uuid
    from app.services.auth import create_user
    from app.models.user import UserRole
    suffix = str(_uuid.uuid4())[:8]
    user = create_user(
        db_session,
        email=f"staff-{suffix}@example.com",
        name="Staff Member",
        password="StaffPass123!",
        role=UserRole.staff,
    )
    db_session.flush()
    return user


# =============================================================================
# App + TestClient fixtures
# =============================================================================

@pytest.fixture()
def app_instance():
    """
    FastAPI app with DB dependency overridden to use the test session factory.
    """
    from app.main import create_app
    from app.database import get_db as _original_get_db

    _app = create_app()

    def _override_get_db() -> Generator[Session, None, None]:
        db = _TestSession()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    _app.dependency_overrides[_original_get_db] = _override_get_db
    return _app


@pytest.fixture()
def client(app_instance) -> TestClient:
    """Unauthenticated TestClient."""
    return TestClient(app_instance, raise_server_exceptions=True)


def _make_logged_in_client(app_inst, user) -> TestClient:
    """Helper: create a real session token for the given User ORM object."""
    from app.services.auth import create_session, generate_csrf_token

    db = _TestSession()
    try:
        # Re-query user within this session (may be from a different session)
        from app.models.user import User
        from sqlalchemy import select
        u = db.execute(select(User).where(User.id == user.id)).scalar_one()
        _, raw_token = create_session(db, u)
        csrf = generate_csrf_token()
        db.commit()
    finally:
        db.close()

    tc = TestClient(app_inst, raise_server_exceptions=True)
    tc.cookies.set("session_token", raw_token)
    tc.cookies.set("csrf_token", csrf)
    tc.headers.update({"X-CSRF-Token": csrf})
    return tc


@pytest.fixture()
def logged_in_admin(app_instance, admin_user):
    """TestClient pre-authenticated as admin."""
    return _make_logged_in_client(app_instance, admin_user)


@pytest.fixture()
def logged_in_staff(app_instance, staff_user):
    """TestClient pre-authenticated as staff."""
    return _make_logged_in_client(app_instance, staff_user)


# =============================================================================
# Mock fixtures
# =============================================================================

@pytest.fixture()
def mock_anthropic(mocker):
    """
    Patch the Anthropic SDK to return a canned non-escalating response.
    Tests can override `mock_anthropic.messages.create.return_value`.

    The patch target moved with the LLM provider abstraction: the SDK is
    now imported lazily inside `app.services.llm_client.AnthropicLLMClient`,
    not directly in `categorizer`. Tests still get the same `messages.create`
    surface to manipulate, but they need to remember to also reset the
    llm_client singleton (we do it via reset_llm_client()) so the freshly
    patched class is picked up on the next call.
    """
    canned = MagicMock()
    canned.content = [MagicMock(
        text=(
            '{"category": "general_inquiry", "confidence": 0.9, '
            '"escalation_needed": false, "escalation_reasons": [], '
            '"summary": "Client has a general question.", '
            '"suggested_reply_tone": "professional"}'
        )
    )]
    canned.usage = MagicMock(input_tokens=100, output_tokens=50)

    # The llm_client module imports anthropic lazily, so mock the imported
    # symbol there. The categorizer doesn't own the SDK anymore.
    import anthropic as _real_anthropic
    mock_cls = mocker.patch("anthropic.Anthropic")
    mock_instance = mock_cls.return_value
    mock_instance.messages.create.return_value = canned

    # Reset both the categorizer singleton and the llm_client singleton so
    # the next get_llm_client() / get_categorizer() call rebuilds against
    # the freshly mocked SDK.
    from app.services import llm_client as _llm_module
    _llm_module.reset_llm_client()
    _cat_module._categorizer = None
    yield mock_instance
    _llm_module.reset_llm_client()
    _cat_module._categorizer = None


class RecordingEmailProvider:
    """Fake email provider that records calls for assertion in tests."""

    def __init__(self):
        self.sent_emails: list[dict] = []
        self.connect_calls: int = 0
        self.raise_on_send: Exception | None = None

    def connect(self) -> None:
        self.connect_calls += 1

    def fetch_new_emails(self):
        return []

    def mark_as_read(self, message_id: str) -> None:
        pass

    def send_email(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        reply_to_message_id: str | None = None,
        references_header: str | None = None,
        message_id: str | None = None,
    ) -> str:
        if self.raise_on_send:
            raise self.raise_on_send
        record = {
            "to": to,
            "subject": subject,
            "body_text": body_text,
            "reply_to_message_id": reply_to_message_id,
            "references_header": references_header,
            "message_id": message_id,
        }
        self.sent_emails.append(record)
        return message_id or f"<mock-{len(self.sent_emails)}@test.local>"

    def disconnect(self) -> None:
        pass


@pytest.fixture()
def mock_email_provider():
    """Replace the global email-provider singleton with a RecordingEmailProvider."""
    provider = RecordingEmailProvider()
    original = _prov_module._provider
    _prov_module._provider = provider
    yield provider
    _prov_module._provider = original


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    """Clear the in-memory login rate-limit store before/after each test."""
    _auth_module._failed_attempts.clear()
    yield
    _auth_module._failed_attempts.clear()


# =============================================================================
# Helper factory (importable by test modules)
# =============================================================================

def make_raw_email(
    *,
    message_id: str = "<test-msg-1@example.com>",
    subject: str = "Test subject",
    sender: str = "Client Name <client@example.com>",
    recipient: str = "firm@example.com",
    body_text: str = "Hello, I have a question.",
    body_html: str | None = None,
    received_at: datetime | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    provider_thread_id: str | None = None,
):
    """Convenience factory for RawEmail test instances."""
    from app.services.email_provider import RawEmail
    return RawEmail(
        message_id=message_id,
        subject=subject,
        sender=sender,
        recipient=recipient,
        body_text=body_text,
        body_html=body_html,
        received_at=received_at or datetime.now(timezone.utc),
        in_reply_to=in_reply_to,
        references=references,
        provider_thread_id=provider_thread_id,
    )
