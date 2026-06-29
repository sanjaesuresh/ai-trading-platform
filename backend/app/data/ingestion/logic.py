"""Pure ingestion logic — no database dependency, fully unit-testable.

All functions here are free of SQLAlchemy sessions, network calls, and side
effects.  They are the correctness core; the DB-I/O layer in db.py calls them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timedelta

import pandas as pd


@dataclass
class IngestionSummary:
    """Outcome of one ingestion run — produced without touching the database."""

    rows_fetched: int
    rows_written: int
    status: str  # "completed" or "failed"
    error: str | None


def compute_incremental_slice(
    latest_stored_ts: datetime | None,
    provider_frame: pd.DataFrame,
) -> pd.DataFrame:
    """Return only the rows from *provider_frame* that are strictly newer than
    *latest_stored_ts*.

    Backfill case
    -------------
    When *latest_stored_ts* is ``None`` (no bars stored yet), the full frame is
    returned — this is the initial backfill path.

    Incremental case
    ----------------
    Only rows whose ``timestamp`` column is strictly greater than
    *latest_stored_ts* are returned.  Rows equal to or older than the cutoff are
    silently dropped, making re-runs idempotent.

    The returned frame always has a fresh integer RangeIndex.  The input is not
    mutated.
    """
    if latest_stored_ts is None:
        return provider_frame.copy().reset_index(drop=True)

    cutoff = pd.Timestamp(latest_stored_ts)
    mask = provider_frame["timestamp"] > cutoff
    return provider_frame.loc[mask].copy().reset_index(drop=True)


def compute_incremental_start(
    latest_stored_ts: datetime | None,
    default_start: date_type,
) -> date_type:
    """Return the start date an incremental fetch should request.

    Backfill case
    -------------
    When *latest_stored_ts* is ``None`` (no bars stored yet), *default_start* is
    returned — the provider is asked for the full configured history.

    Incremental case
    ----------------
    When bars exist, the start is the day *after* the latest stored bar, so the
    provider is only asked for the post-latest range (respecting rate limits).
    The strictly-greater incremental slice in :func:`compute_incremental_slice`
    still dedups defensively, so requesting the same day is harmless.

    Pure function — no database, no network.
    """
    if latest_stored_ts is None:
        return default_start
    return latest_stored_ts.date() + timedelta(days=1)


def build_upsert_rows(symbol: str, frame: pd.DataFrame) -> list[dict]:
    """Convert a provider-format frame into dicts ready for the MarketData upsert.

    Each returned dict maps directly to ``MarketData`` column names so the DB
    layer can pass it straight to ``session.execute(pg_insert(MarketData).values(rows))``.

    The input frame is not mutated.  Returns an empty list if *frame* is empty.
    """
    if frame.empty:
        return []

    rows: list[dict] = []
    for _, row in frame.iterrows():
        rows.append(
            {
                "symbol": symbol,
                "timestamp": row["timestamp"].to_pydatetime(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "adj_close": float(row["adj_close"]),
                "div_cash": float(row["div_cash"]),
                "split_factor": float(row["split_factor"]),
            }
        )
    return rows


def build_audit_summary(
    rows_fetched: int,
    rows_written: int,
    *,
    error: str | None = None,
) -> IngestionSummary:
    """Compute the audit summary from ingestion outcomes.

    The *status* is derived purely from whether *error* is set:
    - ``error`` is not None → "failed"
    - otherwise → "completed"

    Zero *rows_written* without an error is valid and means no new bars were
    available (incremental run where all fetched bars were already stored).

    Pure function — no database, no session.
    """
    status = "failed" if error is not None else "completed"
    return IngestionSummary(
        rows_fetched=rows_fetched,
        rows_written=rows_written,
        status=status,
        error=error,
    )
