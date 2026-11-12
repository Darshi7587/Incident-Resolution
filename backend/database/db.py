"""SQLite database engine, session factory, and initialization helpers."""

from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from backend.config import get_settings

Base = declarative_base()

_engine = None
_SessionLocal = None


def _ensure_sqlite_dir(database_url: str) -> None:
    """Ensure parent directory exists when using a local SQLite file URL."""
    if database_url.startswith("sqlite:///"):
        raw_path = database_url.replace("sqlite:///", "", 1)
        if raw_path and raw_path != ":memory:":
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)


def get_engine():
    """Lazily create and return the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _ensure_sqlite_dir(settings.database_url)
        connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
        _engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
    return _engine


def get_session_factory():
    """Return configured sessionmaker bound to the active engine."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine(), future=True)
    return _SessionLocal


def reset_engine() -> None:
    """Reset cached engine and session factory (useful for tests with overridden DB URLs)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def init_db() -> None:
    """Import ORM models and create all SQLite tables if they do not exist."""
    from backend.database import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def check_db_connection() -> bool:
    """Verify SQLite database connectivity."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
