"""Load and normalize OHLCV data from a CSV into a clean pandas frame."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
_NUMERIC_COLUMNS = ["open", "high", "low", "close", "volume"]


class MarketDataError(ValueError):
    """Raised for malformed market-data CSVs, with a clear, specific message."""


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    """Read an OHLCV CSV and return a normalized frame.

    Requires columns: timestamp, open, high, low, close, volume. Parses the
    timestamp to datetime, sorts ascending by timestamp, drops exact duplicate
    rows, and returns the frame with a fresh integer index. Raises
    ``MarketDataError`` with a specific message rather than failing deep in the
    pipeline.
    """
    csv_path = Path(path)
    if not csv_path.is_file():
        raise MarketDataError(f"CSV file not found: {csv_path}")

    try:
        frame = pd.read_csv(csv_path)
    except Exception as exc:  # pragma: no cover - pandas raises many subtypes
        raise MarketDataError(f"Could not parse CSV {csv_path}: {exc}") from exc

    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise MarketDataError(
            f"CSV is missing required column(s): {', '.join(missing)}. "
            f"Required: {', '.join(REQUIRED_COLUMNS)}."
        )

    frame = frame[REQUIRED_COLUMNS].copy()

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    if frame["timestamp"].isna().any():
        bad = int(frame["timestamp"].isna().sum())
        raise MarketDataError(f"{bad} row(s) have an unparseable timestamp.")

    for col in _NUMERIC_COLUMNS:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
        if frame[col].isna().any():
            bad = int(frame[col].isna().sum())
            raise MarketDataError(f"{bad} row(s) have a non-numeric '{col}' value.")

    frame = frame.drop_duplicates()
    frame = frame.sort_values("timestamp", kind="stable").reset_index(drop=True)
    return frame
