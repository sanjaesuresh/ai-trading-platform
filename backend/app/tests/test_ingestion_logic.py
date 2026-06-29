"""Pure-logic tests for the ingestion package.

All tests are DB-free and run with ``pytest`` from ``backend/`` without Docker,
matching the Phase 1 test conventions.

Covers:
  - compute_incremental_slice: backfill, incremental, no-new-rows, out-of-order
    timestamps, index reset, non-mutation of input.
  - build_upsert_rows: correct keys, count, symbol, empty input.
  - build_audit_summary: success and failure cases.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from app.data.ingestion.logic import (
    build_audit_summary,
    build_upsert_rows,
    compute_incremental_slice,
    compute_incremental_start,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_frame(n: int = 5, start: str = "2023-01-02") -> pd.DataFrame:
    """Minimal provider-format frame with *n* daily business-day bars."""
    ts = pd.date_range(start, periods=n, freq="B")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [1_000_000 + i * 1_000 for i in range(n)],
            "adj_close": [100.5 + i for i in range(n)],
            "div_cash": [0.0] * n,
            "split_factor": [1.0] * n,
        }
    )


# ---------------------------------------------------------------------------
# compute_incremental_slice
# ---------------------------------------------------------------------------


def test_backfill_returns_full_frame() -> None:
    """When latest_stored_ts is None, the whole provider frame is returned."""
    frame = _make_frame(5)
    result = compute_incremental_slice(None, frame)
    assert len(result) == 5


def test_backfill_all_timestamps_present() -> None:
    frame = _make_frame(5)
    result = compute_incremental_slice(None, frame)
    pd.testing.assert_series_equal(
        result["timestamp"].reset_index(drop=True),
        frame["timestamp"].reset_index(drop=True),
    )


def test_incremental_returns_only_newer_rows() -> None:
    """Rows equal to or older than the cutoff are excluded."""
    frame = _make_frame(5)
    # Cutoff at the 3rd bar (index 2) → only bars 3 and 4 (indices 3,4) remain.
    cutoff: datetime = frame["timestamp"].iloc[2].to_pydatetime()
    result = compute_incremental_slice(cutoff, frame)
    assert len(result) == 2
    assert (result["timestamp"] > pd.Timestamp(cutoff)).all()


def test_incremental_exact_cutoff_excluded() -> None:
    """The cutoff timestamp itself is NOT included (strictly greater than)."""
    frame = _make_frame(5)
    cutoff = frame["timestamp"].iloc[0].to_pydatetime()
    result = compute_incremental_slice(cutoff, frame)
    # First bar is at the cutoff — must be excluded.
    assert (result["timestamp"] > pd.Timestamp(cutoff)).all()


def test_no_new_rows_when_cutoff_at_last_bar() -> None:
    """All bars already stored → empty slice."""
    frame = _make_frame(5)
    cutoff = frame["timestamp"].iloc[-1].to_pydatetime()
    result = compute_incremental_slice(cutoff, frame)
    assert len(result) == 0


def test_incremental_slice_resets_index() -> None:
    """The returned slice must always have a fresh integer RangeIndex."""
    frame = _make_frame(5)
    cutoff = frame["timestamp"].iloc[2].to_pydatetime()
    result = compute_incremental_slice(cutoff, frame)
    assert list(result.index) == list(range(len(result)))


def test_backfill_resets_index() -> None:
    # Even the backfill path must reset the index.
    frame = _make_frame(5)
    result = compute_incremental_slice(None, frame)
    assert list(result.index) == list(range(5))


def test_incremental_slice_does_not_mutate_input() -> None:
    """Input frame must not be modified."""
    frame = _make_frame(5)
    original_len = len(frame)
    original_index = list(frame.index)
    compute_incremental_slice(frame["timestamp"].iloc[1].to_pydatetime(), frame)
    assert len(frame) == original_len
    assert list(frame.index) == original_index


def test_out_of_order_input_still_filters_correctly() -> None:
    """Filter is based on timestamp values, not row order — shuffled input works."""
    frame = _make_frame(5)
    shuffled = frame.sample(frac=1, random_state=42).reset_index(drop=True)
    cutoff_ts = pd.Timestamp("2023-01-04")
    result = compute_incremental_slice(cutoff_ts.to_pydatetime(), shuffled)
    # Every returned row must be strictly after the cutoff.
    assert (result["timestamp"] > cutoff_ts).all()


def test_duplicate_timestamps_in_input_filtered_by_cutoff() -> None:
    """Even if the provider frame has duplicates, the filter applies correctly."""
    frame = _make_frame(3)
    # Inject a duplicate of the first bar.
    frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    cutoff = frame["timestamp"].iloc[1].to_pydatetime()
    result = compute_incremental_slice(cutoff, frame)
    # Only bars strictly after the 2nd bar's timestamp should remain.
    assert (result["timestamp"] > pd.Timestamp(cutoff)).all()


# ---------------------------------------------------------------------------
# compute_incremental_start
# ---------------------------------------------------------------------------


def test_incremental_start_backfill_returns_default() -> None:
    """No stored bars → request from the configured default start."""
    default = date(2015, 1, 1)
    assert compute_incremental_start(None, default) == default


def test_incremental_start_is_day_after_latest() -> None:
    """With stored bars, the fetch starts the day after the latest one."""
    latest = datetime(2023, 6, 30, 0, 0, 0)
    assert compute_incremental_start(latest, date(2015, 1, 1)) == date(2023, 7, 1)


# ---------------------------------------------------------------------------
# build_upsert_rows
# ---------------------------------------------------------------------------

_EXPECTED_KEYS = {
    "symbol", "timestamp", "open", "high", "low", "close",
    "volume", "adj_close", "div_cash", "split_factor",
}


def test_build_upsert_rows_count() -> None:
    frame = _make_frame(3)
    rows = build_upsert_rows("AAPL", frame)
    assert len(rows) == 3


def test_build_upsert_rows_keys() -> None:
    frame = _make_frame(1)
    rows = build_upsert_rows("AAPL", frame)
    assert set(rows[0].keys()) == _EXPECTED_KEYS


def test_build_upsert_rows_symbol_propagated() -> None:
    frame = _make_frame(3)
    rows = build_upsert_rows("SPY", frame)
    assert all(r["symbol"] == "SPY" for r in rows)


def test_build_upsert_rows_timestamp_is_python_datetime() -> None:
    frame = _make_frame(2)
    rows = build_upsert_rows("AAPL", frame)
    for r in rows:
        assert isinstance(r["timestamp"], datetime)


def test_build_upsert_rows_numeric_values_are_float() -> None:
    frame = _make_frame(1)
    rows = build_upsert_rows("AAPL", frame)
    r = rows[0]
    for key in ("open", "high", "low", "close", "volume", "adj_close", "div_cash", "split_factor"):
        assert isinstance(r[key], float), f"Expected float for '{key}'"


def test_build_upsert_rows_empty_frame() -> None:
    empty = _make_frame(0)
    rows = build_upsert_rows("AAPL", empty)
    assert rows == []


# ---------------------------------------------------------------------------
# build_audit_summary
# ---------------------------------------------------------------------------


def test_audit_summary_success_status() -> None:
    summary = build_audit_summary(100, 50)
    assert summary.status == "completed"


def test_audit_summary_success_no_error() -> None:
    summary = build_audit_summary(100, 50)
    assert summary.error is None


def test_audit_summary_success_counts() -> None:
    summary = build_audit_summary(100, 50)
    assert summary.rows_fetched == 100
    assert summary.rows_written == 50


def test_audit_summary_failure_status() -> None:
    summary = build_audit_summary(100, 0, error="Quality gate failed")
    assert summary.status == "failed"


def test_audit_summary_failure_error_message() -> None:
    summary = build_audit_summary(100, 0, error="Quality gate failed")
    assert summary.error == "Quality gate failed"


def test_audit_summary_failure_counts() -> None:
    summary = build_audit_summary(100, 0, error="Quality gate failed")
    assert summary.rows_fetched == 100
    assert summary.rows_written == 0


def test_audit_summary_zero_written_no_error_is_completed() -> None:
    """Zero rows written without an error means no new bars — still completed."""
    summary = build_audit_summary(5, 0)
    assert summary.status == "completed"
    assert summary.error is None
