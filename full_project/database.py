"""Database setup shared by the API and scripts.

- Uses DATABASE_URL when provided (recommended on DigitalOcean: managed Postgres).
- Falls back to a local SQLite file for development.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


BASE_DIR = Path(__file__).resolve().parent


def _pick_postgres_driver_prefix() -> str:
    """Pick a Postgres SQLAlchemy URL prefix based on installed driver.

    - psycopg (v3) preferred when available
    - psycopg2 next
    - otherwise, leave it as plain postgresql:// and let SQLAlchemy error clearly
    """
    try:
        import psycopg  # type: ignore  # noqa: F401

        return "postgresql+psycopg://"
    except Exception:
        try:
            import psycopg2  # type: ignore  # noqa: F401

            return "postgresql+psycopg2://"
        except Exception:
            return "postgresql://"


def normalize_db_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    # Heroku-style URLs sometimes use "postgres://"
    if url.startswith("postgres://"):
        return url.replace("postgres://", _pick_postgres_driver_prefix(), 1)

    # If a user provides postgresql:// without an explicit driver, pick one.
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", _pick_postgres_driver_prefix(), 1)

    return url


# Prefer an injected DATABASE_URL (DigitalOcean App Platform / Droplet env var).
_env_db_url = normalize_db_url(os.getenv("DATABASE_URL", ""))
DATABASE_URL = _env_db_url or f"sqlite:///{(BASE_DIR / 'app.db').as_posix()}"


def _make_engine(db_url: str) -> Engine:
    connect_args = {}
    engine_kwargs = {
        "pool_pre_ping": True,
    }

    # SQLite needs this when used from multiple threads (e.g., FastAPI + Uvicorn workers).
    if db_url.startswith("sqlite:"):
        connect_args["check_same_thread"] = False

    return create_engine(db_url, connect_args=connect_args, **engine_kwargs)


engine: Engine = _make_engine(DATABASE_URL)


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a SQLAlchemy Session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
