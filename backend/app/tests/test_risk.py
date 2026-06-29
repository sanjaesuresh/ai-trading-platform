"""Risk checks: stop/target boundary behaviour and drawdown circuit breaker."""

from __future__ import annotations

import math

from app.backtesting.risk import ExitSignal, check_drawdown_breach, check_stop_target

# ---------------------------------------------------------------------------
# Stop / target
# ---------------------------------------------------------------------------


def test_stop_fires_exactly_at_boundary() -> None:
    # close == entry * (1 - 0.10) = 90.0 → STOP.
    assert check_stop_target(100.0, 90.0, stop_loss_pct=0.10, take_profit_pct=None) == ExitSignal.STOP


def test_stop_fires_below_boundary() -> None:
    assert check_stop_target(100.0, 85.0, stop_loss_pct=0.10, take_profit_pct=None) == ExitSignal.STOP


def test_stop_does_not_fire_above_boundary() -> None:
    # close = 91 > 90 → None.
    assert check_stop_target(100.0, 91.0, stop_loss_pct=0.10, take_profit_pct=None) is None


def test_target_fires_exactly_at_boundary() -> None:
    # close == entry * (1 + 0.20) = 120.0 → TARGET.
    assert check_stop_target(100.0, 120.0, stop_loss_pct=None, take_profit_pct=0.20) == ExitSignal.TARGET


def test_target_fires_above_boundary() -> None:
    assert check_stop_target(100.0, 125.0, stop_loss_pct=None, take_profit_pct=0.20) == ExitSignal.TARGET


def test_target_does_not_fire_below_boundary() -> None:
    # close = 115 < 120 → None.
    assert check_stop_target(100.0, 115.0, stop_loss_pct=None, take_profit_pct=0.20) is None


def test_stop_wins_when_both_pcts_set_and_stop_fires() -> None:
    # close=85 triggers stop (<=90); take_profit set but not triggered (>=120).
    # Even with take_profit set, result must be STOP, not TARGET.
    result = check_stop_target(100.0, 85.0, stop_loss_pct=0.10, take_profit_pct=0.20)
    assert result == ExitSignal.STOP


def test_both_pcts_none_returns_none() -> None:
    # No levels configured → always None.
    assert check_stop_target(100.0, 50.0, stop_loss_pct=None, take_profit_pct=None) is None
    assert check_stop_target(100.0, 200.0, stop_loss_pct=None, take_profit_pct=None) is None


def test_none_stop_only_target_fires() -> None:
    assert check_stop_target(100.0, 130.0, stop_loss_pct=None, take_profit_pct=0.10) == ExitSignal.TARGET


def test_none_target_only_stop_fires() -> None:
    assert check_stop_target(100.0, 80.0, stop_loss_pct=0.10, take_profit_pct=None) == ExitSignal.STOP


def test_zero_entry_price_returns_none() -> None:
    assert check_stop_target(0.0, 90.0, stop_loss_pct=0.10, take_profit_pct=None) is None


def test_negative_entry_price_returns_none() -> None:
    assert check_stop_target(-50.0, 90.0, stop_loss_pct=0.10, take_profit_pct=None) is None


def test_nan_entry_returns_none() -> None:
    assert check_stop_target(math.nan, 90.0, stop_loss_pct=0.10, take_profit_pct=None) is None


def test_inf_entry_returns_none() -> None:
    assert check_stop_target(math.inf, 90.0, stop_loss_pct=0.10, take_profit_pct=None) is None


def test_nan_close_returns_none() -> None:
    assert check_stop_target(100.0, math.nan, stop_loss_pct=0.10, take_profit_pct=None) is None


# ---------------------------------------------------------------------------
# Drawdown breach
# ---------------------------------------------------------------------------


def test_drawdown_breach_at_exact_threshold() -> None:
    # (100 - 80) / 100 = 0.20 >= 0.20 → True.
    assert check_drawdown_breach(100.0, 80.0, threshold_pct=0.20) is True


def test_drawdown_breach_above_threshold() -> None:
    assert check_drawdown_breach(100.0, 70.0, threshold_pct=0.20) is True


def test_drawdown_no_breach_below_threshold() -> None:
    # (100 - 85) / 100 = 0.15 < 0.20 → False.
    assert check_drawdown_breach(100.0, 85.0, threshold_pct=0.20) is False


def test_drawdown_no_breach_at_peak() -> None:
    # No drawdown at all.
    assert check_drawdown_breach(100.0, 100.0, threshold_pct=0.20) is False


def test_drawdown_peak_zero_no_error() -> None:
    # Division by zero guard: peak <= 0 → False.
    assert check_drawdown_breach(0.0, 80.0, threshold_pct=0.20) is False


def test_drawdown_peak_negative_no_error() -> None:
    assert check_drawdown_breach(-100.0, -120.0, threshold_pct=0.20) is False


def test_drawdown_nan_peak_no_error() -> None:
    assert check_drawdown_breach(math.nan, 80.0, threshold_pct=0.20) is False


def test_drawdown_inf_peak_no_error() -> None:
    # inf peak would make drawdown = (inf - x) / inf = NaN → guard returns False.
    assert check_drawdown_breach(math.inf, 80.0, threshold_pct=0.20) is False


def test_drawdown_nan_current_no_error() -> None:
    assert check_drawdown_breach(100.0, math.nan, threshold_pct=0.20) is False


def test_drawdown_boundary_precision() -> None:
    # Just below threshold: 0.199999 < 0.20 → False.
    # (100 - 80.001) / 100 = 0.19999 < 0.20.
    assert check_drawdown_breach(100.0, 80.001, threshold_pct=0.20) is False
    # Just at threshold: 0.20 >= 0.20 → True.
    assert check_drawdown_breach(100.0, 80.0, threshold_pct=0.20) is True
