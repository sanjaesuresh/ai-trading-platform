"""Callable ingestion commands: backfill and incremental.

Thin wiring on top of the DB-I/O layer. Selects the provider from config (Tiingo
when ``TIINGO_API_KEY`` is set, otherwise the credential-free offline provider),
opens a session, and runs the requested mode over a symbol universe.

This is the *command* surface the M2 plan asks for; scheduling it nightly is M6.
Run it directly::

    python -m app.data.ingestion backfill SPY AAPL
    python -m app.data.ingestion incremental
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.data.ingestion.db import backfill_symbols, ingest_incremental
from app.data.providers.base import MarketDataProvider
from app.data.providers.offline import OfflineProvider
from app.data.providers.tiingo import TiingoProvider
from app.models_db.ingestion_run import IngestionRun

log = get_logger(__name__)

# Conservative spacing between Tiingo requests during a multi-symbol run, well
# inside the free-tier 50 req/hr ceiling.
_TIINGO_MIN_INTERVAL_S = 1.5


def make_provider(settings: Settings) -> tuple[MarketDataProvider, str]:
    """Return ``(provider, provider_name)`` chosen from config.

    Tiingo when an API key is configured; otherwise the offline provider rooted
    at the allowed data directory. The offline path needs no credentials and is
    what CI exercises.
    """
    if settings.tiingo_api_key:
        provider: MarketDataProvider = TiingoProvider(
            settings.tiingo_api_key, min_interval_s=_TIINGO_MIN_INTERVAL_S
        )
        return provider, "tiingo"
    return OfflineProvider(settings.allowed_data_path), "offline"


def run_backfill(
    symbols: list[str] | None = None,
    *,
    end: date | None = None,
    session: Session | None = None,
    settings: Settings | None = None,
) -> list[IngestionRun]:
    """Backfill full configured history for *symbols* (defaults to the universe)."""
    settings = settings or get_settings()
    symbols = symbols or list(settings.backfill_universe)
    end = end or date.today()
    start = date.fromisoformat(settings.backfill_start)
    provider, provider_name = make_provider(settings)

    log.info("Backfill (%s): %s from %s to %s", provider_name, symbols, start, end)
    owns_session = session is None
    session = session or SessionLocal()
    try:
        return backfill_symbols(
            session, provider, symbols, start, end, provider_name=provider_name
        )
    finally:
        if owns_session:
            session.close()


def run_incremental(
    symbols: list[str] | None = None,
    *,
    end: date | None = None,
    session: Session | None = None,
    settings: Settings | None = None,
) -> list[IngestionRun]:
    """Fetch only post-latest bars for *symbols* (defaults to the universe)."""
    settings = settings or get_settings()
    symbols = symbols or list(settings.backfill_universe)
    end = end or date.today()
    default_start = date.fromisoformat(settings.backfill_start)
    provider, provider_name = make_provider(settings)

    log.info("Incremental (%s): %s through %s", provider_name, symbols, end)
    owns_session = session is None
    session = session or SessionLocal()
    try:
        return [
            ingest_incremental(
                session,
                provider,
                symbol,
                end,
                default_start=default_start,
                provider_name=provider_name,
            )
            for symbol in symbols
        ]
    finally:
        if owns_session:
            session.close()
