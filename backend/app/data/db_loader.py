"""Database source for backtests.

Two concerns are kept separate:

  1. **Pure transform** (no session) — ``orm_rows_to_frame``: converts a list of
     ``MarketData`` ORM rows into the normalized OHLCV frame that the rest of the
     pipeline (``add_technical_indicators``, backtesting engine) consumes unchanged.

  2. **Thin DB-I/O** — ``query_market_data``: fetches the rows from Postgres for a
     given symbol and optional date range.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_db.market_data import MarketData


def orm_rows_to_frame(rows: list[MarketData]) -> pd.DataFrame:
    """Convert MarketData ORM rows to a normalized OHLCV frame.

    The output has exactly the same column shape as ``load_ohlcv_csv`` produces:
    ``[timestamp, open, high, low, close, volume]``.  This lets
    ``add_technical_indicators`` and the backtesting engine consume it unchanged.

    Adjusted-price transform
    ------------------------
    Backtests run on the adjusted (split- and dividend-correct) price series as
    specified in section 3.2 of the Phase 2 plan.  The transform is:

        ratio = adj_close / close   (per bar)

        adjusted_open  = raw_open  × ratio
        adjusted_high  = raw_high  × ratio
        adjusted_low   = raw_low   × ratio
        adjusted_close = adj_close  (vendor-supplied or stored)

    Scaling all four price columns by the same ratio keeps the OHLC relationships
    internally consistent (open ≤ high, low ≤ open/close, etc.) so the
    data-quality gate continues to pass on the output frame.

    For the offline provider in M1 ``adj_close == close``, so ``ratio == 1.0``
    and every price is unchanged.  When real adjusted data arrives in M2 the
    same transform produces the correctly adjusted series without any code change.

    When ``adj_close`` is NULL in the database (e.g. pre-migration legacy rows),
    the raw close is used as a fallback and ``ratio == 1.0``.

    The input list is not mutated.  Returns an empty frame (with correct columns)
    on empty input.
    """
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    timestamps = [pd.Timestamp(r.timestamp) for r in rows]
    raw_open = [r.open for r in rows]
    raw_high = [r.high for r in rows]
    raw_low = [r.low for r in rows]
    raw_close = [r.close for r in rows]
    volume = [r.volume for r in rows]

    # Resolve adj_close: fall back to raw close when the column is NULL.
    adj_close_vals = [
        r.adj_close if r.adj_close is not None else r.close
        for r in rows
    ]

    # Compute per-bar adjustment ratio.  Prices are always positive after the
    # data-quality gate on ingest; the zero guard is a safety net for legacy rows.
    # All lists are derived from the same `rows` iterable so lengths are equal.
    ratios = [
        ac / c if c != 0.0 else 1.0
        for ac, c in zip(adj_close_vals, raw_close, strict=True)
    ]

    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [o * r for o, r in zip(raw_open, ratios, strict=True)],
            "high": [h * r for h, r in zip(raw_high, ratios, strict=True)],
            "low": [lo * r for lo, r in zip(raw_low, ratios, strict=True)],
            "close": [float(ac) for ac in adj_close_vals],
            "volume": [float(v) for v in volume],
        }
    )
    return frame.reset_index(drop=True)


def query_market_data(
    session: Session,
    symbol: str,
    start: date | None = None,
    end: date | None = None,
) -> list[MarketData]:
    """Return MarketData rows for *symbol* ordered by timestamp.

    Both *start* and *end* are inclusive.  Pass ``None`` for an open-ended
    constraint on that side (i.e. all available history).

    Daily bars are stored at midnight (00:00:00); end-of-day bars on *end* are
    included by comparing against 23:59:59 of that date.
    """
    stmt = select(MarketData).where(MarketData.symbol == symbol)
    if start is not None:
        stmt = stmt.where(
            MarketData.timestamp >= datetime(start.year, start.month, start.day)
        )
    if end is not None:
        stmt = stmt.where(
            MarketData.timestamp <= datetime(end.year, end.month, end.day, 23, 59, 59)
        )
    stmt = stmt.order_by(MarketData.timestamp)
    return list(session.scalars(stmt).all())
