"""Data-quality checks: blocking errors stop the pipeline; clean data passes."""

from __future__ import annotations

import pandas as pd

from app.data.data_quality import check_data_quality


def _clean_frame(rows: int = 5) -> pd.DataFrame:
    ts = pd.date_range("2023-01-02", periods=rows, freq="D")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": [100.0 + i for i in range(rows)],
            "high": [101.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [1_000 + i for i in range(rows)],
        }
    )


def test_clean_dataset_passes() -> None:
    report = check_data_quality(_clean_frame())
    assert report.passed
    assert report.errors == []
    assert report.row_count == 5


def test_missing_column_fails() -> None:
    frame = _clean_frame().drop(columns=["volume"])
    report = check_data_quality(frame)
    assert not report.passed
    assert any("volume" in e for e in report.errors)


def test_negative_price_fails() -> None:
    frame = _clean_frame()
    frame.loc[2, "close"] = -5.0
    report = check_data_quality(frame)
    assert not report.passed
    assert any("close" in e for e in report.errors)


def test_duplicate_timestamp_fails() -> None:
    frame = _clean_frame()
    frame.loc[3, "timestamp"] = frame.loc[2, "timestamp"]
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    report = check_data_quality(frame)
    assert not report.passed
    assert any("duplicate" in e.lower() for e in report.errors)


def test_high_below_low_fails() -> None:
    frame = _clean_frame()
    frame.loc[1, "high"] = frame.loc[1, "low"] - 1.0
    report = check_data_quality(frame)
    assert not report.passed
    assert any("high < low" in e for e in report.errors)
