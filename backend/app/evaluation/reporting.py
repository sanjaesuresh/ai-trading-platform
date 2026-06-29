"""Result dataclasses and honest distribution aggregation (pure logic).

This is where a sweep or walk-forward run is turned into evidence. The framing
rules are deliberate:

- **Selection never reads out-of-sample data.** ``select_best`` ranks on the
  *in-sample* objective only (tie-broken by in-sample total return). The runner
  uses it to choose a parameter set per split before any test-segment metric is
  computed — the structural guarantee that selection cannot peek ahead.
- **The full distribution is reported, not the best cell.** ``summarize`` gives
  best / median / worst of the out-of-sample objective across combinations, the
  fraction that beat the rule-based baseline, the in-sample-vs-out-of-sample gap
  of the chosen combination, and an overfit flag — so a sweep cannot quietly
  present its luckiest result as if it were typical.

The aggregation reads the existing ``Metrics`` records; it does not recompute any
metric. Win rate / profit factor stay over round trips via ``compute_metrics``.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.backtesting.metrics import Metrics

# Overfit threshold: the best in-sample combination is flagged as overfit when
# its out-of-sample objective falls below half of its in-sample objective (only
# meaningful when the in-sample objective is positive — a strategy that wasn't
# good in-sample has nothing to overfit). Documented and tunable in one place.
_OVERFIT_RETENTION = 0.5


@dataclass
class CombinationResult:
    """One parameter combination's in- and (optional) out-of-sample metrics."""

    params: dict[str, Any]
    in_sample: Metrics
    out_sample: Metrics | None
    num_trades_in: int
    num_trades_out: int


@dataclass
class DistributionSummary:
    """Honest summary of a sweep / walk-forward distribution.

    All of ``best``/``median``/``worst`` are over the out-of-sample objective
    (falling back to in-sample when a result has no out-of-sample segment, e.g. a
    pure sweep with no split).
    """

    objective: str
    best: float
    median: float
    worst: float
    best_params: dict[str, Any]
    pct_beating_baseline: float
    in_sample_vs_out_sample_gap: float
    overfit_flag: bool


@dataclass
class SplitResult:
    """The chosen combination's result on one walk-forward split, plus baseline."""

    train_start: int
    train_end: int
    test_start: int
    test_end: int
    chosen_params: dict[str, Any]
    in_sample: Metrics
    out_sample: Metrics
    num_trades_in: int
    num_trades_out: int
    baseline_out_sample: Metrics


@dataclass
class WalkForwardResult:
    """The full walk-forward outcome: per-split detail plus the summary."""

    objective: str
    splits: list[SplitResult] = field(default_factory=list)
    summary: DistributionSummary | None = None


def _objective_value(metrics: Metrics, objective: str) -> float:
    return float(getattr(metrics, objective))


def _out_or_in(result: CombinationResult, objective: str) -> float:
    """Out-of-sample objective, falling back to in-sample when there is no split."""
    metrics = result.out_sample if result.out_sample is not None else result.in_sample
    return _objective_value(metrics, objective)


def select_best(
    results: list[CombinationResult], *, objective: str
) -> CombinationResult:
    """Return the result with the highest *in-sample* objective.

    Ties are broken by in-sample ``total_return_pct``. Selection deliberately
    ignores out-of-sample metrics so it can never peek ahead. Raises
    ``ValueError`` on an empty list (the caller must guard empty splits).
    """
    if not results:
        raise ValueError("select_best requires at least one result.")
    return max(
        results,
        key=lambda r: (
            _objective_value(r.in_sample, objective),
            r.in_sample.total_return_pct,
        ),
    )


def summarize(
    results: list[CombinationResult],
    *,
    objective: str,
    baseline_out_sample: Metrics | None,
) -> DistributionSummary:
    """Aggregate combination results into an honest distribution summary.

    Empty input returns a zeroed summary. ``pct_beating_baseline`` is 0.0 when no
    baseline is supplied. The overfit flag and the gap describe the combination
    that *would be selected* (highest in-sample objective), not the luckiest one.
    """
    if not results:
        return DistributionSummary(
            objective=objective,
            best=0.0,
            median=0.0,
            worst=0.0,
            best_params={},
            pct_beating_baseline=0.0,
            in_sample_vs_out_sample_gap=0.0,
            overfit_flag=False,
        )

    out_values = np.array([_out_or_in(r, objective) for r in results], dtype=float)
    best_idx = int(np.argmax(out_values))

    if baseline_out_sample is not None:
        baseline_value = _objective_value(baseline_out_sample, objective)
        pct_beating_baseline = float(np.mean(out_values > baseline_value))
    else:
        pct_beating_baseline = 0.0

    # The gap and overfit flag are about the in-sample-selected combination.
    selected = select_best(results, objective=objective)
    selected_in = _objective_value(selected.in_sample, objective)
    selected_out = (
        _objective_value(selected.out_sample, objective)
        if selected.out_sample is not None
        else selected_in
    )
    gap = selected_in - selected_out
    overfit_flag = selected_in > 0.0 and selected_out < _OVERFIT_RETENTION * selected_in

    return DistributionSummary(
        objective=objective,
        best=float(out_values.max()),
        median=float(np.median(out_values)),
        worst=float(out_values.min()),
        best_params=results[best_idx].params,
        pct_beating_baseline=pct_beating_baseline,
        in_sample_vs_out_sample_gap=gap,
        overfit_flag=overfit_flag,
    )


def replace_pct_beating_baseline(
    summary: DistributionSummary, pct: float
) -> DistributionSummary:
    """Return a copy of *summary* with ``pct_beating_baseline`` set to *pct*.

    Walk-forward compares each split's chosen combination against *that split's*
    own baseline, which the single-baseline ``summarize`` can't express, so the
    runner computes the fraction over splits and replaces it here.
    """
    return dataclasses.replace(summary, pct_beating_baseline=pct)
