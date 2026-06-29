"""Feature engineering adds indicators and never mutates its input."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.data.feature_engineering import INDICATOR_COLUMNS, add_technical_indicators


def _frame(rows: int = 80) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 100.0 + np.cumsum(rng.normal(0, 1, rows))
    close = np.maximum(close, 1.0)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2023-01-02", periods=rows, freq="D"),
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": rng.integers(1_000, 2_000, rows).astype(float),
        }
    )


def test_indicators_are_added() -> None:
    frame = _frame()
    out = add_technical_indicators(frame)
    for col in INDICATOR_COLUMNS:
        assert col in out.columns


def test_input_is_not_mutated() -> None:
    frame = _frame()
    original_cols = list(frame.columns)
    snapshot = frame.copy(deep=True)
    add_technical_indicators(frame)
    assert list(frame.columns) == original_cols
    pd.testing.assert_frame_equal(frame, snapshot)


def test_indicators_eventually_have_values() -> None:
    out = add_technical_indicators(_frame())
    # After the longest warm-up (SMA-50), later rows are populated.
    assert out["sma_50"].iloc[-1] == out["sma_50"].iloc[-1]  # not NaN
    assert not np.isnan(out["rsi_14"].iloc[-1])
    assert not np.isnan(out["macd_signal"].iloc[-1])
