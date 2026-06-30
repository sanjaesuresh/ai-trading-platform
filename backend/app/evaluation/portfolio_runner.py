"""Walk-forward / sweep runner for the multi-symbol portfolio backtest (Phase 3).

The portfolio analogue of :mod:`app.evaluation.runner`. It reuses the existing
honest-evaluation machinery unchanged — ``generate_splits`` for the train/test
windows, ``select_best`` for in-sample-only selection, and ``summarize`` /
``replace_pct_beating_baseline`` for the distribution and baseline comparison —
swapping only the scorer: each combination is scored by running the portfolio
backtest over the basket rather than a single-symbol backtest.

Because selection reads in-sample only and the chosen combination plus the
rule-based baseline are scored on the held-out test window, the portfolio
allocator is judged out-of-sample, net of fees, against the baseline — the same
discipline that keeps single-symbol results honest, now with a portfolio as one
more place to overfit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.backtesting.engine import run_backtest
from app.backtesting.metrics import Metrics
from app.backtesting.portfolio_backtest import align_frames, run_portfolio_backtest
from app.backtesting.portfolio_core import PortfolioConfig
from app.backtesting.portfolio_metrics import compute_portfolio_metrics
from app.backtesting.records import EquityPoint
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


@dataclass
class PortfolioWalkForwardResult:
    """A portfolio walk-forward outcome.

    Wraps the standard ``WalkForwardResult`` (chosen-combo vs the rule-based
    baseline, both with the allocator on) and adds the §6 control: the
    **allocator-off** comparison. ``single_position_out_sample`` is, per split,
    the same strategy/params run single-position per symbol at equal weight (no
    cross-symbol allocation); ``pct_beating_single_position`` is the fraction of
    splits where the portfolio allocator beat that allocator-off basket on the
    objective. If the allocator cannot beat equal-weight single-position results
    net of fees, it has not earned its added complexity — that is the honest
    reading this field exists to surface.
    """

    walk_forward: WalkForwardResult
    single_position_out_sample: list[Metrics] = field(default_factory=list)
    pct_beating_single_position: float | None = None


def _score_portfolio(
    frames: Mapping[str, pd.DataFrame],
    *,
    strategy_name: str,
    params: dict[str, Any],
    config: PortfolioConfig,
) -> tuple[Metrics, int]:
    """Run the portfolio backtest for one combination and return its metrics and
    round-trip count. Mirrors ``runner._score`` but over a basket — and reports
    round trips (not fills) so ``num_trades_*`` means the same thing as the
    single-symbol runner's contract."""
    strategy = resolve_strategy(strategy_name, params)
    result = run_portfolio_backtest(frames, strategy, config)
    metrics = compute_portfolio_metrics(
        result.equity_curve, result.trades, config.initial_capital
    )
    return metrics, metrics.num_round_trips


def _score_single_position_basket(
    frames: Mapping[str, pd.DataFrame],
    *,
    strategy_name: str,
    params: dict[str, Any],
    config: PortfolioConfig,
) -> Metrics:
    """Allocator-off baseline: run each symbol single-position at equal capital
    (1/N), with the same strategy/params, costs, sizing, and per-symbol risk, then
    combine the per-symbol equity curves into one portfolio curve and pool trades.

    This is the comparison that isolates the cross-symbol allocator's value: same
    strategy, no portfolio allocation. Uses the single-symbol engine directly.
    """
    symbols = sorted(frames)
    if not symbols:
        return compute_portfolio_metrics([], [], config.initial_capital)
    cap_each = config.initial_capital / len(symbols)

    combined: dict[pd.Timestamp, EquityPoint] | None = None
    pooled_trades = []
    for sym in symbols:
        strategy = resolve_strategy(strategy_name, params)
        res = run_backtest(
            frames[sym], strategy, sym,
            initial_capital=cap_each, fee_bps=config.fee_bps,
            slippage_bps=config.slippage_bps, max_position_pct=config.max_position_pct,
            target_vol=config.target_vol, vol_lookback=config.vol_lookback,
            stop_loss_pct=config.stop_loss_pct, take_profit_pct=config.take_profit_pct,
            max_drawdown_cutoff_pct=config.max_drawdown_cutoff_pct,
        )
        pooled_trades.extend(res.trades)
        if combined is None:
            combined = {
                p.timestamp: EquityPoint(p.timestamp, p.equity, p.cash, p.position_value)
                for p in res.equity_curve
            }
        else:
            for p in res.equity_curve:
                agg = combined[p.timestamp]
                combined[p.timestamp] = EquityPoint(
                    p.timestamp, agg.equity + p.equity, agg.cash + p.cash,
                    agg.position_value + p.position_value,
                )
    curve = [combined[ts] for ts in sorted(combined)] if combined else []
    return compute_portfolio_metrics(curve, pooled_trades, config.initial_capital)


def run_portfolio_sweep(
    featured_frames: Mapping[str, pd.DataFrame],
    *,
    strategy_name: str,
    param_grid: dict[str, list],
    config: PortfolioConfig,
    objective: str = "sharpe_ratio",
) -> tuple[list[CombinationResult], DistributionSummary]:
    """Score every combination once over the whole basket history (no split).

    In-sample only — the summary's ``is_out_of_sample`` is False. Use the
    walk-forward variant for out-of-sample evidence.
    """
    combos = expand_param_grid(strategy_name, param_grid)
    results: list[CombinationResult] = []
    for params in combos:
        metrics, n_trades = _score_portfolio(
            featured_frames, strategy_name=strategy_name, params=params, config=config
        )
        results.append(
            CombinationResult(
                params=params, in_sample=metrics, out_sample=None,
                num_trades_in=n_trades, num_trades_out=0,
            )
        )
    summary = summarize(results, objective=objective, baseline_out_sample=None)
    return results, summary


def _slice_frames(
    aligned: Mapping[str, pd.DataFrame], start: int, end: int
) -> dict[str, pd.DataFrame]:
    """Slice every aligned frame to bars ``[start:end)`` and restore the
    ``timestamp`` column so ``run_portfolio_backtest`` consumes them unchanged."""
    return {
        sym: f.iloc[start:end].reset_index() for sym, f in aligned.items()
    }


def run_portfolio_walk_forward(
    featured_frames: Mapping[str, pd.DataFrame],
    *,
    strategy_name: str,
    param_grid: dict[str, list],
    splits: list[WalkForwardSplit],
    config: PortfolioConfig,
    objective: str = "sharpe_ratio",
    baseline_strategy_name: str = "trend_following",
    baseline_params: dict[str, Any] | None = None,
) -> PortfolioWalkForwardResult:
    """Per split: select the best combination in-sample, then score it, the
    rule-based baseline, and the allocator-off single-position basket on the
    held-out test window. Returns the per-split detail, an honest distribution
    summary with the per-split baseline beat rate, and the §6 allocator-off
    comparison (``pct_beating_single_position``).

    Splits index over the **common timeline** (the intersection of the basket's
    trading days); every symbol is sliced on the same bar indices.
    """
    baseline_params = baseline_params or {}
    _symbols, _timeline, aligned = align_frames(featured_frames)

    split_results: list[SplitResult] = []
    per_split_combo: list[CombinationResult] = []
    single_position_out: list[Metrics] = []
    beats = 0
    single_pos_beats = 0

    for split in splits:
        train = _slice_frames(aligned, split.train_start, split.train_end)
        test = _slice_frames(aligned, split.test_start, split.test_end)

        # In-sample: score every combination on the train window.
        combos = expand_param_grid(strategy_name, param_grid)
        train_results: list[CombinationResult] = []
        for params in combos:
            metrics, n_trades = _score_portfolio(
                train, strategy_name=strategy_name, params=params, config=config
            )
            train_results.append(
                CombinationResult(
                    params=params, in_sample=metrics, out_sample=None,
                    num_trades_in=n_trades, num_trades_out=0,
                )
            )
        chosen = select_best(train_results, objective=objective)

        # Out-of-sample: the chosen combination and the baseline on the test window.
        out_metrics, n_out = _score_portfolio(
            test, strategy_name=strategy_name, params=chosen.params, config=config
        )
        baseline_out, _ = _score_portfolio(
            test, strategy_name=baseline_strategy_name, params=baseline_params,
            config=config,
        )
        # Allocator-off control: the chosen strategy/params run single-position
        # per symbol at equal weight on the same test window (§6).
        single_pos = _score_single_position_basket(
            test, strategy_name=strategy_name, params=chosen.params, config=config
        )
        single_position_out.append(single_pos)
        if getattr(out_metrics, objective) > getattr(single_pos, objective):
            single_pos_beats += 1

        split_results.append(
            SplitResult(
                train_start=split.train_start, train_end=split.train_end,
                test_start=split.test_start, test_end=split.test_end,
                chosen_params=chosen.params, in_sample=chosen.in_sample,
                out_sample=out_metrics, num_trades_in=chosen.num_trades_in,
                num_trades_out=n_out, baseline_out_sample=baseline_out,
            )
        )
        per_split_combo.append(
            CombinationResult(
                params=chosen.params, in_sample=chosen.in_sample,
                out_sample=out_metrics, num_trades_in=chosen.num_trades_in,
                num_trades_out=n_out,
            )
        )
        if getattr(out_metrics, objective) > getattr(baseline_out, objective):
            beats += 1

    summary = summarize(per_split_combo, objective=objective, baseline_out_sample=None)
    if split_results:
        summary = replace_pct_beating_baseline(summary, beats / len(split_results))

    wf = WalkForwardResult(
        objective=objective, splits=split_results, summary=summary
    )
    pct_beating_single = (
        single_pos_beats / len(split_results) if split_results else None
    )
    return PortfolioWalkForwardResult(
        walk_forward=wf,
        single_position_out_sample=single_position_out,
        pct_beating_single_position=pct_beating_single,
    )
