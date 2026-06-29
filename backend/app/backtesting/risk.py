"""Pure position-risk checks: stop/target exits and max-drawdown circuit breaker.

All functions are side-effect-free and import no engine or database modules.
They are safe to call with zero, NaN, or missing inputs — each docstring
documents the fallback.

Fill model: conditions are evaluated against the bar-N close price, and
resulting fills happen at bar N+1's open (close-trigger / next-open model).
"""

from __future__ import annotations

import math
from enum import StrEnum


class ExitSignal(StrEnum):
    """The kind of risk-triggered exit."""

    STOP = "STOP"
    TARGET = "TARGET"


def check_stop_target(
    entry_price: float,
    close_price: float,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
) -> ExitSignal | None:
    """Check whether bar-N's close triggers a stop-loss or take-profit.

    Parameters
    ----------
    entry_price:
        Effective fill price at which the position was entered (after slippage).
    close_price:
        Bar-N close price.  The fill will happen at bar N+1's open (caller's
        responsibility; this function only evaluates the condition).
    stop_loss_pct:
        Fraction below entry at which to stop out (e.g. ``0.05`` for 5 %).
        ``None`` disables the stop-loss check.
    take_profit_pct:
        Fraction above entry at which to take profit (e.g. ``0.20`` for 20 %).
        ``None`` disables the take-profit check.

    Returns
    -------
    ExitSignal | None
        ``STOP`` if ``close_price <= entry_price * (1 - stop_loss_pct)``.
        ``TARGET`` if ``close_price >= entry_price * (1 + take_profit_pct)``.
        When both conditions are met simultaneously, ``STOP`` wins (risk-first).
        ``None`` if neither condition is met or both relevant pcts are ``None``.
    """
    # Degenerate entry price makes every level meaningless.
    if not (math.isfinite(entry_price) and entry_price > 0.0):
        return None
    if not math.isfinite(close_price):
        return None

    stop_hit = (
        stop_loss_pct is not None
        and math.isfinite(stop_loss_pct)
        and stop_loss_pct > 0.0
        and close_price <= entry_price * (1.0 - stop_loss_pct)
    )
    target_hit = (
        take_profit_pct is not None
        and math.isfinite(take_profit_pct)
        and take_profit_pct > 0.0
        and close_price >= entry_price * (1.0 + take_profit_pct)
    )

    # STOP wins over TARGET (risk-first ordering).
    if stop_hit:
        return ExitSignal.STOP
    if target_hit:
        return ExitSignal.TARGET
    return None


def check_drawdown_breach(
    peak_equity: float,
    current_equity: float,
    threshold_pct: float,
) -> bool:
    """Return True when the drawdown from peak meets or exceeds ``threshold_pct``.

    Parameters
    ----------
    peak_equity:
        Running maximum equity seen up to and including the current bar.
    current_equity:
        Current marked-to-close equity.
    threshold_pct:
        Drawdown threshold as a decimal fraction (e.g. ``0.20`` for 20 %).

    Returns
    -------
    bool
        ``True`` when ``(peak_equity - current_equity) / peak_equity >= threshold_pct``.
        ``False`` when peak_equity is non-positive or non-finite (guards against
        division by zero and inverted-sign nonsense).
    """
    if not (math.isfinite(peak_equity) and peak_equity > 0.0):
        return False
    if not math.isfinite(current_equity):
        return False
    if not (math.isfinite(threshold_pct) and threshold_pct > 0.0):
        return False

    drawdown = (peak_equity - current_equity) / peak_equity
    return drawdown >= threshold_pct
