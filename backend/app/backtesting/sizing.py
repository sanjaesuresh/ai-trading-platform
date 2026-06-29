"""Volatility-targeted position sizing.

Computes the fraction of available cash to deploy on a buy so that the
expected annualised volatility of the position matches ``target_vol``,
bounded by ``max_fraction``.

Annualisation assumes daily returns (factor: ``sqrt(252)``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np


def compute_position_fraction(
    returns: Sequence[float],
    target_vol: float,
    max_fraction: float,
) -> float:
    """Return the fraction of cash to deploy, targeting ``target_vol``.

    Parameters
    ----------
    returns:
        Close-to-close periodic returns (e.g. ``close[i] / close[i-1] - 1``)
        for the lookback window ending at the current bar.  Must not be mutated.
    target_vol:
        Desired annualised volatility as a decimal (e.g. ``0.15`` for 15 %).
    max_fraction:
        Hard cap on the resulting fraction.  The return value is always in
        ``[0, max_fraction]``.

    Returns
    -------
    float
        ``min(target_vol / realized_vol, max_fraction)``, clamped to
        ``[0, max_fraction]``.

    When volatility cannot be estimated — fewer than 2 returns, zero std, NaN,
    or non-finite — returns ``0.0`` so the engine skips the entry. That is the
    conservative choice: deploying max allocation precisely when risk is
    unmeasurable would invert the purpose of a vol targeter.
    """
    # Guard the cap itself against pathological values.
    max_fraction = float(max_fraction)
    if not (math.isfinite(max_fraction) and max_fraction > 0.0):
        return 0.0

    # Need at least 2 observations for sample std (ddof=1).
    if len(returns) < 2:
        # Too few returns to estimate vol — skip the trade (conservative).
        return 0.0

    arr = np.asarray(returns, dtype=float)

    # Any non-finite value in the series makes the estimate unreliable.
    if not np.all(np.isfinite(arr)):
        return 0.0  # conservative skip: non-finite input

    realized_vol_daily = float(arr.std(ddof=1))

    # Annualise by sqrt(252) for daily bars.
    realized_vol = realized_vol_daily * math.sqrt(252)

    # Zero or non-finite annualised vol → flat/constant-price window; skip.
    if not (math.isfinite(realized_vol) and realized_vol > 0.0):
        return 0.0  # conservative skip: zero/NaN vol

    fraction = float(target_vol) / realized_vol

    # Clamp to [0, max_fraction]; negative target_vol is guarded by gt=0
    # in the Pydantic schema, but we clamp defensively here.
    return float(np.clip(fraction, 0.0, max_fraction))
