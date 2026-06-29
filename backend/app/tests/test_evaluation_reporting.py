"""Distribution aggregation: selection on in-sample only, honest summary stats."""

from __future__ import annotations

from app.backtesting.metrics import Metrics
from app.evaluation.reporting import (
    CombinationResult,
    select_best,
    summarize,
)


def _m(**over: float) -> Metrics:
    """A zeroed Metrics with selected fields overridden."""
    base: dict = {
        "total_return_pct": 0.0,
        "annualized_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "num_round_trips": 0,
        "num_fills": 0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "avg_holding_days": 0.0,
        "exposure_pct": 0.0,
    }
    base.update(over)
    return Metrics(**base)  # type: ignore[arg-type]


def _combo(params: dict, *, in_sample: Metrics, out_sample: Metrics | None) -> CombinationResult:
    return CombinationResult(
        params=params,
        in_sample=in_sample,
        out_sample=out_sample,
        num_trades_in=in_sample.num_round_trips,
        num_trades_out=out_sample.num_round_trips if out_sample else 0,
    )


def test_select_best_uses_in_sample_only() -> None:
    # A: strong in-sample, weak out-of-sample. B: weak in, strong out.
    a = _combo({"x": 1}, in_sample=_m(sharpe_ratio=2.0), out_sample=_m(sharpe_ratio=0.1))
    b = _combo({"x": 2}, in_sample=_m(sharpe_ratio=0.5), out_sample=_m(sharpe_ratio=3.0))
    chosen = select_best([a, b], objective="sharpe_ratio")
    assert chosen.params == {"x": 1}  # picked on in-sample, ignoring out-of-sample


def test_select_best_tie_break_on_return() -> None:
    a = _combo({"x": 1}, in_sample=_m(sharpe_ratio=1.0, total_return_pct=5.0), out_sample=None)
    b = _combo({"x": 2}, in_sample=_m(sharpe_ratio=1.0, total_return_pct=9.0), out_sample=None)
    chosen = select_best([a, b], objective="sharpe_ratio")
    assert chosen.params == {"x": 2}


def test_summary_best_median_worst() -> None:
    combos = [
        _combo({"x": 1}, in_sample=_m(sharpe_ratio=1.0), out_sample=_m(sharpe_ratio=0.5)),
        _combo({"x": 2}, in_sample=_m(sharpe_ratio=1.0), out_sample=_m(sharpe_ratio=1.5)),
        _combo({"x": 3}, in_sample=_m(sharpe_ratio=1.0), out_sample=_m(sharpe_ratio=1.0)),
    ]
    s = summarize(combos, objective="sharpe_ratio", baseline_out_sample=None)
    assert s.best == 1.5
    assert s.worst == 0.5
    assert s.median == 1.0


def test_pct_beating_baseline() -> None:
    combos = [
        _combo({"x": i}, in_sample=_m(sharpe_ratio=1.0), out_sample=_m(sharpe_ratio=v))
        for i, v in enumerate([0.1, 0.4, 0.9, 1.2])
    ]
    baseline = _m(sharpe_ratio=0.5)  # two of four out-of-sample values exceed 0.5
    s = summarize(combos, objective="sharpe_ratio", baseline_out_sample=baseline)
    assert s.pct_beating_baseline == 0.5


def test_no_baseline_pct_is_zero() -> None:
    combos = [_combo({"x": 1}, in_sample=_m(sharpe_ratio=1.0), out_sample=_m(sharpe_ratio=1.0))]
    s = summarize(combos, objective="sharpe_ratio", baseline_out_sample=None)
    assert s.pct_beating_baseline == 0.0


def test_overfit_flag_trips_on_large_gap() -> None:
    # Best in-sample combo collapses out-of-sample (out < half of in).
    combos = [
        _combo({"x": 1}, in_sample=_m(sharpe_ratio=2.0), out_sample=_m(sharpe_ratio=0.1)),
        _combo({"x": 2}, in_sample=_m(sharpe_ratio=1.0), out_sample=_m(sharpe_ratio=0.9)),
    ]
    s = summarize(combos, objective="sharpe_ratio", baseline_out_sample=None)
    assert s.overfit_flag is True
    assert s.in_sample_vs_out_sample_gap == 1.9  # 2.0 in - 0.1 out


def test_overfit_flag_false_when_stable() -> None:
    combos = [
        _combo({"x": 1}, in_sample=_m(sharpe_ratio=1.0), out_sample=_m(sharpe_ratio=0.9)),
    ]
    s = summarize(combos, objective="sharpe_ratio", baseline_out_sample=None)
    assert s.overfit_flag is False


def test_objective_can_be_any_metric_field() -> None:
    combos = [
        _combo({"x": 1}, in_sample=_m(total_return_pct=10.0), out_sample=_m(total_return_pct=4.0)),
        _combo({"x": 2}, in_sample=_m(total_return_pct=5.0), out_sample=_m(total_return_pct=8.0)),
    ]
    s = summarize(combos, objective="total_return_pct", baseline_out_sample=None)
    assert s.best == 8.0
    assert s.worst == 4.0


def test_empty_results_is_zeroed() -> None:
    s = summarize([], objective="sharpe_ratio", baseline_out_sample=None)
    assert s.best == 0.0 and s.median == 0.0 and s.worst == 0.0
    assert s.best_params == {}
    assert s.overfit_flag is False
