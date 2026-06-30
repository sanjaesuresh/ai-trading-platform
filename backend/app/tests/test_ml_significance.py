"""Significance / overfitting statistics: pure-math unit tests (Phase 4 M3a).

Tests cover every exported function and the module constants. All functions are
pure (no I/O, no DB), so there is no setup/teardown and no fixtures needed.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.ml.significance import (
    DSR_PASS,
    MC_PASS_PERCENTILE,
    MIN_TRADES_FOR_VERDICT,
    PBO_MAX,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    pbo_cscv,
    probabilistic_sharpe_ratio,
    returns_moments,
    verdict,
)

# ---------------------------------------------------------------------------
# returns_moments
# ---------------------------------------------------------------------------


def test_returns_moments_normal_kurtosis_near_three() -> None:
    """For a large normal sample, sample kurtosis should be ≈ 3.0 (non-excess)."""
    rng = np.random.default_rng(0)
    arr = rng.normal(0, 1, 10_000)
    m = returns_moments(arr)
    assert m.n == 10_000
    assert abs(m.kurtosis - 3.0) < 0.25


def test_returns_moments_known_small_array() -> None:
    """Hand-verify mean, std, and sharpe on a tiny array."""
    arr = np.array([0.1, 0.2, 0.3, 0.4])
    m = returns_moments(arr)
    assert m.n == 4
    assert abs(m.mean - 0.25) < 1e-12
    expected_std = float(np.std(arr, ddof=1))
    assert abs(m.std - expected_std) < 1e-12
    assert abs(m.sharpe - m.mean / m.std) < 1e-12


def test_returns_moments_n_zero() -> None:
    """Empty array should return safe defaults (no exception)."""
    m = returns_moments(np.array([]))
    assert m.n == 0
    assert m.mean == 0.0
    assert m.std == 0.0
    assert m.sharpe == 0.0
    assert m.skew == 0.0
    assert m.kurtosis == 3.0


def test_returns_moments_n_one() -> None:
    """Single-element array: mean preserved, all dispersion stats are defaults."""
    m = returns_moments(np.array([0.07]))
    assert m.n == 1
    assert m.mean == pytest.approx(0.07)
    assert m.std == 0.0
    assert m.sharpe == 0.0
    assert m.kurtosis == 3.0


def test_returns_moments_zero_variance() -> None:
    """Constant array: sharpe and higher moments return safe neutral defaults."""
    m = returns_moments(np.array([1.0, 1.0, 1.0, 1.0]))
    assert m.std == 0.0
    assert m.sharpe == 0.0
    assert m.skew == 0.0
    assert m.kurtosis == 3.0


def test_returns_moments_frozen() -> None:
    """ReturnMoments is frozen; attribute mutation must raise."""
    m = returns_moments(np.array([0.1, 0.2]))
    with pytest.raises((AttributeError, TypeError)):
        m.n = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# probabilistic_sharpe_ratio
# ---------------------------------------------------------------------------


def test_psr_monotone_increasing_in_sharpe() -> None:
    """Higher sample Sharpe → higher probability of real edge, everything else equal.

    Use a modest n and moderate Sharpe range to stay well below the floating-point
    saturation region of the standard-normal CDF (which returns 1.0 for z ≳ 8).
    """
    sharpes = [-0.5, -0.2, 0.0, 0.2, 0.4]
    psrs = [
        probabilistic_sharpe_ratio(s, n=20, skew=0.0, kurtosis=3.0) for s in sharpes
    ]
    for a, b in zip(psrs, psrs[1:], strict=False):
        assert a < b


def test_psr_equals_half_when_sharpe_equals_benchmark() -> None:
    """When sample Sharpe equals benchmark, Φ(0) = 0.5 exactly."""
    psr = probabilistic_sharpe_ratio(0.0, n=100, skew=0.0, kurtosis=3.0, benchmark_sharpe=0.0)
    assert abs(psr - 0.5) < 1e-12

    # Works for non-zero benchmarks too.
    psr2 = probabilistic_sharpe_ratio(0.8, n=100, skew=0.0, kurtosis=3.0, benchmark_sharpe=0.8)
    assert abs(psr2 - 0.5) < 1e-12


def test_psr_approaches_one_with_large_n() -> None:
    """Longer track with positive Sharpe → PSR converges toward 1."""
    psr_small = probabilistic_sharpe_ratio(0.5, n=50, skew=0.0, kurtosis=3.0)
    psr_large = probabilistic_sharpe_ratio(0.5, n=2000, skew=0.0, kurtosis=3.0)
    assert psr_small < psr_large
    assert psr_large > 0.95


def test_psr_n_lt_2_returns_nan() -> None:
    """n < 2 means no degrees of freedom; PSR is undefined → nan."""
    assert math.isnan(probabilistic_sharpe_ratio(1.0, n=1, skew=0.0, kurtosis=3.0))
    assert math.isnan(probabilistic_sharpe_ratio(1.0, n=0, skew=0.0, kurtosis=3.0))


def test_psr_negative_denom_returns_nan() -> None:
    """Degenerate distribution that makes denominator non-positive → nan."""
    # kurtosis close to 0 with large sharpe can drive the quadratic negative.
    assert math.isnan(
        probabilistic_sharpe_ratio(5.0, n=100, skew=0.0, kurtosis=0.1)
    )


def test_psr_output_in_unit_interval() -> None:
    """For well-behaved inputs, PSR must lie in [0, 1].

    norm.cdf saturates to exactly 0.0 or 1.0 at extreme z-values; that is
    numerically correct floating-point behaviour, so we allow equality at the
    endpoints.
    """
    for sr in [-2.0, -1.0, 0.0, 1.0, 2.0]:
        psr = probabilistic_sharpe_ratio(sr, n=100, skew=0.0, kurtosis=3.0)
        if not math.isnan(psr):
            assert 0.0 <= psr <= 1.0


# ---------------------------------------------------------------------------
# expected_max_sharpe
# ---------------------------------------------------------------------------


def test_expected_max_sharpe_increases_with_n_trials() -> None:
    """Searching more configurations raises the false-discovery bar."""
    ems = [expected_max_sharpe(n, 1.0) for n in [2, 10, 100, 1000]]
    for a, b in zip(ems, ems[1:], strict=False):
        assert a < b


def test_expected_max_sharpe_increases_with_variance() -> None:
    """More dispersion in trial Sharpes → higher expected maximum."""
    ems_low = expected_max_sharpe(50, 0.5)
    ems_high = expected_max_sharpe(50, 2.0)
    assert ems_low < ems_high
    assert ems_high > 0.0


def test_expected_max_sharpe_guards() -> None:
    """N ≤ 1 or var ≤ 0 means no multiple-testing adjustment → 0."""
    assert expected_max_sharpe(1, 1.0) == 0.0
    assert expected_max_sharpe(0, 1.0) == 0.0
    assert expected_max_sharpe(-5, 1.0) == 0.0
    assert expected_max_sharpe(50, 0.0) == 0.0
    assert expected_max_sharpe(50, -1.0) == 0.0


# ---------------------------------------------------------------------------
# deflated_sharpe_ratio
# ---------------------------------------------------------------------------


def test_dsr_below_psr_zero_benchmark() -> None:
    """DSR must be lower than PSR(benchmark=0) when n_trials > 1 and var > 0.

    The expected-max benchmark is positive, which shifts PSR to a lower value.
    """
    rng = np.random.default_rng(1)
    arr = rng.normal(0.01, 0.1, 300)
    m = returns_moments(arr)
    psr_0 = probabilistic_sharpe_ratio(m.sharpe, m.n, m.skew, m.kurtosis, 0.0)
    dsr = deflated_sharpe_ratio(m.sharpe, m.n, m.skew, m.kurtosis, 50, 0.5)

    assert not math.isnan(dsr)
    assert not math.isnan(psr_0)
    assert dsr < psr_0


def test_dsr_equals_psr_when_one_trial() -> None:
    """With n_trials=1, expected_max_sharpe=0 so DSR collapses to PSR(benchmark=0)."""
    sr, n, skew, kurtosis = 0.5, 100, 0.0, 3.0
    psr = probabilistic_sharpe_ratio(sr, n, skew, kurtosis, 0.0)
    dsr = deflated_sharpe_ratio(sr, n, skew, kurtosis, 1, 1.0)
    assert abs(dsr - psr) < 1e-12


# ---------------------------------------------------------------------------
# pbo_cscv
# ---------------------------------------------------------------------------


def test_pbo_dominant_column_gives_low_pbo() -> None:
    """When one configuration dominates in every sub-period, IS winner = OS winner → PBO ≈ 0."""
    rng = np.random.default_rng(0)
    T, N = 64, 10
    mat = rng.normal(0, 0.1, (T, N))
    mat[:, 0] += 5.0  # column 0 vastly outperforms in every period
    result = pbo_cscv(mat, n_splits=4)
    assert not math.isnan(result.pbo)
    assert result.pbo < 0.3
    assert result.n_combinations == 6  # C(4, 2) = 6


def test_pbo_pure_noise_near_half() -> None:
    """IID noise gives no genuine edge: IS selection is coin-flip → PBO near 0.5."""
    rng = np.random.default_rng(42)
    T, N = 160, 50  # many configs so the expected-rank argument holds
    mat = rng.normal(0, 1, (T, N))
    result = pbo_cscv(mat, n_splits=8)
    assert not math.isnan(result.pbo)
    # Wide tolerance: with C(8,4)=70 combinations, variance is non-negligible.
    assert 0.2 <= result.pbo <= 0.8


def test_pbo_output_in_unit_interval() -> None:
    """PBO is a probability and must lie in [0, 1]."""
    rng = np.random.default_rng(7)
    mat = rng.normal(0, 1, (32, 5))
    result = pbo_cscv(mat, n_splits=4)
    assert not math.isnan(result.pbo)
    assert 0.0 <= result.pbo <= 1.0


def test_pbo_guard_single_config() -> None:
    """N < 2 configurations: PBO is undefined → nan."""
    mat = np.random.default_rng(0).normal(0, 1, (32, 1))
    result = pbo_cscv(mat, n_splits=4)
    assert math.isnan(result.pbo)
    assert result.n_combinations == 0


def test_pbo_guard_too_few_rows() -> None:
    """Fewer rows than n_splits: cannot form S submatrices → nan."""
    mat = np.random.default_rng(0).normal(0, 1, (3, 5))
    result = pbo_cscv(mat, n_splits=4)
    assert math.isnan(result.pbo)


def test_pbo_n_combinations_matches_formula() -> None:
    """n_combinations must equal C(S, S/2) for even n_splits."""
    rng = np.random.default_rng(99)
    mat = rng.normal(0, 1, (32, 4))
    result = pbo_cscv(mat, n_splits=4)
    assert result.n_combinations == 6   # C(4, 2) = 6
    assert result.n_splits == 4


def test_pbo_odd_n_splits_floored_to_even() -> None:
    """Odd n_splits is silently floored to the nearest even value."""
    rng = np.random.default_rng(5)
    mat = rng.normal(0, 1, (32, 4))
    result_odd = pbo_cscv(mat, n_splits=5)   # floored to 4
    result_even = pbo_cscv(mat, n_splits=4)
    # Both should produce identical results (same S=4 used internally).
    assert result_odd.n_combinations == result_even.n_combinations
    assert result_odd.pbo == pytest.approx(result_even.pbo)


def test_pbo_result_frozen() -> None:
    """PBOResult is frozen; mutation must raise."""
    rng = np.random.default_rng(0)
    mat = rng.normal(0, 1, (16, 3))
    result = pbo_cscv(mat, n_splits=4)
    with pytest.raises((AttributeError, TypeError)):
        result.pbo = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------

_PASS_KWARGS = {
    "beats_buy_and_hold": True,
    "beats_rule": True,
    "beats_logistic": True,
    "mc_percentile": 0.97,
    "deflated_sharpe": 0.97,
    "pbo": 0.2,
    "n_oos_trades": 50,
}


def test_verdict_pass_when_all_conditions_met() -> None:
    """All six conditions pass → verdict is 'pass'."""
    v = verdict(**_PASS_KWARGS)  # type: ignore[arg-type]
    assert v.verdict == "pass"
    assert isinstance(v.reasons, list)
    assert len(v.reasons) == 6  # one per condition


def test_verdict_inconclusive_too_few_trades() -> None:
    """n_oos_trades below floor → inconclusive, regardless of other metrics."""
    v = verdict(**{**_PASS_KWARGS, "n_oos_trades": MIN_TRADES_FOR_VERDICT - 1})  # type: ignore[arg-type]
    assert v.verdict == "inconclusive"
    assert any("n_oos_trades" in r for r in v.reasons)


def test_verdict_inconclusive_exactly_at_trade_floor() -> None:
    """n_oos_trades == MIN_TRADES_FOR_VERDICT is not below the floor → not inconclusive for that reason."""
    v = verdict(**{**_PASS_KWARGS, "n_oos_trades": MIN_TRADES_FOR_VERDICT})  # type: ignore[arg-type]
    assert v.verdict == "pass"  # still passes (all other conditions met)


def test_verdict_fail_when_conditions_not_met() -> None:
    """At least one condition failing → verdict is 'fail'."""
    v = verdict(
        beats_buy_and_hold=False,
        beats_rule=False,
        beats_logistic=False,
        mc_percentile=0.3,
        deflated_sharpe=0.4,
        pbo=0.8,
        n_oos_trades=50,
    )
    assert v.verdict == "fail"
    # Reasons should record each FAIL.
    fail_reasons = [r for r in v.reasons if "FAIL" in r]
    assert len(fail_reasons) >= 3


def test_verdict_nan_dsr_inconclusive() -> None:
    """nan DSR means the statistical test could not run → inconclusive."""
    v = verdict(**{**_PASS_KWARGS, "deflated_sharpe": float("nan")})  # type: ignore[arg-type]
    assert v.verdict == "inconclusive"
    assert any("nan" in r for r in v.reasons)


def test_verdict_single_failing_condition_gives_fail() -> None:
    """A single condition below threshold flips the verdict from pass to fail."""
    v = verdict(**{**_PASS_KWARGS, "pbo": PBO_MAX + 0.01})  # type: ignore[arg-type]
    assert v.verdict == "fail"


def test_verdict_model_verdict_frozen() -> None:
    """ModelVerdict is frozen."""
    v = verdict(**_PASS_KWARGS)  # type: ignore[arg-type]
    with pytest.raises((AttributeError, TypeError)):
        v.verdict = "inconclusive"  # type: ignore[misc]


def test_verdict_constants_match_thresholds() -> None:
    """Module constants must align with the verdict logic (regression guard)."""
    assert MIN_TRADES_FOR_VERDICT == 10
    assert MC_PASS_PERCENTILE == 0.95
    assert DSR_PASS == 0.95
    assert PBO_MAX == 0.5
