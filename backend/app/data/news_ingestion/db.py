"""Thin DB-I/O layer for news ingestion.

The only place in the news-ingestion package that touches SQLAlchemy sessions.
Pure logic lives in ``logic.py``; the cleaning gate lives in
``app.data.news_quality``.

Postgres-only. The upsert uses ``ON CONFLICT DO NOTHING`` targeting
``uq_news_symbol_item_content`` — an article's stored content is immutable for a
given content hash, so a re-ingest is a no-op and a revised body lands as a new
row at its own first-seen.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.data.news_ingestion.logic import (
    NewsIngestionSummary,
    build_news_audit_summary,
    build_news_upsert_rows,
    compute_incremental_news_slice,
    compute_incremental_news_start,
)
from app.data.news_providers.base import NewsProvider
from app.data.news_quality import check_and_clean_news
from app.models_db.news_article import NewsArticle
from app.models_db.news_ingestion_run import NewsIngestionRun

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def get_latest_first_seen(session: Session, symbol: str) -> datetime | None:
    """Return the most-recent stored ``first_seen_at`` for *symbol*, or None."""
    return session.scalar(
        select(func.max(NewsArticle.first_seen_at)).where(NewsArticle.symbol == symbol)
    )


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def upsert_news_articles(session: Session, rows: list[dict]) -> int:
    """Idempotent insert of *rows* into ``news_articles``.

    ``ON CONFLICT DO NOTHING`` on ``uq_news_symbol_item_content``: re-ingesting
    identical content is a no-op; a revised body (new content_hash) is a new row.
    Returns the number of input rows (Postgres rowcount is unreliable here).
    """
    if not rows:
        return 0
    stmt = pg_insert(NewsArticle).values(rows)
    stmt = stmt.on_conflict_do_nothing(constraint="uq_news_symbol_item_content")
    session.execute(stmt)
    return len(rows)


def _create_news_ingestion_run(
    session: Session,
    provider_name: str,
    symbol: str,
    range_start: date,
    range_end: date,
) -> NewsIngestionRun:
    run = NewsIngestionRun(
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


def _finalize_news_ingestion_run(
    session: Session,
    run: NewsIngestionRun,
    summary: NewsIngestionSummary,
) -> None:
    run.status = summary.status
    run.items_fetched = summary.items_fetched
    run.items_written = summary.items_written
    run.items_dropped = summary.items_dropped
    run.error = summary.error
    run.finished_at = datetime.now(UTC)
    session.commit()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def ingest_news_symbol(
    session: Session,
    provider: NewsProvider,
    symbol: str,
    start: date,
    end: date,
    *,
    valid_symbols: Iterable[str] | None = None,
) -> NewsIngestionRun:
    """Orchestrate one news-ingestion run for *symbol* over [*start*, *end*].

    1. Create a NewsIngestionRun audit row ("running").
    2. Fetch items from *provider*.
    3. Run the news data-quality gate (clean per-item; abort only on a structural
       error).
    4. Compute the incremental slice (items newer than the latest stored
       first-seen; None → backfill).
    5. Upsert into ``news_articles`` (ON CONFLICT DO NOTHING).
    6. Finalize the audit row.

    Safe to re-run: the upsert is idempotent. On any unexpected exception the
    audit row is finalized as "failed".
    """
    run = _create_news_ingestion_run(session, provider.name, symbol, start, end)
    items_fetched = 0
    items_written = 0
    items_dropped = 0

    try:
        frame = provider.fetch_news(symbol, start, end)
        items_fetched = len(frame)
        log.info(
            "Fetched %d news item(s) for %s from '%s'",
            items_fetched,
            symbol,
            provider.name,
        )

        clean, report = check_and_clean_news(frame, valid_symbols=valid_symbols)
        if not report.passed:
            error_msg = "; ".join(report.errors)
            log.warning("News quality gate failed for %s: %s", symbol, error_msg)
            summary = build_news_audit_summary(items_fetched, 0, 0, error=error_msg)
            _finalize_news_ingestion_run(session, run, summary)
            return run
        items_dropped = report.items_dropped

        latest = get_latest_first_seen(session, symbol)
        new_frame = compute_incremental_news_slice(latest, clean)
        rows = build_news_upsert_rows(new_frame, provider=provider.name)
        items_written = upsert_news_articles(session, rows)

        summary = build_news_audit_summary(items_fetched, items_written, items_dropped)
        _finalize_news_ingestion_run(session, run, summary)
        log.info(
            "News ingest done for %s: %d written, %d dropped, %d fetched",
            symbol,
            items_written,
            items_dropped,
            items_fetched,
        )

    except Exception as exc:
        log.error("News ingestion failed for %s: %s", symbol, exc)
        summary = build_news_audit_summary(
            items_fetched, items_written, items_dropped, error=str(exc)
        )
        try:
            _finalize_news_ingestion_run(session, run, summary)
        except Exception:
            log.exception("Could not finalize NewsIngestionRun %s after failure", run.id)

    return run


def backfill_news_symbols(
    session: Session,
    provider: NewsProvider,
    symbols: list[str],
    start: date,
    end: date,
) -> list[NewsIngestionRun]:
    """Backfill [*start*, *end*] news for each symbol; symbols are independent."""
    runs: list[NewsIngestionRun] = []
    for symbol in symbols:
        runs.append(
            ingest_news_symbol(
                session, provider, symbol, start, end, valid_symbols=symbols
            )
        )
    return runs


def ingest_news_incremental(
    session: Session,
    provider: NewsProvider,
    symbol: str,
    end: date,
    *,
    default_start: date,
) -> NewsIngestionRun:
    """Fetch only the post-latest news range for *symbol* up to *end*.

    Start is the day of the latest stored first-seen (or *default_start* when
    nothing is stored). When already current (start after *end*) this is a
    recorded no-op rather than an empty-fetch failure.
    """
    latest = get_latest_first_seen(session, symbol)
    start = compute_incremental_news_start(latest, default_start)
    if start > end:
        log.info("News for %s already current through %s; nothing to fetch.", symbol, end)
        run = _create_news_ingestion_run(session, provider.name, symbol, start, end)
        _finalize_news_ingestion_run(session, run, build_news_audit_summary(0, 0, 0))
        return run
    return ingest_news_symbol(
        session, provider, symbol, start, end, valid_symbols=[symbol]
    )
