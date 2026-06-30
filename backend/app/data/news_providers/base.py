"""Provider-agnostic news interface (Phase 5 M1).

Mirrors the market-data provider contract (``app.data.providers.base``): any
``NewsProvider`` returns a DataFrame in the normalized shape described by
``NEWS_COLUMNS``.

The shape carries **two** timestamps — a publish timestamp and a first-seen
(ingest/crawl) timestamp — because the Phase 5 availability-time cutoff keys on
``max(publish, first_seen)``, not publish alone (plan §2). A back-dated or
revised article must never retroactively apply to a decision that could not have
seen it, so first-seen is a required field in the contract output, never derived
later.

Both timestamps are tz-aware UTC. Daily bars downstream are tz-naive; the
feature builder (M4) normalizes both sides to a single DST-correct UTC frame, so
the provider's job here is only to surface unambiguous UTC instants.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any

import pandas as pd

# Full column contract for news-provider output. Implementations return exactly
# these columns, in this order.
NEWS_COLUMNS: list[str] = [
    "item_id",        # provider-stable id for the article (dedup key)
    "symbol",         # tradable symbol the item is attributed to
    "published_at",   # publish timestamp, tz-aware UTC
    "first_seen_at",  # first-seen / ingest (crawl) timestamp, tz-aware UTC
    "headline",       # title
    "body",           # body or summary text
    "source",         # publisher / source name
    "url",            # canonical article url
]

# Columns that must never be null in provider output. The two timestamps are
# load-bearing for the availability-time cutoff, so a missing one is a hard error.
NEWS_REQUIRED_COLUMNS: list[str] = [
    "item_id",
    "symbol",
    "published_at",
    "first_seen_at",
]


class NewsProviderError(Exception):
    """A news provider could not produce a valid frame (file/parse/contract)."""


class NewsProvider(ABC):
    """Abstract contract for point-in-time news access.

    All implementations must be idempotent — calling ``fetch_news`` twice with
    the same arguments returns identical frames. Credentials (if any) are
    injected at construction time from environment-sourced config, never as
    hard-coded literals.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short provider identifier (e.g. ``"tiingo_news"``) for the audit row."""
        raise NotImplementedError

    @abstractmethod
    def fetch_news(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Return news items for *symbol* published in [*start*, *end*].

        The returned DataFrame:
        - Has exactly the columns in ``NEWS_COLUMNS``, in that order.
        - Has tz-aware UTC ``published_at`` and ``first_seen_at``.
        - Is sorted ascending by ``published_at``, with a fresh RangeIndex.
        - Contains no nulls in ``NEWS_REQUIRED_COLUMNS``.
        - Is a new frame the caller may freely mutate.

        Raises a provider-specific exception (or ``NewsProviderError``) on
        network/auth/parse failures.
        """
        raise NotImplementedError


def to_utc(value: Any) -> pd.Timestamp:
    """Parse *value* into a tz-aware UTC timestamp.

    A tz-naive value is assumed to already be UTC (the contract's frame); a
    tz-aware value is converted to UTC. Either way the result is an unambiguous
    UTC instant the downstream cutoff can compare without DST ambiguity.
    """
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def empty_news_frame() -> pd.DataFrame:
    """An empty frame with exactly ``NEWS_COLUMNS`` (for empty date ranges)."""
    cols: dict[str, pd.Series] = {}
    for col in NEWS_COLUMNS:
        if col in ("published_at", "first_seen_at"):
            cols[col] = pd.Series(dtype="datetime64[ns, UTC]")
        else:
            cols[col] = pd.Series(dtype="object")
    return pd.DataFrame(cols)


def build_news_frame(records: list[dict[str, Any]], symbol: str) -> pd.DataFrame:
    """Normalize contract-keyed item dicts into a ``NEWS_COLUMNS`` frame.

    Each record uses the contract field names (``item_id``, ``published_at``,
    ``first_seen_at``, ``headline``, ``body``, ``source``, ``url``); ``symbol``
    is supplied by the caller (we fetch per symbol). ``first_seen_at`` is
    required by the contract, but a record that omits it falls back to its
    publish time so a malformed feed degrades to publish-only rather than
    crashing. Output is sorted by ``published_at`` with a fresh RangeIndex.

    Raises ``NewsProviderError`` if a record is missing ``item_id`` or
    ``published_at``.
    """
    if not records:
        return empty_news_frame()

    rows: list[dict[str, Any]] = []
    for raw in records:
        if "item_id" not in raw or raw["item_id"] in (None, ""):
            raise NewsProviderError(f"News item for {symbol} is missing 'item_id'.")
        if "published_at" not in raw or raw["published_at"] in (None, ""):
            raise NewsProviderError(
                f"News item for {symbol} is missing 'published_at'."
            )
        first_seen = raw.get("first_seen_at") or raw["published_at"]
        rows.append(
            {
                "item_id": str(raw["item_id"]),
                "symbol": symbol,
                "published_at": to_utc(raw["published_at"]),
                "first_seen_at": to_utc(first_seen),
                "headline": str(raw.get("headline") or ""),
                "body": str(raw.get("body") or ""),
                "source": str(raw.get("source") or ""),
                "url": str(raw.get("url") or ""),
            }
        )

    frame = pd.DataFrame.from_records(rows)
    frame = frame.sort_values("published_at").reset_index(drop=True)
    return frame[NEWS_COLUMNS]
