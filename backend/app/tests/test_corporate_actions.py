"""Corporate-action awareness in the data-quality gate.

A large raw close-to-close gap on a split bar is legitimate and must not be
flagged; an unexplained gap of the same size must be. Dividends are small enough
not to trip the threshold. All pure-logic / DB-free.
"""

from __future__ import annotations

import pandas as pd

from app.data.data_quality import check_data_quality


def _provider_frame(
    closes: list[float],
    *,
    split_factors: list[float] | None = None,
    div_cash: list[float] | None = None,
) -> pd.DataFrame:
    """Build a clean PROVIDER_COLUMNS frame with the given closes.

    OHLC brackets each close so the only thing under test is the jump warning.
    """
    n = len(closes)
    ts = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": list(closes),
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * n,
            "adj_close": closes,
            "div_cash": div_cash if div_cash is not None else [0.0] * n,
            "split_factor": split_factors if split_factors is not None else [1.0] * n,
        }
    )


def _has_jump_warning(frame: pd.DataFrame) -> bool:
    report = check_data_quality(frame)
    return any("price jump" in w for w in report.warnings)


def test_split_bar_not_flagged() -> None:
    # 100 -> 40 is a -60% raw gap, but a 2:1-style split on that bar explains it.
    frame = _provider_frame(
        [100.0, 100.0, 40.0, 41.0, 42.0],
        split_factors=[1.0, 1.0, 2.0, 1.0, 1.0],
    )
    report = check_data_quality(frame)
    assert report.passed  # warnings never block
    assert not _has_jump_warning(frame)


def test_unexplained_gap_flagged() -> None:
    # Same -60% gap, but split_factor stays 1.0 → nothing explains it.
    frame = _provider_frame(
        [100.0, 100.0, 40.0, 41.0, 42.0],
        split_factors=[1.0, 1.0, 1.0, 1.0, 1.0],
    )
    report = check_data_quality(frame)
    assert report.passed
    assert _has_jump_warning(frame)


def test_dividend_does_not_false_trigger() -> None:
    # A normal dividend bar moves price far less than the 50% threshold.
    frame = _provider_frame(
        [100.0, 100.5, 99.5, 100.0, 100.5],
        div_cash=[0.0, 0.0, 0.75, 0.0, 0.0],
    )
    assert not _has_jump_warning(frame)


def test_plain_csv_frame_without_adj_columns_still_warns() -> None:
    # No split_factor column (Phase 1 CSV shape) → original behaviour: flag it.
    frame = _provider_frame([100.0, 100.0, 40.0, 41.0, 42.0]).drop(
        columns=["adj_close", "div_cash", "split_factor"]
    )
    assert _has_jump_warning(frame)
