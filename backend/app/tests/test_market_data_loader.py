"""Loader: required columns, parse errors, ascending sort, duplicate drop."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.data.market_data_loader import MarketDataError, load_ohlcv_csv

_HEADER = "timestamp,open,high,low,close,volume\n"


def _write(path: Path, body: str) -> Path:
    path.write_text(_HEADER + body)
    return path


def test_file_not_found_raises(tmp_path: Path) -> None:
    with pytest.raises(MarketDataError, match="not found"):
        load_ohlcv_csv(tmp_path / "missing.csv")


def test_missing_required_column_raises(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("timestamp,open,high,low,close\n2023-01-02,100,101,99,100.5\n")
    with pytest.raises(MarketDataError, match="volume"):
        load_ohlcv_csv(path)


def test_unparseable_timestamp_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "data.csv", "not-a-date,100,101,99,100.5,1000\n")
    with pytest.raises(MarketDataError, match="unparseable timestamp"):
        load_ohlcv_csv(path)


def test_non_numeric_price_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "data.csv", "2023-01-02,100,101,99,N/A,1000\n")
    with pytest.raises(MarketDataError, match="non-numeric 'close'"):
        load_ohlcv_csv(path)


def test_output_sorted_ascending_by_timestamp(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "data.csv",
        "2023-01-04,103,104,102,103,1000\n"
        "2023-01-02,100,101,99,100,1000\n"
        "2023-01-03,101,102,100,101,1000\n",
    )
    frame = load_ohlcv_csv(path)
    assert frame["timestamp"].is_monotonic_increasing
    assert frame["timestamp"].iloc[0] == pd.Timestamp("2023-01-02")
    assert frame["timestamp"].iloc[-1] == pd.Timestamp("2023-01-04")


def test_exact_duplicate_rows_dropped(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "data.csv",
        "2023-01-02,100,101,99,100,1000\n"
        "2023-01-02,100,101,99,100,1000\n"
        "2023-01-03,101,102,100,101,1000\n",
    )
    frame = load_ohlcv_csv(path)
    assert len(frame) == 2
