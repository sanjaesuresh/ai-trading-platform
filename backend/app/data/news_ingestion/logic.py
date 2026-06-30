"""Pure news-ingestion logic — no database, no network, fully unit-testable.

The DB-I/O layer in ``db.py`` calls these. ``content_hash`` is the shared
dedup/cache key: the article-storage key (M2) and the LLM annotation cache (M3)
both build on it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime

import pandas as pd


def content_hash(headline: str, body: str) -> str:
    """Stable sha256 of an article's text (headline + body).

    A revised body changes the hash, which is exactly how a revision becomes a
    new availability event downstream rather than a silent in-place correction
    (plan §2). A null-separator prevents headline/body boundary collisions.
    """
    h = hashlib.sha256()
    h.update((headline or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((body or "").encode("utf-8"))
    return h.hexdigest()


def compute_incremental_news_slice(
    latest_first_seen: datetime | None,
    clean_frame: pd.DataFrame,
) -> pd.DataFrame:
    """Return only items whose ``first_seen_at`` is strictly newer than the latest
    stored first-seen for the symbol.

    News availability is keyed on first-seen, so incremental ingest advances on
    first-seen, not publish date — a back-dated article surfacing today (its
    first-seen is today) is correctly treated as new. Backfill (``None``) returns
    the whole frame. The unique storage constraint is the correctness backstop;
    this is the volume optimization. Input is not mutated.
    """
    if latest_first_seen is None:
        return clean_frame.copy().reset_index(drop=True)
    if clean_frame.empty:
        return clean_frame.copy().reset_index(drop=True)

    cutoff = pd.Timestamp(latest_first_seen)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    seen = pd.to_datetime(clean_frame["first_seen_at"], utc=True)
    mask = seen > cutoff
    return clean_frame.loc[mask].copy().reset_index(drop=True)


def compute_incremental_news_start(
    latest_first_seen: datetime | None,
    default_start: date_type,
) -> date_type:
    """Return the start date an incremental news fetch should request.

    Backfill (``None``) → *default_start*. Otherwise the day of the latest stored
    first-seen (not the day after) so an article first seen later on the same day
    is still requested; the strictly-greater slice dedups defensively.
    """
    if latest_first_seen is None:
        return default_start
    return latest_first_seen.date()


def build_news_upsert_rows(frame: pd.DataFrame, *, provider: str) -> list[dict]:
    """Convert a cleaned ``NEWS_COLUMNS`` frame into ``NewsArticle`` upsert dicts.

    Computes ``content_hash`` per row. Input frame is not mutated; empty frame →
    empty list.
    """
    if frame.empty:
        return []

    rows: list[dict] = []
    for _, row in frame.iterrows():
        headline = str(row["headline"] or "")
        body = str(row["body"] or "")
        rows.append(
            {
                "symbol": str(row["symbol"]),
                "item_id": str(row["item_id"]),
                "published_at": pd.Timestamp(row["published_at"]).to_pydatetime(),
                "first_seen_at": pd.Timestamp(row["first_seen_at"]).to_pydatetime(),
                "headline": headline,
                "body": body,
                "source": (str(row["source"]) if row["source"] else None),
                "url": (str(row["url"]) if row["url"] else None),
                "content_hash": content_hash(headline, body),
                "provider": provider,
            }
        )
    return rows


@dataclass
class NewsIngestionSummary:
    """Outcome of one news-ingestion run — produced without touching the DB."""

    items_fetched: int
    items_written: int
    items_dropped: int
    status: str  # "completed" or "failed"
    error: str | None


def build_news_audit_summary(
    items_fetched: int,
    items_written: int,
    items_dropped: int,
    *,
    error: str | None = None,
) -> NewsIngestionSummary:
    """Compute the audit summary. ``error`` set → "failed", else "completed".

    Zero items written without an error is valid (incremental run with nothing
    new, or a window with no news). Pure function.
    """
    status = "failed" if error is not None else "completed"
    return NewsIngestionSummary(
        items_fetched=items_fetched,
        items_written=items_written,
        items_dropped=items_dropped,
        status=status,
        error=error,
    )