"""Callable news-ingestion commands: backfill and incremental (Phase 5 M7).

Thin wiring on top of the news DB-I/O layer, mirroring
``app.data.ingestion.commands``. Selects the provider from config (Tiingo news
when a key is set, otherwise the credential-free offline provider), opens a
session, and runs the requested mode over the configured universe.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.data.news_ingestion.db import backfill_news_symbols, ingest_news_incremental
from app.data.news_providers.base import NewsProvider
from app.data.news_providers.offline import OfflineNewsProvider
from app.data.news_providers.tiingo_news import TiingoNewsProvider

log = get_logger(__name__)

# Conservative spacing between Tiingo requests, inside the free-tier ceiling.
_TIINGO_MIN_INTERVAL_S = 1.5


def make_news_provider(settings: Settings) -> NewsProvider:
    """Return the news provider chosen from config.

    Tiingo news when a key is configured; otherwise the offline provider rooted at
    the configured news directory (created if missing so a fresh checkout yields
    empty-but-valid news rather than a crash — sparse/absent news is normal).
    """
    if settings.tiingo_api_key:
        return TiingoNewsProvider(
            settings.tiingo_api_key, min_interval_s=_TIINGO_MIN_INTERVAL_S
        )
    news_dir = settings.news_data_path
    news_dir.mkdir(parents=True, exist_ok=True)
    return OfflineNewsProvider(news_dir)


def run_news_backfill(
    symbols: list[str] | None = None,
    *,
    end: date | None = None,
    session: Session | None = None,
    settings: Settings | None = None,
):
    """Backfill full configured news history for *symbols* (defaults to universe)."""
    settings = settings or get_settings()
    symbols = symbols or list(settings.backfill_universe)
    end = end or date.today()
    start = date.fromisoformat(settings.backfill_start)
    provider = make_news_provider(settings)

    log.info("News backfill (%s): %s from %s to %s", provider.name, symbols, start, end)
    owns_session = session is None
    session = session or SessionLocal()
    try:
        return backfill_news_symbols(session, provider, symbols, start, end)
    finally:
        if owns_session:
            session.close()


def run_news_incremental(
    symbols: list[str] | None = None,
    *,
    end: date | None = None,
    session: Session | None = None,
    settings: Settings | None = None,
):
    """Fetch only post-latest news for *symbols* (defaults to the universe)."""
    settings = settings or get_settings()
    symbols = symbols or list(settings.backfill_universe)
    end = end or date.today()
    default_start = date.fromisoformat(settings.backfill_start)
    provider = make_news_provider(settings)

    log.info("News incremental (%s): %s through %s", provider.name, symbols, end)
    owns_session = session is None
    session = session or SessionLocal()
    try:
        return [
            ingest_news_incremental(
                session, provider, symbol, end, default_start=default_start
            )
            for symbol in symbols
        ]
    finally:
        if owns_session:
            session.close()
