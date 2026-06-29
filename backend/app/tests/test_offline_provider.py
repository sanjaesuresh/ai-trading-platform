"""Provider-interface contract tests for OfflineProvider.

All tests are pure-logic and DB-free — they run with ``pytest`` from
``backend/`` without Docker, matching the Phase 1 test conventions.

The offline provider is the credential-free implementation used by CI.
These tests assert:
  1. The returned frame matches the PROVIDER_COLUMNS shape.
  2. The frame passes check_data_quality without blocking errors.
  3. The adjustment passthrough is correct (div=0, split=1, adj_close==close).
  4. Date-range filtering is applied correctly.
  5. Path traversal in symbol names is rejected.
  6. A missing CSV raises MarketDataError cleanly.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.data.data_quality import check_data_quality
from app.data.market_data_loader import MarketDataError
from app.data.providers.base import PROVIDER_COLUMNS
from app.data.providers.offline import OfflineProvider

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _write_csv(path: Path, rows: int = 10) -> None:
    """Write a minimal valid OHLCV CSV to *path*."""
    ts = pd.date_range("2023-01-02", periods=rows, freq="B")  # business days
    df = pd.DataFrame(
        {
            "timestamp": ts.strftime("%Y-%m-%d"),
            "open": [100.0 + i for i in range(rows)],
            "high": [101.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [1_000_000 + i * 1000 for i in range(rows)],
        }
    )
    df.to_csv(path, index=False)


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Temp directory with a pre-written AAPL.csv fixture."""
    _write_csv(tmp_path / "AAPL.csv", rows=10)
    return tmp_path


@pytest.fixture()
def provider(data_dir: Path) -> OfflineProvider:
    return OfflineProvider(data_dir)


# ---------------------------------------------------------------------------
# Shape / contract tests
# ---------------------------------------------------------------------------

def test_frame_has_all_provider_columns(provider: OfflineProvider) -> None:
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    for col in PROVIDER_COLUMNS:
        assert col in frame.columns, f"Missing column: {col}"


def test_frame_is_sorted_ascending(provider: OfflineProvider) -> None:
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert frame["timestamp"].is_monotonic_increasing


def test_frame_has_integer_rangeindex(provider: OfflineProvider) -> None:
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert isinstance(frame.index, pd.RangeIndex)
    assert list(frame.index) == list(range(len(frame)))


def test_ohlcv_columns_are_non_null(provider: OfflineProvider) -> None:
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    for col in ["timestamp", "open", "high", "low", "close", "volume"]:
        assert not frame[col].isna().any(), f"Column '{col}' has nulls"


def test_frame_passes_data_quality_gate(provider: OfflineProvider) -> None:
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    report = check_data_quality(frame)
    assert report.passed, f"Data quality errors: {report.errors}"


# ---------------------------------------------------------------------------
# Adjustment passthrough tests
# ---------------------------------------------------------------------------

def test_adj_close_equals_close_for_offline_data(provider: OfflineProvider) -> None:
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    pd.testing.assert_series_equal(
        frame["adj_close"].reset_index(drop=True),
        frame["close"].reset_index(drop=True),
        check_names=False,
    )


def test_div_cash_is_zero(provider: OfflineProvider) -> None:
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert (frame["div_cash"] == 0.0).all()


def test_split_factor_is_one(provider: OfflineProvider) -> None:
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert (frame["split_factor"] == 1.0).all()


# ---------------------------------------------------------------------------
# Date-range filtering tests
# ---------------------------------------------------------------------------

def test_date_range_filters_correctly(data_dir: Path) -> None:
    """Only rows within [start, end] should be returned."""
    provider = OfflineProvider(data_dir)
    full = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    first_ts: pd.Timestamp = full["timestamp"].iloc[0]

    # Request a sub-range: one row from the start, one from the end excluded.
    sliced = provider.fetch_daily("AAPL", first_ts.date(), first_ts.date())
    assert len(sliced) == 1
    assert sliced["timestamp"].iloc[0] == first_ts

    # Requesting before the data starts yields empty frame.
    empty = provider.fetch_daily("AAPL", date(2000, 1, 1), date(2000, 1, 31))
    assert len(empty) == 0


def test_date_range_index_is_reset_after_filter(data_dir: Path) -> None:
    """After filtering the index must still be a fresh RangeIndex."""
    provider = OfflineProvider(data_dir)
    full = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    first_ts: pd.Timestamp = full["timestamp"].iloc[0]
    sliced = provider.fetch_daily("AAPL", first_ts.date(), first_ts.date())
    assert list(sliced.index) == [0]


# ---------------------------------------------------------------------------
# Error-handling tests
# ---------------------------------------------------------------------------

def test_missing_csv_raises_market_data_error(data_dir: Path) -> None:
    provider = OfflineProvider(data_dir)
    with pytest.raises(MarketDataError, match="not found"):
        provider.fetch_daily("NONEXISTENT", date(2023, 1, 1), date(2023, 12, 31))


def test_path_traversal_in_symbol_raises(data_dir: Path) -> None:
    provider = OfflineProvider(data_dir)
    with pytest.raises(MarketDataError):
        provider.fetch_daily("../secrets", date(2023, 1, 1), date(2023, 12, 31))


def test_nonexistent_base_dir_raises() -> None:
    with pytest.raises(MarketDataError, match="does not exist"):
        OfflineProvider("/tmp/this_directory_should_not_exist_phase2_m1")
