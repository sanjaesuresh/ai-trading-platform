"""Technical indicators added to an OHLCV frame.

``add_technical_indicators`` never mutates its input: it returns a new frame
with indicator columns appended. Warm-up rows where an indicator is not yet
defined remain NaN and are handled safely downstream (the engine skips them).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Indicator columns this module produces, in addition to the OHLCV columns.
INDICATOR_COLUMNS = [
    "returns",
    "log_returns",
    "sma_20",
    "sma_50",
    "ema_20",
    "rsi_14",
    "macd",
    "macd_signal",
    "bb_upper",
    "bb_lower",
    "atr_14",
    "volatility_20",
    "volume_ma_20",
]


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder smoothing == EWMA with alpha = 1/period.
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # When average loss is zero, RSI is defined as 100 (pure uptrend).
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    return rsi


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's Average True Range."""
    high = frame["high"]
    low = frame["low"]
    prev_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def add_technical_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a new frame with technical indicators appended. Input is untouched."""
    out = frame.copy()
    close = out["close"]

    out["returns"] = close.pct_change()
    out["log_returns"] = np.log(close / close.shift(1))

    out["sma_20"] = close.rolling(window=20, min_periods=20).mean()
    out["sma_50"] = close.rolling(window=50, min_periods=50).mean()
    out["ema_20"] = close.ewm(span=20, min_periods=20, adjust=False).mean()

    out["rsi_14"] = _rsi(close, period=14)

    ema_12 = close.ewm(span=12, min_periods=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, min_periods=26, adjust=False).mean()
    out["macd"] = ema_12 - ema_26
    out["macd_signal"] = out["macd"].ewm(span=9, min_periods=9, adjust=False).mean()

    rolling_std_20 = close.rolling(window=20, min_periods=20).std()
    out["bb_upper"] = out["sma_20"] + 2.0 * rolling_std_20
    out["bb_lower"] = out["sma_20"] - 2.0 * rolling_std_20

    out["atr_14"] = _atr(out, period=14)
    out["volatility_20"] = out["returns"].rolling(window=20, min_periods=20).std()
    out["volume_ma_20"] = out["volume"].rolling(window=20, min_periods=20).mean()

    return out
