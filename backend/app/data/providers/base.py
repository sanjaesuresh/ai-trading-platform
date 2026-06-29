"""Provider-agnostic market-data interface.

Any implementation of MarketDataProvider must return a DataFrame in the
normalized shape described by PROVIDER_COLUMNS. That shape is a strict superset
of the Phase 1 loader shape (market_data_loader.REQUIRED_COLUMNS) so the existing
data-quality gate accepts provider output unchanged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd

from app.data.market_data_loader import REQUIRED_COLUMNS

# Full column contract for provider output.  The first six match the Phase 1
# loader exactly so check_data_quality passes without modification.
PROVIDER_COLUMNS: list[str] = [
    *REQUIRED_COLUMNS,   # timestamp, open, high, low, close, volume
    "adj_close",         # vendor-supplied or computed split+dividend adjusted close
    "div_cash",          # cash dividend per share for this bar (0.0 when no event)
    "split_factor",      # split multiplier applied on this bar (1.0 when no event)
]


class MarketDataProvider(ABC):
    """Abstract contract for market-data access.

    All implementations must be idempotent — calling fetch_daily twice with
    the same arguments must return identical frames.  Credentials (if any)
    are injected at construction time via environment-sourced config, never as
    hard-coded literals.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short provider identifier (e.g. ``"tiingo"``) recorded in the audit row."""
        raise NotImplementedError

    @abstractmethod
    def fetch_daily(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Return daily OHLCV + corporate-action data for *symbol* over [start, end].

        The returned DataFrame:
        - Has exactly the columns in PROVIDER_COLUMNS (may have more; callers
          should not rely on extra columns).
        - Is sorted ascending by ``timestamp``, with a fresh integer RangeIndex.
        - Contains no null values in the six REQUIRED_COLUMNS.
        - Passes ``check_data_quality`` without blocking errors.
        - Is a new frame — the implementation must not hold a reference that the
          caller could mutate.

        Raises ``MarketDataError`` (from market_data_loader) on data problems,
        or a provider-specific exception on network/auth failures.
        """
        raise NotImplementedError
