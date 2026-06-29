"""Sizing: vol targeting, cap, fallbacks for too-few / zero / NaN / inf vol."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.backtesting.sizing import compute_position_fraction


def test_high_vol_yields_fraction_below_cap() -> None:
    # Daily vol of ~5 % → annualised ~79 %.  target=15 % → fraction ≈ 0.19.
    rng = np.random.default_rng(0)
    returns = rng.normal(0.0, 0.05, 30).tolist()
    result = compute_position_fraction(returns, target_vol=0.15, max_fraction=0.95)
    assert result < 0.95
    assert result > 0.0


def test_low_vol_capped_at_max_fraction() -> None:
    # Daily vol of ~0.1 % → annualised ~1.6 %.  target=20 % >> realized → cap.
    rng = np.random.default_rng(1)
    returns = rng.normal(0.0, 0.001, 30).tolist()
    result = compute_position_fraction(returns, target_vol=0.20, max_fraction=0.50)
    assert result == pytest.approx(0.50)


def test_too_few_returns_skips_trade() -> None:
    # Single return: cannot compute sample std (ddof=1 requires n >= 2).
    # Conservative fallback: return 0.0 so the engine skips the entry rather
    # than deploying max allocation when risk is unmeasurable.
    result = compute_position_fraction([0.01], target_vol=0.15, max_fraction=0.95)
    assert result == pytest.approx(0.0)


def test_empty_returns_skips_trade() -> None:
    # No returns at all — definitely can't estimate vol; skip the trade.
    result = compute_position_fraction([], target_vol=0.15, max_fraction=0.95)
    assert result == pytest.approx(0.0)


def test_zero_vol_skips_trade() -> None:
    # All-zero returns (flat price → no movement) → std = 0 exactly.
    # Must NOT divide by zero, and must NOT deploy max allocation; skip instead.
    returns = [0.0] * 30
    result = compute_position_fraction(returns, target_vol=0.15, max_fraction=0.95)
    assert result == pytest.approx(0.0)
    assert math.isfinite(result)


def test_nan_in_returns_skips_trade() -> None:
    # NaN in the series makes the vol estimate unreliable; skip the trade.
    returns = [0.01, float("nan"), 0.02, -0.01]
    result = compute_position_fraction(returns, target_vol=0.15, max_fraction=0.95)
    assert result == pytest.approx(0.0)


def test_inf_in_returns_skips_trade() -> None:
    # Inf in the series makes the vol estimate unreliable; skip the trade.
    returns = [0.01, float("inf"), 0.02, -0.01]
    result = compute_position_fraction(returns, target_vol=0.15, max_fraction=0.95)
    assert result == pytest.approx(0.0)


def test_result_always_in_range() -> None:
    # Fuzz: result must always be in [0, max_fraction] regardless of inputs.
    rng = np.random.default_rng(42)
    max_frac = 0.80
    for _ in range(200):
        n = int(rng.integers(0, 60))
        daily_vol = float(rng.uniform(0.0, 0.15))
        returns = rng.normal(0.0, daily_vol, n).tolist()
        result = compute_position_fraction(returns, target_vol=0.15, max_fraction=max_frac)
        assert 0.0 <= result <= max_frac, f"out of range: {result} with {n} returns"
        assert math.isfinite(result)


def test_fraction_scales_inversely_with_vol() -> None:
    # Doubling realized vol should roughly halve the fraction (before cap).
    # Use alternating ±vol returns for reproducible std.
    def _alt_returns(n: int, daily_vol: float) -> list[float]:
        rs = []
        for k in range(n):
            rs.append(daily_vol if k % 2 == 0 else -daily_vol)
        return rs

    # Low vol: daily 0.5 % → ~7.9 % pa.  fraction = 15 / 7.9 > 1 → capped.
    low = compute_position_fraction(_alt_returns(30, 0.005), 0.15, 1.0)
    # Medium vol: daily 2 % → ~31.7 % pa.  fraction = 15 / 31.7 ≈ 0.47.
    mid = compute_position_fraction(_alt_returns(30, 0.02), 0.15, 1.0)
    # High vol: daily 4 % → ~63.5 % pa.  fraction = 15 / 63.5 ≈ 0.24.
    high = compute_position_fraction(_alt_returns(30, 0.04), 0.15, 1.0)

    assert low > mid > high  # higher vol → smaller fraction
    assert low == pytest.approx(1.0)  # low vol capped at 1.0


def test_exact_target_vol_gives_fraction_one() -> None:
    # When realized vol ≈ target_vol exactly, fraction ≈ 1.0 (before cap).
    target = 0.20
    daily_vol = target / math.sqrt(252)
    rng = np.random.default_rng(7)
    returns = rng.normal(0.0, daily_vol, 5_000).tolist()
    result = compute_position_fraction(returns, target_vol=target, max_fraction=2.0)
    assert abs(result - 1.0) < 0.05  # within 5 % of 1.0 with 5 k draws
