"""Thin DB-I/O layer for data ingestion.

Functions here are the only place in the ingestion package that touch
SQLAlchemy sessions or commit to the database.  Pure business logic lives in
``logic.py`` so it can be tested without Docker.

Postgres-only.  The upsert uses ``sqlalchemy.dialects.postgresql.insert`` with
``on_conflict_do_update`` targeting the ``uq_symbol_timestamp`` constraint.
Re-running ingestion for the same symbol+range converges and never duplicates.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.data.data_quality import check_data_quality
from app.data.ingestion.logic import (
    IngestionSummary,
    build_audit_summary,
    build_upsert_rows,
    compute_incremental_slice,
    compute_incremental_start,
)
from app.data.providers.base import MarketDataProvider
from app.models_db.ingestion_run import IngestionRun
from app.models_db.market_data import MarketData

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def get_latest_timestamp(session: Session, symbol: str) -> datetime | None:
    """Return the most-recent stored timestamp for *symbol*, or None if absent.

    Used to decide whether a run is a backfill (None) or incremental (datetime).
    """
    result = session.scalar(
        select(func.max(MarketData.timestamp)).where(MarketData.symbol == symbol)
    )
    return result


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def upsert_bars(session: Session, rows: list[dict]) -> int:
    """Idempotent upsert of *rows* into ``market_data``.

    Uses Postgres ``ON CONFLICT DO UPDATE`` targeting ``uq_symbol_timestamp``.
    Re-running with the same rows updates in place; no duplicates are created.

    Returns the number of rows in *rows* (not the Postgres rowcount, which is
    unreliable across upsert modes).  Returns 0 immediately on empty input.
    """
    if not rows:
        return 0

    stmt = pg_insert(MarketData).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_symbol_timestamp",
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
            "adj_close": stmt.excluded.adj_close,
            "div_cash": stmt.excluded.div_cash,
            "split_factor": stmt.excluded.split_factor,
        },
    )
    session.execute(stmt)
    return len(rows)


def _create_ingestion_run(
    session: Session,
    provider_name: str,
    symbol: str,
    range_start: date,
    range_end: date,
) -> IngestionRun:
    """Insert an IngestionRun in "running" state and flush it to get its id."""
    run = IngestionRun(
        provider=provider_name,
        symbol=symbol,
        range_start=range_start,
        range_end=range_end,
        status="running",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _finalize_ingestion_run(
    session: Session,
    run: IngestionRun,
    summary: IngestionSummary,
) -> None:
    """Update *run* with the outcome from *summary* and commit."""
    run.status = summary.status
    run.rows_fetched = summary.rows_fetched
    run.rows_written = summary.rows_written
    run.error = summary.error
    run.finished_at = datetime.now(UTC)
    session.commit()


# ---------------------------------------------------------------------------
# Orchestration entrypoint
# ---------------------------------------------------------------------------


def ingest_symbol(
    session: Session,
    provider: MarketDataProvider,
    symbol: str,
    start: date,
    end: date,
) -> IngestionRun:
    """Orchestrate one ingestion run for *symbol* over [*start*, *end*].

    Pipeline
    --------
    1. Create an IngestionRun audit row in "running" state (immediately committed).
    2. Fetch daily bars from *provider*.
    3. Run the Phase 1 data-quality gate.  If it fails, finalize as "failed"
       and return — no bars are written.
    4. Compute the incremental slice (rows strictly newer than the latest stored
       bar; None → backfill, write everything).
    5. Upsert new bars into ``market_data`` using ON CONFLICT DO UPDATE.
    6. Finalize the audit row as "completed" or "failed".

    This is safe to re-run: the upsert is idempotent so duplicate calls for
    the same symbol+range converge without creating duplicate rows or errors.

    On any unexpected exception the audit row is finalized as "failed" and the
    exception is logged; callers receive the IngestionRun for inspection.
    """
    run = _create_ingestion_run(session, provider.name, symbol, start, end)
    rows_fetched = 0
    rows_written = 0

    try:
        # Fetch from provider.
        provider_frame = provider.fetch_daily(symbol, start, end)
        rows_fetched = len(provider_frame)
        log.info("Fetched %d rows for %s from provider '%s'", rows_fetched, symbol, provider.name)

        # Data-quality gate — abort on blocking errors.
        report = check_data_quality(provider_frame)
        if not report.passed:
            error_msg = "; ".join(report.errors)
            log.warning("Data-quality gate failed for %s: %s", symbol, error_msg)
            summary = build_audit_summary(rows_fetched, 0, error=error_msg)
            _finalize_ingestion_run(session, run, summary)
            return run

        # Compute incremental slice (backfill if no stored bars yet).
        latest_ts = get_latest_timestamp(session, symbol)
        new_frame = compute_incremental_slice(latest_ts, provider_frame)
        log.info(
            "Incremental slice for %s: %d new rows (latest stored: %s)",
            symbol, len(new_frame), latest_ts,
        )

        # Build and upsert new rows.
        upsert_data = build_upsert_rows(symbol, new_frame)
        rows_written = upsert_bars(session, upsert_data)

        summary = build_audit_summary(rows_fetched, rows_written)
        _finalize_ingestion_run(session, run, summary)
        log.info("Ingestion completed for %s: %d/%d rows written", symbol, rows_written, rows_fetched)

    except Exception as exc:
        log.error("Ingestion failed for symbol %s: %s", symbol, exc)
        summary = build_audit_summary(rows_fetched, rows_written, error=str(exc))
        try:
            _finalize_ingestion_run(session, run, summary)
        except Exception:
            # Last-resort: the session may be broken; nothing more we can do.
            log.exception("Could not finalize IngestionRun %s after failure", run.id)

    return run


def backfill_symbols(
    session: Session,
    provider: MarketDataProvider,
    symbols: list[str],
    start: date,
    end: date,
) -> list[IngestionRun]:
    """Backfill full [*start*, *end*] history for each symbol in *symbols*.

    Runs :func:`ingest_symbol` once per symbol and returns the audit rows in the
    same order. Each symbol is independent: one symbol's failure (rate limit,
    bad data) is recorded on its own ``IngestionRun`` and does not abort the rest.
    Idempotent — re-running converges via the upsert.
    """
    runs: list[IngestionRun] = []
    for symbol in symbols:
        runs.append(ingest_symbol(session, provider, symbol, start, end))
    return runs


def ingest_incremental(
    session: Session,
    provider: MarketDataProvider,
    symbol: str,
    end: date,
    *,
    default_start: date,
) -> IngestionRun:
    """Fetch only the post-latest range for *symbol* up to *end*.

    The start date is the day after the latest stored bar (or *default_start*
    when nothing is stored yet), so the provider is asked only for new bars —
    keeping requests inside rate limits. When the symbol is already current
    (computed start is after *end*) this is a recorded no-op rather than an
    empty-fetch failure. Scheduling this nightly is M6; here it is a callable.
    """
    latest_ts = get_latest_timestamp(session, symbol)
    start = compute_incremental_start(latest_ts, default_start)

    if start > end:
        log.info("Symbol %s already current through %s; nothing to fetch.", symbol, end)
        run = _create_ingestion_run(session, provider.name, symbol, start, end)
        _finalize_ingestion_run(session, run, build_audit_summary(0, 0))
        return run

    return ingest_symbol(session, provider, symbol, start, end)
