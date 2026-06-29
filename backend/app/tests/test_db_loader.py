"""Tests for the database source for backtests (db_loader).

All tests are DB-free and run with ``pytest`` from ``backend/`` without Docker.

Covers:
  - orm_rows_to_frame: column shape, row count, RangeIndex.
  - Adjusted-price transform: ratio=1.0 (offline case), ratio!=1.0 (M2 case).
  - NULL adj_close fallback to raw close.
  - Non-mutation of input.
  - Empty input.
  - Output passes the Phase 1 data-quality gate.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from app.data.data_quality import check_data_quality
from app.data.db_loader import orm_rows_to_frame

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def _make_rows(
    n: int = 5,
    *,
    adj_close_override: list[float] | None = None,
    adj_close_none: bool = False,
) -> list[Any]:
    """Return fake ORM-like objects that mirror the MarketData row interface.

    Parameters
    ----------
    n:
        Number of rows to generate.
    adj_close_override:
        If provided, use these values for adj_close (must be length *n*).
    adj_close_none:
        If True, set adj_close to None on every row (simulates NULL in DB).
    """
    ts_list = pd.date_range("2023-01-02", periods=n, freq="B").to_pydatetime().tolist()
    rows: list[Any] = []
    for i, ts in enumerate(ts_list):
        close = 100.5 + i
        if adj_close_none:
            adj = None
        elif adj_close_override is not None:
            adj = adj_close_override[i]
        else:
            adj = close  # offline case: adj_close == close
        rows.append(
            SimpleNamespace(
                timestamp=ts,
                open=100.0 + i,
                high=101.0 + i,
                low=99.0 + i,
                close=close,
                volume=float(1_000_000 + i * 1_000),
                adj_close=adj,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Shape / contract
# ---------------------------------------------------------------------------


def test_frame_has_required_ohlcv_columns() -> None:
    rows = _make_rows(5)
    frame = orm_rows_to_frame(rows)
    for col in _OHLCV_COLUMNS:
        assert col in frame.columns, f"Missing column: {col}"


def test_frame_row_count_matches_input() -> None:
    rows = _make_rows(7)
    frame = orm_rows_to_frame(rows)
    assert len(frame) == 7


def test_frame_index_is_range() -> None:
    rows = _make_rows(5)
    frame = orm_rows_to_frame(rows)
    assert isinstance(frame.index, pd.RangeIndex)
    assert list(frame.index) == list(range(5))


def test_frame_timestamps_are_pandas_timestamps() -> None:
    rows = _make_rows(3)
    frame = orm_rows_to_frame(rows)
    assert frame["timestamp"].dtype == "datetime64[ns]" or pd.api.types.is_datetime64_any_dtype(
        frame["timestamp"]
    )


def test_frame_is_sorted_by_timestamp() -> None:
    rows = _make_rows(5)
    frame = orm_rows_to_frame(rows)
    assert frame["timestamp"].is_monotonic_increasing


# ---------------------------------------------------------------------------
# Adjusted-price transform: offline case (ratio = 1.0)
# ---------------------------------------------------------------------------


def test_offline_close_equals_adj_close() -> None:
    """When adj_close == close, the output close must equal adj_close."""
    rows = _make_rows(5)
    frame = orm_rows_to_frame(rows)
    for i, row in enumerate(rows):
        assert frame.loc[i, "close"] == pytest.approx(row.adj_close)


def test_offline_open_unchanged_when_ratio_is_one() -> None:
    rows = _make_rows(5)
    frame = orm_rows_to_frame(rows)
    for i, row in enumerate(rows):
        assert frame.loc[i, "open"] == pytest.approx(row.open)


def test_offline_high_unchanged_when_ratio_is_one() -> None:
    rows = _make_rows(5)
    frame = orm_rows_to_frame(rows)
    for i, row in enumerate(rows):
        assert frame.loc[i, "high"] == pytest.approx(row.high)


def test_offline_low_unchanged_when_ratio_is_one() -> None:
    rows = _make_rows(5)
    frame = orm_rows_to_frame(rows)
    for i, row in enumerate(rows):
        assert frame.loc[i, "low"] == pytest.approx(row.low)


def test_offline_volume_unchanged() -> None:
    rows = _make_rows(5)
    frame = orm_rows_to_frame(rows)
    for i, row in enumerate(rows):
        assert frame.loc[i, "volume"] == pytest.approx(row.volume)


# ---------------------------------------------------------------------------
# Adjusted-price transform: ratio != 1.0 (M2 preview)
# ---------------------------------------------------------------------------


def test_adjustment_ratio_applied_to_close() -> None:
    """adj_close is used directly as the close column."""
    # adj_close is half of close → ratio = 0.5.
    n = 3
    adj_overrides = [50.25, 50.75, 51.25]
    rows = _make_rows(n, adj_close_override=adj_overrides)
    frame = orm_rows_to_frame(rows)
    for i in range(n):
        assert frame.loc[i, "close"] == pytest.approx(adj_overrides[i])


def test_adjustment_ratio_scales_open() -> None:
    n = 3
    adj_overrides = [50.25, 50.75, 51.25]
    rows = _make_rows(n, adj_close_override=adj_overrides)
    frame = orm_rows_to_frame(rows)
    for i, row in enumerate(rows):
        ratio = row.adj_close / row.close
        assert frame.loc[i, "open"] == pytest.approx(row.open * ratio)


def test_adjustment_ratio_scales_high() -> None:
    n = 3
    adj_overrides = [50.25, 50.75, 51.25]
    rows = _make_rows(n, adj_close_override=adj_overrides)
    frame = orm_rows_to_frame(rows)
    for i, row in enumerate(rows):
        ratio = row.adj_close / row.close
        assert frame.loc[i, "high"] == pytest.approx(row.high * ratio)


def test_adjustment_ratio_scales_low() -> None:
    n = 3
    adj_overrides = [50.25, 50.75, 51.25]
    rows = _make_rows(n, adj_close_override=adj_overrides)
    frame = orm_rows_to_frame(rows)
    for i, row in enumerate(rows):
        ratio = row.adj_close / row.close
        assert frame.loc[i, "low"] == pytest.approx(row.low * ratio)


def test_adjustment_preserves_ohlc_ordering() -> None:
    """After scaling, adjusted open must still be within adjusted high/low."""
    n = 5
    # adj_close below close → ratio < 1.0 — scaling shrinks uniformly.
    adj_overrides = [c * 0.8 for c in [100.5, 101.5, 102.5, 103.5, 104.5]]
    rows = _make_rows(n, adj_close_override=adj_overrides)
    frame = orm_rows_to_frame(rows)
    assert (frame["open"] <= frame["high"]).all()
    assert (frame["open"] >= frame["low"]).all()
    assert (frame["close"] <= frame["high"]).all()
    assert (frame["close"] >= frame["low"]).all()


# ---------------------------------------------------------------------------
# NULL adj_close fallback
# ---------------------------------------------------------------------------


def test_null_adj_close_falls_back_to_raw_close() -> None:
    rows = _make_rows(3, adj_close_none=True)
    frame = orm_rows_to_frame(rows)
    for i, row in enumerate(rows):
        assert frame.loc[i, "close"] == pytest.approx(row.close)


def test_null_adj_close_ratio_is_one() -> None:
    """When adj_close is NULL the ratio must be 1.0 → open/high/low unchanged."""
    rows = _make_rows(3, adj_close_none=True)
    frame = orm_rows_to_frame(rows)
    for i, row in enumerate(rows):
        assert frame.loc[i, "open"] == pytest.approx(row.open)
        assert frame.loc[i, "high"] == pytest.approx(row.high)
        assert frame.loc[i, "low"] == pytest.approx(row.low)


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------


def test_frame_passes_data_quality_gate() -> None:
    rows = _make_rows(10)
    frame = orm_rows_to_frame(rows)
    report = check_data_quality(frame)
    assert report.passed, f"Data quality errors: {report.errors}"


def test_adjusted_frame_passes_data_quality_gate() -> None:
    """Adjusted prices (ratio != 1.0) must still pass the quality gate."""
    n = 10
    adj_overrides = [c * 0.9 for c in [100.5 + i for i in range(n)]]
    rows = _make_rows(n, adj_close_override=adj_overrides)
    frame = orm_rows_to_frame(rows)
    report = check_data_quality(frame)
    assert report.passed, f"Data quality errors: {report.errors}"


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty_frame() -> None:
    frame = orm_rows_to_frame([])
    assert len(frame) == 0


def test_empty_input_has_correct_columns() -> None:
    frame = orm_rows_to_frame([])
    for col in _OHLCV_COLUMNS:
        assert col in frame.columns
