"""Generate a reproducible synthetic daily OHLCV CSV for Phase 1.

The data is SYNTHETIC and labeled as such. It is a trend-plus-noise random walk
deliberately tuned so the trend-following rules produce both buys and sells —
otherwise the engine and metrics tests would be vacuous. It implies nothing
about real markets.

Run:  python data/sample/generate_sample.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260629
N_DAYS = 320
START_PRICE = 100.0
START_DATE = "2023-01-02"
OUT = Path(__file__).resolve().parent / "sample_ohlcv.csv"


def generate() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)

    # Alternating drift regimes create the up/down trends the strategy reacts to.
    regimes = [
        (60, 0.0010),   # up
        (50, -0.0012),  # down
        (70, 0.0014),   # up
        (45, -0.0010),  # down
        (95, 0.0011),   # up
    ]
    drifts = np.concatenate([np.full(length, mu) for length, mu in regimes])[:N_DAYS]
    if len(drifts) < N_DAYS:
        drifts = np.concatenate([drifts, np.full(N_DAYS - len(drifts), 0.0008)])

    daily_vol = 0.012
    shocks = rng.normal(0.0, daily_vol, size=N_DAYS)
    log_returns = drifts + shocks

    close = START_PRICE * np.exp(np.cumsum(log_returns))
    prev_close = np.concatenate([[START_PRICE], close[:-1]])

    # Open near the prior close with a small gap.
    open_ = prev_close * (1.0 + rng.normal(0.0, 0.002, size=N_DAYS))

    # Build internally consistent highs/lows around open & close.
    base_hi = np.maximum(open_, close)
    base_lo = np.minimum(open_, close)
    high = base_hi * (1.0 + np.abs(rng.normal(0.0, 0.004, size=N_DAYS)))
    low = base_lo * (1.0 - np.abs(rng.normal(0.0, 0.004, size=N_DAYS)))

    # Volume trends mildly with absolute returns so the volume filter can trigger.
    base_volume = 1_000_000
    volume = (base_volume * (1.0 + 6.0 * np.abs(log_returns)) *
              (1.0 + rng.normal(0.0, 0.1, size=N_DAYS)))
    volume = np.maximum(volume, 1_000).round().astype(int)

    dates = pd.bdate_range(start=START_DATE, periods=N_DAYS)

    return pd.DataFrame(
        {
            "timestamp": dates.strftime("%Y-%m-%d"),
            "open": open_.round(4),
            "high": high.round(4),
            "low": low.round(4),
            "close": close.round(4),
            "volume": volume,
        }
    )


if __name__ == "__main__":
    df = generate()
    df.to_csv(OUT, index=False)
    print(f"Wrote {len(df)} rows to {OUT}")
