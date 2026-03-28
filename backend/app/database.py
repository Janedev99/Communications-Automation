"""
SQLAlchemy engine, session factory, and declarative Base.

All database interaction goes through the `get_db` dependency which yields
a scoped session and guarantees commit/rollback/close semantics.
"""
from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def _build_engine():
    settings = get_settings()
    kwargs: dict = {
        "pool_pre_ping": True,   # Detect stale connections
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 1800,    # Recycle connections every 30 min
    }
    engine = create_engine(settings.database_url, **kwargs)

    # Ensure UTC timezone for every new connection
    @event.listens_for(engine, "connect")
    def set_timezone(dbapi_conn, _connection_record):
        with dbapi_conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'UTC'")

    return engine


engine = _build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # Keep attributes accessible after commit
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session.

    Usage::

        @router.get("/items")
        def list_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_db_connection() -> bool:
    """Return True if the database is reachable. Used in health checks."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
