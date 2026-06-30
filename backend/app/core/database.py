"""SQLAlchemy engine, session factory, and the request-scoped session dependency.

Postgres only — the URL comes from settings (``DATABASE_URL``).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models_db.base import Base

_settings = get_settings()

engine = create_engine(_settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield a session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all_tables() -> None:
    """Create tables if they do not exist, so a fresh Postgres works immediately.

    Alembic owns schema migrations; this is the convenience path for first boot.
    """
    # Import models so they register on Base.metadata before create_all.
    from app.models_db import (  # noqa: F401
        backtest_run,
        evaluation_run,
        ingestion_run,
        market_data,
        ml_model,
        news_annotation,
        news_article,
        news_ingestion_run,
        paper_trading,
        trade,
    )

    Base.metadata.create_all(bind=engine)
