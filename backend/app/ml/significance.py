"""Overfitting-detection and significance statistics for the ML strategy (Phase 4 M3a).

This module answers the question every trading researcher must ask before trusting
an ML model: "Is this out-of-sample result real edge, or noise that vanishes in
live trading?"

Four independent statistical lenses, all pure math — no I/O, no global state,
no DB:

- **Probabilistic Sharpe Ratio (PSR)** (Bailey & López de Prado, 2012).
  Adjusts the Sharpe ratio for realistic return distributions (non-zero skew,
  non-Gaussian kurtosis) and finite track length to estimate the probability
  that the true underlying Sharpe exceeds a benchmark. Beats the raw Sharpe
  because the raw Sharpe treats all return distributions as Gaussian and ignores
  finite-sample luck.

- **Deflated Sharpe Ratio (DSR)** (Bailey & López de Prado, 2014).
  PSR with the benchmark raised to the *expected maximum* Sharpe across the number
  of strategy configurations tested. This is the multiple-testing correction: the
  more configurations a researcher tries, the higher the false-discovery bar needed
  to demonstrate real edge rather than lucky selection.

- **Probability of Backtest Overfitting (PBO)** via CSCV (Bailey, Borwein,
  López de Prado, Zhu, 2015). A combinatorial cross-validation over N strategy
  configurations. PBO estimates the fraction of hold-out evaluations where the
  in-sample winner falls in the bottom half out-of-sample. PBO near 0.5 means the
  backtest selection is no better than a coin flip; PBO near 0.0 means genuine edge
  that generalises to unseen data.

- **Verdict**. A final gate that maps all evidence to "pass"/"fail"/"inconclusive"
  using named module constants so downstream code references thresholds, not magic
  numbers.

All functions are pure and independently testable; none touches the database or
any I/O.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np
from scipy import stats

# ---------------------------------------------------------------------------
# Thresholds — exported so M3b and tests reference these, not magic numbers.
# ---------------------------------------------------------------------------

MIN_TRADES_FOR_VERDICT: int = 10   # minimum OOS trades for a meaningful verdict
MC_PASS_PERCENTILE: float = 0.95   # model must beat ≥ 95 % of a random ensemble
DSR_PASS: float = 0.95             # deflated Sharpe probability threshold
PBO_MAX: float = 0.5               # maximum tolerated probability of overfitting

# Euler–Mascheroni constant (used in the expected-max-Sharpe formula).
_GAMMA_EM: float = 0.5772156649


# ---------------------------------------------------------------------------
# Frozen return types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReturnMoments:
    """Descriptive moments of a per-period return series.

    All statistics derived from the sample only; no annualisation. The ``sharpe``
    field is the raw per-period mean/std ratio — the input PSR and DSR need. The
    ``kurtosis`` is non-excess (3.0 for a Gaussian), matching the convention the
    PSR formula uses so callers never need to convert.
    """

    n: int
    mean: float
    std: float
    sharpe: float
    skew: float
    kurtosis: float  # non-excess: 3.0 for a normal distribution


@dataclass(frozen=True)
class PBOResult:
    """Outcome of the CSCV probability-of-backtest-overfitting test."""

    pbo: float          # in [0, 1], or nan when guards triggered
    n_combinations: int
    n_splits: int


@dataclass(frozen=True)
class PairedIncrementalResult:
    """The paired (news − price) incremental significance test (Phase 5 §6).

    "Incremental" needs an incremental test, not a boolean ``>``: the news arm's
    absolute return stream is mostly the price signal, so if price clears the bar
    the news arm clears it too and a one-basis-point edge reads as significant. So
    the increment is tested on its own — a paired test on the per-bar (news − price)
    difference stream, deflated for the news search count, plus an explicit
    ``beats_price_only`` condition. A point estimate of the difference is not
    evidence the difference is non-zero.
    """

    mean_diff: float
    bootstrap_p_value: float  # one-sided H0: mean(news − price) <= 0
    deflated_sharpe: float  # DSR of the differenced stream, deflated for n_trials
    n_obs: int
    n_trials: int
    beats_price_only: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "mean_diff": float(self.mean_diff),
            "bootstrap_p_value": float(self.bootstrap_p_value),
            "deflated_sharpe": float(self.deflated_sharpe),
            "n_obs": int(self.n_obs),
            "n_trials": int(self.n_trials),
            "beats_price_only": bool(self.beats_price_only),
        }


def _stationary_bootstrap_mean(
    diff: np.ndarray, *, n_resamples: int, avg_block: float, seed: int
) -> np.ndarray:
    """Stationary-bootstrap (Politis-Romano) distribution of the mean of *diff*.

    Resamples in geometric-length blocks (mean ``avg_block``) so the autocorrelation
    in a per-bar return-difference series is preserved — an iid bootstrap would
    understate the variance of the mean and overstate significance.
    """
    n = diff.size
    rng = np.random.default_rng(seed)
    p = 1.0 / max(1.0, avg_block)
    means = np.empty(n_resamples, dtype="float64")
    for r in range(n_resamples):
        idx = np.empty(n, dtype=np.int64)
        i = int(rng.integers(0, n))
        for t in range(n):
            idx[t] = i
            i = int(rng.integers(0, n)) if rng.random() < p else (i + 1) % n
        means[r] = float(diff[idx].mean())
    return means


def paired_incremental_significance(
    diff_returns: np.ndarray,
    *,
    n_trials: int,
    n_resamples: int = 2000,
    avg_block: float = 5.0,
    seed: int = 0,
) -> PairedIncrementalResult:
    """Paired test on a per-bar (news − price) return-difference stream (§6).

    Combines a stationary-bootstrap one-sided p-value (H0: the mean difference is
    ≤ 0) with a deflated Sharpe of the differenced stream, deflated for the news
    search count ``n_trials``. ``beats_price_only`` requires both a positive mean
    difference and a deflated Sharpe clearing ``DSR_PASS`` — the bootstrap p-value
    is reported as a cross-check, not a second gate.
    """
    diff = np.asarray(diff_returns, dtype="float64")
    n = int(diff.size)
    if n < 2:
        return PairedIncrementalResult(
            mean_diff=float(diff.mean()) if n else 0.0,
            bootstrap_p_value=float("nan"),
            deflated_sharpe=float("nan"),
            n_obs=n,
            n_trials=n_trials,
            beats_price_only=False,
        )

    mean_diff = float(diff.mean())
    boot_means = _stationary_bootstrap_mean(
        diff, n_resamples=n_resamples, avg_block=avg_block, seed=seed
    )
    # One-sided: probability the true mean difference is not above zero.
    p_value = float(np.mean(boot_means <= 0.0))

    moments = returns_moments(diff)
    # Lo (2002) sampling-variance floor for the trial-Sharpe variance, matching the
    # evaluation's deflated-Sharpe treatment.
    var_trial = (1.0 + 0.5 * moments.sharpe**2) / max(1, n)
    dsr = deflated_sharpe_ratio(
        moments.sharpe,
        n,
        moments.skew,
        moments.kurtosis,
        n_trials=n_trials,
        variance_of_trial_sharpes=var_trial,
    )
    beats = bool(mean_diff > 0.0 and not math.isnan(dsr) and dsr >= DSR_PASS)
    return PairedIncrementalResult(
        mean_diff=mean_diff,
        bootstrap_p_value=p_value,
        deflated_sharpe=dsr,
        n_obs=n,
        n_trials=n_trials,
        beats_price_only=beats,
    )


@dataclass(frozen=True)
class ModelVerdict:
    """Binary gate: did the model clear the full significance battery?

    ``verdict`` is one of "pass", "fail", or "inconclusive".
    ``reasons`` records which conditions passed and which failed, in the order they
    were evaluated, so a downstream display can surface a concise explanation.
    """

    verdict: str
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


def returns_moments(returns: np.ndarray) -> ReturnMoments:
    """Compute descriptive moments of a 1-D per-period return array.

    Uses sample statistics throughout (ddof=1 for std, bias=False for skew and
    kurtosis) so all estimates are unbiased for a finite track. The kurtosis
    returned is non-excess (Gaussian = 3.0).

    Guards:
    - n < 2: returns sharpe=0.0, skew=0.0, kurtosis=3.0 (the safe neutral-
      distribution defaults). Mean is arr[0] if n==1, otherwise 0.0.
    - std == 0 (all identical returns): returns sharpe=0.0, skew=0.0, kurtosis=3.0.
      Computing skew/kurtosis on a zero-variance sample is numerically undefined;
      the neutral Gaussian defaults prevent NaN from propagating.
    """
    arr = np.asarray(returns, dtype=float)
    n = int(arr.size)

    if n < 2:
        mean_val = float(arr[0]) if n >= 1 else 0.0
        return ReturnMoments(
            n=n, mean=mean_val, std=0.0, sharpe=0.0, skew=0.0, kurtosis=3.0
        )

    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))

    if std == 0.0:
        return ReturnMoments(
            n=n, mean=mean, std=0.0, sharpe=0.0, skew=0.0, kurtosis=3.0
        )

    sharpe = mean / std
    skew = float(stats.skew(arr, bias=False))
    kurtosis = float(stats.kurtosis(arr, fisher=False, bias=False))

    return ReturnMoments(
        n=n, mean=mean, std=std, sharpe=sharpe, skew=skew, kurtosis=kurtosis
    )


def probabilistic_sharpe_ratio(
    sharpe: float,
    n: int,
    skew: float,
    kurtosis: float,
    benchmark_sharpe: float = 0.0,
) -> float:
    """Probability (0–1) that the true Sharpe exceeds ``benchmark_sharpe``.

    Bailey & López de Prado (2012). The observed (sample) Sharpe is biased
    upward whenever the return distribution has fat tails or positive skew, or the
    track is short — all common in trading. PSR corrects for this by incorporating
    the distribution's shape (via skew and non-excess kurtosis) and the track length
    ``n`` (number of per-period observations). A higher PSR is stronger evidence of
    real edge.

    All Sharpes and ``benchmark_sharpe`` must be on the same per-period basis —
    do not mix daily and annualised figures.

    Formula (non-excess kurtosis, i.e. kurtosis=3 for Gaussian):

        PSR = Φ( (sharpe − benchmark) × √(n−1)
                 / √(1 − skew·sharpe + ((kurtosis−1)/4)·sharpe²) )

    Returns nan when:
    - n < 2: no degrees of freedom for the uncertainty estimate.
    - denominator ≤ 0: degenerate distribution that the formula cannot handle
      (e.g. very high skew with large negative kurtosis).
    """
    if n < 2:
        return float("nan")

    denom_sq = 1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe**2
    if denom_sq <= 0.0:
        return float("nan")

    z = (sharpe - benchmark_sharpe) * math.sqrt(n - 1) / math.sqrt(denom_sq)
    return float(stats.norm.cdf(z))


def expected_max_sharpe(n_trials: int, variance_of_trial_sharpes: float) -> float:
    """Expected maximum Sharpe across ``n_trials`` independent configurations.

    López de Prado (2018). When a researcher evaluates N configurations and
    selects the highest in-sample Sharpe, the expected maximum rises purely by
    selection even when every configuration has zero true edge. This is the
    false-discovery bar the DSR must clear.

    The formula is the expected maximum of N iid N(0, σ²) draws using the
    Euler–Mascheroni (EM) approximation to extreme-value theory:

        E[max] = √var × ( (1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e)) )

    where γ = 0.5772156649 (EM constant), e = Euler's number, N = n_trials.

    Guards:
    - N ≤ 1: no selection pressure; returns 0.0 so DSR degenerates to PSR(0).
    - var ≤ 0: no dispersion across configurations; returns 0.0.
    """
    if n_trials <= 1 or variance_of_trial_sharpes <= 0.0:
        return 0.0

    N = n_trials
    std = math.sqrt(variance_of_trial_sharpes)
    z1 = float(stats.norm.ppf(1.0 - 1.0 / N))
    z2 = float(stats.norm.ppf(1.0 - 1.0 / (N * math.e)))
    return std * ((1.0 - _GAMMA_EM) * z1 + _GAMMA_EM * z2)


def deflated_sharpe_ratio(
    sharpe: float,
    n: int,
    skew: float,
    kurtosis: float,
    n_trials: int,
    variance_of_trial_sharpes: float,
) -> float:
    """PSR with the benchmark raised to the multiple-testing false-discovery bar.

    DSR = PSR(benchmark = expected_max_sharpe(n_trials, variance)).

    PSR against benchmark=0 only tests whether the strategy beat a random coin
    flip. DSR adjusts for the number of configurations tried: if 100 configs were
    evaluated and the best was selected, the benchmark rises to the expected maximum
    Sharpe by chance alone. A DSR near 1 means real edge even after correcting for
    the full search breadth.
    """
    benchmark = expected_max_sharpe(n_trials, variance_of_trial_sharpes)
    return probabilistic_sharpe_ratio(sharpe, n, skew, kurtosis, benchmark)


def pbo_cscv(performance_matrix: np.ndarray, n_splits: int = 16) -> PBOResult:
    """Probability of Backtest Overfitting via Combinatorially Symmetric Cross-Validation.

    Bailey, Borwein, López de Prado, Zhu (2015). Measures how often the
    configuration selected by in-sample optimisation falls in the bottom half of
    out-of-sample performance across all possible symmetric splits of the data.
    PBO near 0.0 means a genuine edge that generalises; near 0.5 means the in-sample
    winner is chosen by luck.

    Args:
        performance_matrix: shape (T_observations, N_configurations). Each column is
            one configuration's per-observation performance (e.g. per-period returns).
        n_splits: number of submatrices S. Must be even (floored to the nearest even
            number if odd). Larger S increases the number of combinations C(S, S/2)
            and the statistical resolution at the cost of computation time.

    Algorithm:
        1. Trim T rows to be divisible by S; drop the small remainder.
        2. Split into S equal-length submatrices.
        3. For each of the C(S, S/2) ways to assign S/2 submatrices to in-sample:
           a. Find the configuration n* with the best mean in-sample performance.
           b. Rank n*'s mean out-of-sample performance among all N configurations.
           c. w = rank / N (w=1 means n* is the OS winner, w=1/N the worst).
           d. λ = logit(w) = ln(w / (1−w)).
        4. PBO = fraction of combinations where λ ≤ 0 (n* in the bottom half OS).

    Guards: N < 2 configurations, S < 2, or T < S → pbo=nan (not enough data).
    """
    mat = np.asarray(performance_matrix, dtype=float)
    if mat.ndim != 2:
        raise ValueError("performance_matrix must be 2-D.")
    T, N = mat.shape

    # Enforce even S for symmetric IS/OS pairing.
    S = n_splits
    if S % 2 != 0:
        S -= 1

    if N < 2 or S < 2 or T < S:
        return PBOResult(pbo=float("nan"), n_combinations=0, n_splits=n_splits)

    # Trim to the largest multiple of S.
    T_use = (T // S) * S
    mat = mat[:T_use, :]
    sub_size = T_use // S

    # Pre-compute each submatrix's per-configuration mean (shape: S × N).
    # Doing this once outside the combination loop avoids redundant slicing.
    sub_means = np.empty((S, N), dtype=float)
    for s in range(S):
        sub_means[s] = mat[s * sub_size : (s + 1) * sub_size].mean(axis=0)

    half = S // 2
    all_idx = list(range(S))
    combos = list(itertools.combinations(all_idx, half))
    n_combos = len(combos)

    # w must stay away from 0 and 1 so logit doesn't diverge.
    _eps = 1e-10
    n_overfit = 0

    for is_idx in combos:
        os_idx = [i for i in all_idx if i not in set(is_idx)]

        is_mean = sub_means[list(is_idx)].mean(axis=0)   # shape (N,)
        n_star = int(np.argmax(is_mean))

        os_mean = sub_means[os_idx].mean(axis=0)          # shape (N,)

        # rankdata returns 1 for the smallest value, N for the largest.
        # w = 1 means n* is the best OS performer (not overfitting).
        rank = float(stats.rankdata(os_mean)[n_star])
        w = rank / N
        w = max(_eps, min(1.0 - _eps, w))
        lam = math.log(w / (1.0 - w))

        if lam <= 0.0:
            n_overfit += 1

    pbo = n_overfit / n_combos
    return PBOResult(pbo=pbo, n_combinations=n_combos, n_splits=n_splits)


def verdict(
    *,
    beats_buy_and_hold: bool,
    beats_rule: bool,
    beats_logistic: bool,
    mc_percentile: float,
    deflated_sharpe: float,
    pbo: float,
    n_oos_trades: int,
) -> ModelVerdict:
    """Map the evidence battery to "pass", "fail", or "inconclusive".

    All thresholds are exposed as module-level constants so callers reference names,
    not magic numbers:
        MIN_TRADES_FOR_VERDICT = 10
        MC_PASS_PERCENTILE    = 0.95
        DSR_PASS              = 0.95
        PBO_MAX               = 0.50

    Rules (evaluated in order):

    1. "inconclusive" if n_oos_trades < MIN_TRADES_FOR_VERDICT or deflated_sharpe
       is nan. Too few trades means the statistics are untrustworthy; a nan DSR
       means the distribution was degenerate and the test could not run.

    2. "pass" only when ALL six conditions hold:
         beats_buy_and_hold  (beats the simple long-only baseline)
         beats_rule          (beats the rule-based trend-following strategy)
         beats_logistic      (beats the logistic-regression baseline)
         mc_percentile ≥ MC_PASS_PERCENTILE   (beats ≥ 95 % of random ensemble)
         deflated_sharpe ≥ DSR_PASS           (≥ 95 % probability of real edge)
         pbo ≤ PBO_MAX                        (≤ 50 % probability of overfitting)

    3. "fail" otherwise.

    ``reasons`` lists each condition's outcome so a UI can show a short explanation.
    """
    reasons: list[str] = []

    # --- inconclusive guard ---
    if n_oos_trades < MIN_TRADES_FOR_VERDICT:
        reasons.append(
            f"n_oos_trades={n_oos_trades} < {MIN_TRADES_FOR_VERDICT} (floor): "
            "inconclusive"
        )
        return ModelVerdict(verdict="inconclusive", reasons=reasons)

    if math.isnan(deflated_sharpe):
        reasons.append("deflated_sharpe is nan (degenerate track): inconclusive")
        return ModelVerdict(verdict="inconclusive", reasons=reasons)

    # nan pbo means CSCV could not run (too few observations / configurations) —
    # that is missing evidence, not a failure, so report "inconclusive".
    if math.isnan(pbo):
        reasons.append("pbo is nan (CSCV could not run — too few splits/configs): inconclusive")
        return ModelVerdict(verdict="inconclusive", reasons=reasons)

    # nan mc_percentile means no MC ensemble runs completed — same reasoning.
    if math.isnan(mc_percentile):
        reasons.append("mc_percentile is nan (no MC ensemble runs): inconclusive")
        return ModelVerdict(verdict="inconclusive", reasons=reasons)

    # --- evaluate every pass condition ---
    all_pass = True

    def _check(condition: bool, label: str) -> None:
        nonlocal all_pass
        status = "PASS" if condition else "FAIL"
        reasons.append(f"{label}: {status}")
        if not condition:
            all_pass = False

    _check(beats_buy_and_hold, "beats_buy_and_hold")
    _check(beats_rule, "beats_rule")
    _check(beats_logistic, "beats_logistic")
    _check(
        mc_percentile >= MC_PASS_PERCENTILE,
        f"mc_percentile={mc_percentile:.3f} >= {MC_PASS_PERCENTILE}",
    )
    _check(
        deflated_sharpe >= DSR_PASS,
        f"deflated_sharpe={deflated_sharpe:.3f} >= {DSR_PASS}",
    )
    _check(
        pbo <= PBO_MAX,
        f"pbo={pbo:.3f} <= {PBO_MAX}",
    )

    return ModelVerdict(verdict="pass" if all_pass else "fail", reasons=reasons)
