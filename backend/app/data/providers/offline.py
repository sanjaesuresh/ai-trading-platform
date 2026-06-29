"""Credential-free offline provider backed by local CSV files.

This is the default for tests and CI.  It reuses the Phase 1 loader for raw
OHLCV parsing and synthesizes the adjustment fields (no corporate actions in
plain CSVs: div_cash=0.0, split_factor=1.0, adj_close=close).

Directory layout expected by this provider::

    <base_dir>/<symbol>.csv    (one file per symbol, Phase 1 OHLCV format)

Path traversal is prevented: any symbol that would resolve outside base_dir
raises ``MarketDataError``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from app.data.market_data_loader import MarketDataError, load_ohlcv_csv
from app.data.providers.base import MarketDataProvider


class OfflineProvider(MarketDataProvider):
    """Market-data provider backed by local CSV files under a base directory.

    Parameters
    ----------
    base_dir:
        Directory that contains per-symbol CSV files.  Must exist.
    """

    def __init__(self, base_dir: str | Path) -> None:
        resolved = Path(base_dir).resolve()
        if not resolved.is_dir():
            raise MarketDataError(f"Offline provider base_dir does not exist: {resolved}")
        self._base_dir = resolved

    @property
    def name(self) -> str:
        return "offline"

    def fetch_daily(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Return daily OHLCV + adjustment passthrough for *symbol* over [start, end].

        Reads ``<base_dir>/<symbol>.csv``.  The adjustment fields are synthetic:
        div_cash=0.0, split_factor=1.0, adj_close=close — accurate for plain
        historical CSVs with no corporate-action events embedded.
        """
        csv_path = self._resolve_symbol_path(symbol)
        raw = load_ohlcv_csv(csv_path)

        # Filter to the requested date range (inclusive on both ends).
        dates = raw["timestamp"].dt.normalize()
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        mask = (dates >= start_ts) & (dates <= end_ts)
        frame = raw.loc[mask].copy().reset_index(drop=True)

        # Synthesize adjustment columns: no corporate actions in plain OHLCV CSVs.
        frame["adj_close"] = frame["close"]
        frame["div_cash"] = 0.0
        frame["split_factor"] = 1.0

        return frame

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_symbol_path(self, symbol: str) -> Path:
        """Return the CSV path for *symbol*, rejecting path traversal attempts."""
        # Disallow any path separator characters in the symbol name.
        if "/" in symbol or "\\" in symbol or ".." in symbol:
            raise MarketDataError(
                f"Symbol '{symbol}' contains invalid path characters."
            )
        candidate = (self._base_dir / f"{symbol}.csv").resolve()
        # Guard: resolved path must remain under base_dir.
        try:
            candidate.relative_to(self._base_dir)
        except ValueError as exc:
            raise MarketDataError(
                f"Symbol '{symbol}' resolved outside the allowed data directory."
            ) from exc
        return candidate
