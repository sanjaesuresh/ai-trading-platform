"""Data-quality inspection of a loaded OHLCV frame.

Produces a structured report. A blocking error means the pipeline must not
proceed to backtesting; a warning is informational only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.data.market_data_loader import REQUIRED_COLUMNS

# A timestamp gap larger than this many times the median spacing is suspicious.
_GAP_FACTOR = 5.0
# A single-bar absolute close-to-close move larger than this fraction is suspicious.
_JUMP_FRACTION = 0.5


@dataclass
class DataQualityReport:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    row_count: int = 0
    start_timestamp: pd.Timestamp | None = None
    end_timestamp: pd.Timestamp | None = None


def check_data_quality(frame: pd.DataFrame) -> DataQualityReport:
    """Inspect an OHLCV frame and return a pass/fail report.

    Blocking errors: missing columns, nulls in required columns, duplicate
    timestamps, non-monotonic timestamps, negative/zero prices, negative volume,
    high < low, open/close outside the high–low range. Warnings: large timestamp
    gaps and suspicious single-bar price jumps.
    """
    errors: list[str] = []
    warnings: list[str] = []

    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        # Without the required columns no further check is meaningful.
        return DataQualityReport(
            passed=False,
            errors=[f"Missing required column(s): {', '.join(missing)}."],
            row_count=int(len(frame)),
        )

    row_count = int(len(frame))
    start_ts = frame["timestamp"].iloc[0] if row_count else None
    end_ts = frame["timestamp"].iloc[-1] if row_count else None

    if row_count == 0:
        return DataQualityReport(
            passed=False,
            errors=["Dataset is empty."],
            row_count=0,
        )

    for col in REQUIRED_COLUMNS:
        if frame[col].isna().any():
            errors.append(f"Column '{col}' contains {int(frame[col].isna().sum())} null value(s).")

    ts = frame["timestamp"]
    dup_count = int(ts.duplicated().sum())
    if dup_count:
        errors.append(f"{dup_count} duplicate timestamp(s).")
    if not ts.is_monotonic_increasing:
        errors.append("Timestamps are not in non-decreasing order.")

    price_cols = ["open", "high", "low", "close"]
    for col in price_cols:
        if (frame[col] <= 0).any():
            errors.append(f"Column '{col}' has {int((frame[col] <= 0).sum())} non-positive value(s).")

    if (frame["volume"] < 0).any():
        errors.append(f"{int((frame['volume'] < 0).sum())} row(s) have negative volume.")

    high_lt_low = frame["high"] < frame["low"]
    if high_lt_low.any():
        errors.append(f"{int(high_lt_low.sum())} row(s) have high < low.")

    open_oob = (frame["open"] > frame["high"]) | (frame["open"] < frame["low"])
    close_oob = (frame["close"] > frame["high"]) | (frame["close"] < frame["low"])
    if open_oob.any():
        errors.append(f"{int(open_oob.sum())} row(s) have open outside the high–low range.")
    if close_oob.any():
        errors.append(f"{int(close_oob.sum())} row(s) have close outside the high–low range.")

    # Warnings — only meaningful with monotonic, gap-comparable timestamps.
    if row_count >= 3 and ts.is_monotonic_increasing and dup_count == 0:
        deltas = ts.diff().dropna()
        median_delta = deltas.median()
        # pandas-stubs types Series.median() loosely; this is Timedelta arithmetic.
        if median_delta is not None and median_delta > pd.Timedelta(0):  # type: ignore[operator]
            big_gaps = int((deltas > median_delta * _GAP_FACTOR).sum())
            if big_gaps:
                warnings.append(f"{big_gaps} large timestamp gap(s) (> {_GAP_FACTOR}x median spacing).")

    close_change = frame["close"].pct_change().abs()
    big_jumps = int((close_change > _JUMP_FRACTION).sum())
    if big_jumps:
        warnings.append(
            f"{big_jumps} suspicious single-bar price jump(s) (> {_JUMP_FRACTION:.0%} close-to-close)."
        )

    return DataQualityReport(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        row_count=row_count,
        start_timestamp=start_ts,
        end_timestamp=end_ts,
    )
