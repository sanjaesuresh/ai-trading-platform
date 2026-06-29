"""Sweep and walk-forward runners — thin drivers over the existing engine.

These reuse ``run_backtest`` and ``compute_metrics`` unchanged; no trade loop or
metric math lives here. Each split slice is its own backtest (enters flat,
force-closes flat on its last bar), exactly the engine's existing behaviour.

No-leakage guarantee: indicators are computed once over the full series upstream;
this driver only *slices by row index*. An indicator at bar *i* depends only on
bars ≤ *i*, so a later test slice can't influence an earlier train slice, and the
walk-forward selection (``select_best``) ranks on in-sample metrics only.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.backtesting.engine import run_backtest
from app.backtesting.metrics import Metrics, compute_metrics
from app.evaluation.grid import expand_param_grid
from app.evaluation.reporting import (
    CombinationResult,
    DistributionSummary,
    SplitResult,
    WalkForwardResult,
    replace_pct_beating_baseline,
    select_best,
    summarize,
)
from app.evaluation.walk_forward import WalkForwardSplit
from app.strategies.registry import resolve_strategy

_DEFAULT_CAPITAL = 100_000.0


def _score(
    frame: pd.DataFrame,
    *,
    symbol: str,
    strategy_name: str,
    params: dict[str, Any],
    run_kwargs: dict[str, Any],
) -> Metrics:
    """Run one strategy/param set over *frame* and return its metrics.

    Resolves (and so validates) the strategy through the registry, runs the
    engine with the caller's engine knobs, and computes metrics against the same
    initial capital the engine used.
    """
    strategy = resolve_strategy(strategy_name, params)
    result = run_backtest(frame, strategy, symbol=symbol, **run_kwargs)
    initial_capital = run_kwargs.get("initial_capital", _DEFAULT_CAPITAL)
    return compute_metrics(result.equity_curve, result.trades, initial_capital)


def run_sweep(
    featured_frame: pd.DataFrame,
    *,
    symbol: str,
    strategy_name: str,
    param_grid: dict[str, list],
    run_kwargs: dict[str, Any],
    objective: str = "sharpe_ratio",
) -> tuple[list[CombinationResult], DistributionSummary]:
    """Run every expanded combination once over the whole frame, then summarise.

    No split: each result's ``out_sample`` is ``None`` and the summary's
    best/median/worst fall back to the in-sample objective.
    """
    combos = expand_param_grid(strategy_name, param_grid)
    results: list[CombinationResult] = []
    for combo in combos:
        metrics = _score(
            featured_frame,
            symbol=symbol,
            strategy_name=strategy_name,
            params=combo,
            run_kwargs=run_kwargs,
        )
        results.append(
            CombinationResult(
                params=combo,
                in_sample=metrics,
                out_sample=None,
                num_trades_in=metrics.num_round_trips,
                num_trades_out=0,
            )
        )
    summary = summarize(results, objective=objective, baseline_out_sample=None)
    return results, summary


def run_walk_forward(
    featured_frame: pd.DataFrame,
    *,
    symbol: str,
    strategy_name: str,
    param_grid: dict[str, list],
    splits: list[WalkForwardSplit],
    run_kwargs: dict[str, Any],
    objective: str = "sharpe_ratio",
    baseline_strategy_name: str = "trend_following",
    baseline_params: dict[str, Any] | None = None,
) -> WalkForwardResult:
    """Per split: select parameters in-sample, then score them out-of-sample.

    For each split:
      1. Run every combination over the *train* slice and score in-sample.
      2. ``select_best`` by in-sample objective — selection never reads the test
         slice.
      3. Run the chosen combination and the rule-based baseline over the *test*
         slice and score out-of-sample.

    The returned summary reports best/median/worst of the chosen combinations'
    out-of-sample objective across splits, plus the fraction of splits whose
    chosen combination beat *that split's own* baseline.
    """
    combos = expand_param_grid(strategy_name, param_grid)
    baseline_params = baseline_params or {}

    split_results: list[SplitResult] = []
    per_split_combo: list[CombinationResult] = []
    beats = 0
    for split in splits:
        train = featured_frame.iloc[split.train_start : split.train_end].reset_index(
            drop=True
        )
        test = featured_frame.iloc[split.test_start : split.test_end].reset_index(
            drop=True
        )

        # 1-2. Select on in-sample only.
        train_results = [
            _build_train_result(
                combo,
                _score(
                    train,
                    symbol=symbol,
                    strategy_name=strategy_name,
                    params=combo,
                    run_kwargs=run_kwargs,
                ),
            )
            for combo in combos
        ]
        chosen = select_best(train_results, objective=objective)

        # 3. Score the chosen combo and the baseline out-of-sample.
        out_metrics = _score(
            test,
            symbol=symbol,
            strategy_name=strategy_name,
            params=chosen.params,
            run_kwargs=run_kwargs,
        )
        baseline_out = _score(
            test,
            symbol=symbol,
            strategy_name=baseline_strategy_name,
            params=baseline_params,
            run_kwargs=run_kwargs,
        )

        split_results.append(
            SplitResult(
                train_start=split.train_start,
                train_end=split.train_end,
                test_start=split.test_start,
                test_end=split.test_end,
                chosen_params=chosen.params,
                in_sample=chosen.in_sample,
                out_sample=out_metrics,
                num_trades_in=chosen.in_sample.num_round_trips,
                num_trades_out=out_metrics.num_round_trips,
                baseline_out_sample=baseline_out,
            )
        )
        per_split_combo.append(
            CombinationResult(
                params=chosen.params,
                in_sample=chosen.in_sample,
                out_sample=out_metrics,
                num_trades_in=chosen.in_sample.num_round_trips,
                num_trades_out=out_metrics.num_round_trips,
            )
        )
        if getattr(out_metrics, objective) > getattr(baseline_out, objective):
            beats += 1

    summary = summarize(per_split_combo, objective=objective, baseline_out_sample=None)
    if split_results:
        summary = replace_pct_beating_baseline(summary, beats / len(split_results))
    return WalkForwardResult(objective=objective, splits=split_results, summary=summary)


def _build_train_result(combo: dict[str, Any], metrics: Metrics) -> CombinationResult:
    return CombinationResult(
        params=combo,
        in_sample=metrics,
        out_sample=None,
        num_trades_in=metrics.num_round_trips,
        num_trades_out=0,
    )
