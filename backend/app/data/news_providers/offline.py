"""Credential-free offline news provider backed by local JSON files.

The default for tests and CI. Directory layout::

    <base_dir>/<symbol>.json   (one file per symbol)

Each file is a JSON list of article objects using the contract field names::

    [
      {
        "item_id": "abc123",
        "published_at": "2023-01-03T15:30:00Z",
        "first_seen_at": "2023-01-03T15:35:00Z",
        "headline": "...",
        "body": "...",
        "source": "...",
        "url": "https://..."
      },
      ...
    ]

A missing per-symbol file means "no news for that symbol" and yields an empty
frame — sparse coverage is normal for news, not an error. Path traversal is
prevented exactly as in the offline market-data provider.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from app.data.news_providers.base import (
    NewsProvider,
    NewsProviderError,
    build_news_frame,
    empty_news_frame,
)


class OfflineNewsProvider(NewsProvider):
    """News provider backed by local per-symbol JSON files under a base directory.

    Parameters
    ----------
    base_dir:
        Directory that contains per-symbol JSON files. Must exist.
    """

    def __init__(self, base_dir: str | Path) -> None:
        resolved = Path(base_dir).resolve()
        if not resolved.is_dir():
            raise NewsProviderError(
                f"Offline news provider base_dir does not exist: {resolved}"
            )
        self._base_dir = resolved

    @property
    def name(self) -> str:
        return "offline_news"

    def fetch_news(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Return news items for *symbol* with a publish date in [*start*, *end*].

        Reads ``<base_dir>/<symbol>.json``. A missing file yields an empty frame.
        Filtering is on the publish *date* (inclusive both ends), so the range is
        intuitive at the calendar-day granularity callers pass.
        """
        path = self._resolve_symbol_path(symbol)
        if not path.is_file():
            return empty_news_frame()

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise NewsProviderError(
                f"Offline news file for {symbol} is unreadable: {path}"
            ) from exc
        if not isinstance(raw, list):
            raise NewsProviderError(
                f"Offline news file for {symbol} must be a JSON list: {path}"
            )

        records: list[dict[str, Any]] = list(raw)
        frame = build_news_frame(records, symbol)
        if frame.empty:
            return frame

        # Filter on the publish date (inclusive both ends).
        pub_date = frame["published_at"].dt.tz_convert("UTC").dt.normalize()
        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC")
        mask = (pub_date >= start_ts) & (pub_date <= end_ts)
        return frame.loc[mask].reset_index(drop=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_symbol_path(self, symbol: str) -> Path:
        """Return the JSON path for *symbol*, rejecting path traversal attempts."""
        if "/" in symbol or "\\" in symbol or ".." in symbol:
            raise NewsProviderError(
                f"Symbol '{symbol}' contains invalid path characters."
            )
        candidate = (self._base_dir / f"{symbol}.json").resolve()
        try:
            candidate.relative_to(self._base_dir)
        except ValueError as exc:
            raise NewsProviderError(
                f"Symbol '{symbol}' resolved outside the allowed news directory."
            ) from exc
        return candidate
