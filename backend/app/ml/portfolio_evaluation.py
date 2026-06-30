"""Multi-symbol ML walk-forward through the Phase 3 portfolio core (Phase 4 M6).

The portfolio analogue of :mod:`app.ml.evaluation`. Where M3 scores a single
symbol through the single-symbol engine, this drives the *pooled-trained* ML
classifier MULTI-SYMBOL through the shared :mod:`app.backtesting.portfolio_core`
— the same allocation / sizing / risk core the live paper runner uses — and judges
it per symbol and against baselines on the held-out windows, net of fees.

Why this shape (the honest-evaluation discipline carried into the portfolio):

- **One pooled model per split, isolated strategy instance per symbol.** Each
  walk-forward split trains a fresh model on its in-sample window (``train_model``)
  and drives the basket OOS with a fresh ``MLClassifierStrategy.from_model`` PER
  symbol, supplied to ``run_portfolio_backtest`` as a per-symbol factory. The ML
  classifier is single-run stateful (it carries ``self._bars_held``), so a shared
  instance would let one symbol's holding counter corrupt another's signal — the
  per-symbol seam in the portfolio driver is what keeps the basket honest.

- **No look-ahead.** The purged splitter keys the train/test boundary to a single
  calendar date across every pooled symbol and purges training labels that reach
  into the held-out window. Each symbol's OOS frame is sliced strictly to the test
  window, so every OOS bar is later than the training window end (recorded per
  split so the property is auditable).

- **Per-symbol OOS breakdown.** From the portfolio's per-symbol trades, each
  symbol's OOS contribution (realized PnL, round trips, win rate) is reported, so
  an aggregate edge carried by one name while the rest lose — the single-asset
  dependence tell — is visible rather than hidden inside a basket number.

- **Baselines on the identical windows.** The rule strategy through the same
  portfolio core, an equal-weight buy-and-hold basket, and the allocator-off
  equal-weight single-position control (the same ML strategy run one-symbol-at-a-
  time at 1/N), all scored net of fees on the same OOS windows. If the portfolio
  ML cannot beat these, it has not earned its complexity.

What this module deliberately does NOT (yet) compute: the full §8 significance
battery (PBO via CSCV, the Monte-Carlo random ensemble) over the *portfolio* return
stream. It reports the aggregate-vs-baselines comparison, the per-symbol breakdown,
turnover, the per-period Sharpe, and the deflated Sharpe (which needs no ensemble).
Extending PBO/MC to the portfolio leg is a documented follow-up (see the report).

Pure logic, DB-free. The result carries a ``to_dict`` of plain JSON-serializable
types (non-finite floats sanitized by the shared ``sanitize_result_dict`` helper at
the service boundary) so it persists cleanly into ``evaluation_runs``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.engine import run_backtest
from app.backtesting.metrics import pair_round_trips
from app.backtesting.portfolio_backtest import align_frames, run_portfolio_backtest
from app.backtesting.portfolio_core import PortfolioConfig
from app.backtesting.portfolio_metrics import compute_portfolio_metrics
from app.backtesting.records import EquityPoint, TradeRecord
from app.evaluation.walk_forward import generate_purged_splits
from app.ml.evaluation import (
    SkippedSplit,
    StrategyScore,
    _BuyAndHoldStrategy,
    default_n_config_trials,
)
from app.ml.features import (
    COL_DECISION_TS,
    COL_WEIGHT,
    FEATURE_COLUMNS,
    build_features,
    effective_sample_size,
)
from app.ml.model import TrainedModel
from app.ml.significance import deflated_sharpe_ratio, returns_moments
from app.ml.training import TrainingConfig, TrainingError, train_model
from app.strategies.base_strategy import BaseStrategy
from app.strategies.ml_classifier import MLClassifierStrategy
from app.strategies.trend_following import TrendFollowingStrategy

# Baseline keys, exported so the wiring/UI reference names rather than literals.
BASE_BUY_AND_HOLD_BASKET = "buy_and_hold_basket"
BASE_RULE_PORTFOLIO = "rule_portfolio"
BASE_SINGLE_POSITION = "single_position_equal_weight"

_PERIODS_PER_YEAR = 252.0


# ---------------------------------------------------------------------------
# Result types (frozen, serializable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolOOSBreakdown:
    """One symbol's pooled out-of-sample contribution to the portfolio result.

    ``contribution_pct`` is the symbol's realized PnL as a fraction of the per-split
    starting capital (additive across splits, NOT compounded) — a contribution
    share, not a standalone return. It exists to surface single-asset dependence:
    an aggregate basket edge carried by one name while the others lose.
    """

    symbol: str
    realized_pnl: float
    contribution_pct: float
    num_round_trips: int
    win_rate: float  # 0..1 over this symbol's round trips

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "realized_pnl": float(self.realized_pnl),
            "contribution_pct": float(self.contribution_pct),
            "num_round_trips": int(self.num_round_trips),
            "win_rate": float(self.win_rate),
        }


@dataclass(frozen=True)
class PortfolioSplitResult:
    """Everything scored for one non-skipped portfolio walk-forward split."""

    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_end: pd.Timestamp
    oos_first_ts: pd.Timestamp
    n_oos_bars: int
    symbols: list[str]
    model: StrategyScore
    baselines: dict[str, StrategyScore]
    beats: dict[str, bool]

    def no_look_ahead(self) -> bool:
        """True iff the first OOS bar is strictly after the training window end."""
        return pd.Timestamp(self.oos_first_ts) > pd.Timestamp(self.train_end)

    def to_dict(self) -> dict[str, object]:
        return {
            "test_start": str(self.test_start),
            "test_end": str(self.test_end),
            "train_end": str(self.train_end),
            "oos_first_ts": str(self.oos_first_ts),
            "n_oos_bars": int(self.n_oos_bars),
            "no_look_ahead": bool(self.no_look_ahead()),
            "symbols": list(self.symbols),
            "model": self.model.to_dict(),
            "baselines": {k: v.to_dict() for k, v in self.baselines.items()},
            "beats": {k: bool(v) for k, v in self.beats.items()},
        }


@dataclass(frozen=True)
class PortfolioSignificance:
    """The cheap-to-compute significance block for the portfolio return stream.

    PBO and the Monte-Carlo ensemble are NOT included here (they need a candidate
    matrix / random ensemble over the basket); the deflated Sharpe needs neither,
    so it is reported as the multiple-testing-aware honesty stat. Extending the full
    §8 battery to the portfolio is a documented follow-up.
    """

    per_period_sharpe: float
    skew: float
    kurtosis: float
    n_obs: int
    n_eff: float
    var_trial_sharpes: float
    deflated_sharpe: float
    n_config_trials: int
    n_oos_round_trips: int

    def to_dict(self) -> dict[str, object]:
        return {
            "per_period_sharpe": float(self.per_period_sharpe),
            "skew": float(self.skew),
            "kurtosis": float(self.kurtosis),
            "n_obs": int(self.n_obs),
            "n_eff": float(self.n_eff),
            "var_trial_sharpes": float(self.var_trial_sharpes),
            "deflated_sharpe": float(self.deflated_sharpe),
            "n_config_trials": int(self.n_config_trials),
            "n_oos_round_trips": int(self.n_oos_round_trips),
        }


@dataclass(frozen=True)
class MLPortfolioEvaluationResult:
    """The complete multi-symbol portfolio walk-forward verdict."""

    symbols: list[str]
    splits: list[PortfolioSplitResult]
    skipped: list[SkippedSplit]
    per_symbol: list[SymbolOOSBreakdown]
    aggregate_model: dict[str, float]
    aggregate_baselines: dict[str, dict[str, float]]
    significance: PortfolioSignificance
    beats_all_baselines: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "symbols": list(self.symbols),
            "splits": [s.to_dict() for s in self.splits],
            "skipped": [s.to_dict() for s in self.skipped],
            "per_symbol": [s.to_dict() for s in self.per_symbol],
            "aggregate_model": {k: float(v) for k, v in self.aggregate_model.items()},
            "aggregate_baselines": {
                name: {k: float(v) for k, v in m.items()}
                for name, m in self.aggregate_baselines.items()
            },
            "significance": self.significance.to_dict(),
            "beats_all_baselines": bool(self.beats_all_baselines),
            "reasons": list(self.reasons),
        }


# ---------------------------------------------------------------------------
# Small numeric / scoring helpers
# ---------------------------------------------------------------------------


def _ml_strategy_factory(model: TrainedModel) -> Callable[[str], BaseStrategy]:
    """A per-symbol factory that builds a FRESH ``MLClassifierStrategy`` for each
    symbol from one pooled model — the isolation seam the portfolio driver needs so
    the classifier's ``_bars_held`` counter never crosses symbols."""

    def factory(_symbol: str) -> BaseStrategy:
        return MLClassifierStrategy.from_model(model)

    return factory


def _buy_and_hold_factory(_symbol: str) -> BaseStrategy:
    """Per-symbol buy-and-hold for the equal-weight basket baseline."""
    return _BuyAndHoldStrategy()


def _ensure_featured(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a frame with the ``f_*`` feature columns present (idempotent).

    ``build_ml_inputs`` hands back OHLCV+indicator frames; the engine needs the
    causal ``f_*`` features the ML strategy reads, so build them when absent. When
    they are already present (e.g. a test passes pre-featured frames) the frame is
    returned untouched.
    """
    if FEATURE_COLUMNS[0] in frame.columns:
        return frame
    return build_features(frame)


def _slice_oos(
    frame: pd.DataFrame, test_start: pd.Timestamp, test_end: pd.Timestamp
) -> pd.DataFrame:
    """Contiguous rows whose timestamp falls in [start, end] inclusive (reindexed)."""
    ts = frame["timestamp"]
    mask = (ts >= test_start) & (ts <= test_end)
    return frame.loc[mask].reset_index(drop=True)


def _per_bar_returns(equity_curve: list[EquityPoint]) -> np.ndarray:
    """Per-bar simple returns of a portfolio equity curve (length n_bars - 1)."""
    eq = np.array([p.equity for p in equity_curve], dtype=float)
    if eq.size < 2:
        return np.empty(0, dtype=float)
    prev = eq[:-1]
    return np.where(prev != 0.0, np.diff(eq) / np.where(prev == 0.0, 1.0, prev), 0.0)


def _turnover_annualized(
    equity_curve: list[EquityPoint], trades: list[TradeRecord]
) -> float:
    """Annualized gross traded notional over mean equity (cost-intensity signal)."""
    n_bars = len(equity_curve)
    if n_bars == 0:
        return 0.0
    mean_equity = float(np.mean([p.equity for p in equity_curve]))
    years = n_bars / _PERIODS_PER_YEAR
    if mean_equity <= 0.0 or years <= 0.0:
        return 0.0
    gross = float(sum(abs(t.gross_value) for t in trades))
    return gross / mean_equity / years


def _score(
    name: str,
    equity_curve: list[EquityPoint],
    trades: list[TradeRecord],
    initial_capital: float,
) -> StrategyScore:
    """Wrap a portfolio run's curve+trades into the shared ``StrategyScore`` shape."""
    metrics = compute_portfolio_metrics(equity_curve, trades, initial_capital)
    return StrategyScore(
        name=name,
        metrics=metrics,
        turnover_annualized=_turnover_annualized(equity_curve, trades),
        total_return_pct=float(metrics.total_return_pct),
        oos_round_trips=int(metrics.num_round_trips),
        per_bar_returns=tuple(float(r) for r in _per_bar_returns(equity_curve)),
    )


def _compound(returns_pct: Sequence[float]) -> float:
    """Compound per-split percentage returns into one total return %."""
    growth = 1.0
    for r in returns_pct:
        growth *= 1.0 + r / 100.0
    return (growth - 1.0) * 100.0


def _single_position_basket(
    frames: Mapping[str, pd.DataFrame],
    factory: Callable[[str], BaseStrategy],
    config: PortfolioConfig,
) -> tuple[list[EquityPoint], list[TradeRecord]]:
    """Allocator-OFF control: each symbol single-position at equal capital (1/N).

    Mirrors ``portfolio_runner._score_single_position_basket`` but takes a strategy
    factory (so it serves both the buy-and-hold basket and the ML single-position
    control). Same costs / sizing / per-symbol risk as the portfolio config; the
    per-symbol equity curves are summed into one basket curve and trades pooled.
    Returns the combined curve + pooled trades for scoring by the caller.
    """
    symbols = sorted(frames)
    if not symbols:
        return [], []
    cap_each = config.initial_capital / len(symbols)

    combined: dict[pd.Timestamp, EquityPoint] | None = None
    pooled_trades: list[TradeRecord] = []
    for sym in symbols:
        res = run_backtest(
            frames[sym], factory(sym), sym,
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
    return curve, pooled_trades


def _symbol_breakdowns(
    trades: list[TradeRecord], symbols: Sequence[str], initial_capital: float
) -> list[SymbolOOSBreakdown]:
    """Per-symbol OOS contribution from the pooled portfolio trades.

    Each symbol is long-only one-position-at-a-time, so its fill stream alternates
    BUY/SELL across splits and pairs into clean round trips. Contribution is the
    symbol's summed realized PnL over the per-split starting capital — additive, so
    one name's carry of the basket is plain to see.
    """
    by_symbol: dict[str, list[TradeRecord]] = {s: [] for s in symbols}
    for t in trades:
        by_symbol.setdefault(t.symbol, []).append(t)

    out: list[SymbolOOSBreakdown] = []
    for sym in symbols:
        round_trips = pair_round_trips(by_symbol.get(sym, []))
        pnls = [rt.pnl for rt in round_trips]
        wins = sum(1 for p in pnls if p > 0)
        n = len(round_trips)
        realized = float(sum(pnls))
        out.append(
            SymbolOOSBreakdown(
                symbol=sym,
                realized_pnl=realized,
                contribution_pct=(realized / initial_capital * 100.0)
                if initial_capital
                else 0.0,
                num_round_trips=n,
                win_rate=(wins / n) if n else 0.0,
            )
        )
    return out


def _aggregate_baseline(
    splits: list[PortfolioSplitResult], name: str, agg_total: float
) -> dict[str, float]:
    return {
        "total_return_pct": agg_total,
        "mean_turnover_annualized": float(
            np.mean([s.baselines[name].turnover_annualized for s in splits])
            if splits
            else 0.0
        ),
        "num_oos_round_trips": float(
            sum(s.baselines[name].oos_round_trips for s in splits)
        ),
    }


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------


def evaluate_ml_portfolio_walk_forward(
    panel: pd.DataFrame,
    frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    config: PortfolioConfig,
    training_config: TrainingConfig | None = None,
    horizon: int = 5,
    embargo: int | None = None,
    in_sample_dates: int = 504,
    out_sample_dates: int = 126,
    step_dates: int = 126,
    scheme: str = "anchored",
    n_config_trials: int | None = None,
) -> MLPortfolioEvaluationResult:
    """Train a fresh pooled model per purged split and score the basket OOS through
    the shared portfolio core against the rule, buy-and-hold-basket, and allocator-
    off single-position baselines — net of fees, with a per-symbol breakdown.

    ``panel`` is the pooled feature/label matrix (``build_pooled_panel``). ``frames``
    maps each symbol to its featured frame (OHLCV + indicators, ``f_*`` built here if
    absent). Costs / sizing / risk come from ``config`` (a ``PortfolioConfig``), so
    every strategy is judged on the identical portfolio execution model. A split
    whose model cannot be trained (single-class fold) or whose OOS basket is
    degenerate (< 2 common bars) is recorded as skipped, never fatal.
    """
    # Disjoint OOS windows: overlapping test windows would double-count bars and
    # inflate the aggregate (same guard as the single-symbol evaluator).
    if step_dates < out_sample_dates:
        raise ValueError(
            f"step_dates={step_dates} < out_sample_dates={out_sample_dates}: "
            "overlapping test windows would double-count OOS bars and inflate the "
            "aggregate. Set step_dates >= out_sample_dates for disjoint windows."
        )

    training_config = training_config or TrainingConfig()
    if n_config_trials is None:
        n_config_trials = default_n_config_trials(training_config)

    symbols = sorted(symbols)
    missing = [s for s in symbols if s not in frames]
    if missing:
        raise ValueError(f"symbols not in frames: {', '.join(missing)}.")
    featured: dict[str, pd.DataFrame] = {
        s: _ensure_featured(frames[s]) for s in symbols
    }

    splits = generate_purged_splits(
        panel,
        horizon=horizon,
        embargo=embargo,
        scheme=scheme,
        in_sample_dates=in_sample_dates,
        out_sample_dates=out_sample_dates,
        step_dates=step_dates,
    )

    split_results: list[PortfolioSplitResult] = []
    skipped: list[SkippedSplit] = []
    model_trades: list[TradeRecord] = []  # pooled ML trades for the per-symbol view
    initial_capital = float(config.initial_capital)

    oos_panel_mask = np.zeros(len(panel), dtype=bool)
    decision_np = panel[COL_DECISION_TS].to_numpy() if len(panel) else np.empty(0)

    for split in splits:
        try:
            train_result = train_model(panel, split.train_idx, config=training_config)
        except TrainingError as exc:
            skipped.append(
                SkippedSplit(split.test_start, split.test_end, str(exc))
            )
            continue
        model = train_result.model

        oos_frames = {
            s: _slice_oos(featured[s], split.test_start, split.test_end)
            for s in symbols
        }
        oos_frames = {s: f for s, f in oos_frames.items() if len(f) >= 2}
        if not oos_frames:
            skipped.append(
                SkippedSplit(
                    split.test_start, split.test_end,
                    "No symbol has >= 2 out-of-sample bars in this window.",
                )
            )
            continue
        _syms, timeline, _aligned = align_frames(oos_frames)
        if len(timeline) < 2:
            skipped.append(
                SkippedSplit(
                    split.test_start, split.test_end,
                    "Aligned out-of-sample basket has fewer than 2 common bars.",
                )
            )
            continue

        # --- Portfolio ML: a FRESH, ISOLATED strategy instance per symbol ---
        ml_factory = _ml_strategy_factory(model)
        ml_res = run_portfolio_backtest(oos_frames, ml_factory, config)
        model_trades.extend(ml_res.trades)
        model_score = _score("model", ml_res.equity_curve, ml_res.trades, initial_capital)

        # --- Baselines on the identical windows / costs ---
        rule_res = run_portfolio_backtest(oos_frames, TrendFollowingStrategy(), config)
        rule_score = _score(
            BASE_RULE_PORTFOLIO, rule_res.equity_curve, rule_res.trades, initial_capital
        )

        bh_curve, bh_trades = _single_position_basket(
            oos_frames, _buy_and_hold_factory, config
        )
        bh_score = _score(BASE_BUY_AND_HOLD_BASKET, bh_curve, bh_trades, initial_capital)

        # Allocator-off control: the SAME ML strategy run single-position per symbol
        # at equal weight (1/N), so the cross-symbol allocator's added value is
        # isolated. Reuses the same per-symbol factory (fresh instance per symbol).
        sp_curve, sp_trades = _single_position_basket(oos_frames, ml_factory, config)
        sp_score = _score(BASE_SINGLE_POSITION, sp_curve, sp_trades, initial_capital)

        baselines = {
            BASE_RULE_PORTFOLIO: rule_score,
            BASE_BUY_AND_HOLD_BASKET: bh_score,
            BASE_SINGLE_POSITION: sp_score,
        }
        beats = {
            name: model_score.total_return_pct > b.total_return_pct
            for name, b in baselines.items()
        }

        oos_first_ts = pd.Timestamp(timeline[0])
        split_results.append(
            PortfolioSplitResult(
                test_start=split.test_start,
                test_end=split.test_end,
                train_end=train_result.train_end,
                oos_first_ts=oos_first_ts,
                n_oos_bars=len(timeline),
                symbols=sorted(oos_frames),
                model=model_score,
                baselines=baselines,
                beats=beats,
            )
        )

        if len(panel):
            window = (
                (decision_np >= np.datetime64(split.test_start))
                & (decision_np <= np.datetime64(split.test_end))
            )
            oos_panel_mask |= window

    n_eff = (
        effective_sample_size(panel.loc[oos_panel_mask, COL_WEIGHT])
        if oos_panel_mask.any()
        else 0.0
    )

    return _aggregate(
        symbols=symbols,
        splits=split_results,
        skipped=skipped,
        model_trades=model_trades,
        initial_capital=initial_capital,
        n_eff=n_eff,
        n_config_trials=n_config_trials,
    )


def _aggregate(
    *,
    symbols: list[str],
    splits: list[PortfolioSplitResult],
    skipped: list[SkippedSplit],
    model_trades: list[TradeRecord],
    initial_capital: float,
    n_eff: float,
    n_config_trials: int,
) -> MLPortfolioEvaluationResult:
    """Roll per-split portfolio scores into aggregates, baselines, and the cheap
    significance block, and assemble the per-symbol OOS breakdown."""
    # Concatenated, time-ordered portfolio OOS per-bar returns.
    model_bars = (
        np.concatenate(
            [np.asarray(s.model.per_bar_returns, dtype=float) for s in splits]
        )
        if splits
        else np.empty(0, dtype=float)
    )
    moments = returns_moments(model_bars)

    # Cross-split dispersion of the per-period Sharpe, floored by the Lo (2002)
    # sampling variance so the deflation never silently vanishes on few splits.
    per_split_sharpes = [
        returns_moments(np.asarray(s.model.per_bar_returns, dtype=float)).sharpe
        for s in splits
    ]
    var_trial = (
        float(np.var(np.asarray(per_split_sharpes), ddof=1))
        if len(per_split_sharpes) >= 2
        else 0.0
    )
    n_eff_floor = max(1.0, n_eff)
    sharpe_sampling_var = (1.0 + 0.5 * moments.sharpe**2) / n_eff_floor
    var_trial = max(var_trial, sharpe_sampling_var)

    n_track = int(round(n_eff))
    dsr = deflated_sharpe_ratio(
        moments.sharpe, n_track, moments.skew, moments.kurtosis,
        n_trials=n_config_trials, variance_of_trial_sharpes=var_trial,
    )

    agg_model_ret = _compound([s.model.total_return_pct for s in splits])
    n_oos_round_trips = int(sum(s.model.oos_round_trips for s in splits))

    baseline_names = [BASE_RULE_PORTFOLIO, BASE_BUY_AND_HOLD_BASKET, BASE_SINGLE_POSITION]
    agg_baseline_returns = {
        name: _compound([s.baselines[name].total_return_pct for s in splits])
        for name in baseline_names
    }
    beats = {name: agg_model_ret > ret for name, ret in agg_baseline_returns.items()}
    beats_all = bool(splits) and all(beats.values())

    splits_beating = {
        name: sum(1 for s in splits if s.beats.get(name, False))
        for name in baseline_names
    }

    significance = PortfolioSignificance(
        per_period_sharpe=moments.sharpe,
        skew=moments.skew,
        kurtosis=moments.kurtosis,
        n_obs=int(model_bars.size),
        n_eff=float(n_eff),
        var_trial_sharpes=var_trial,
        deflated_sharpe=dsr,
        n_config_trials=int(n_config_trials),
        n_oos_round_trips=n_oos_round_trips,
    )

    aggregate_model = {
        "total_return_pct": agg_model_ret,
        "per_period_sharpe": moments.sharpe,
        "deflated_sharpe": dsr,
        "num_oos_round_trips": float(n_oos_round_trips),
        "mean_turnover_annualized": float(
            np.mean([s.model.turnover_annualized for s in splits]) if splits else 0.0
        ),
        "n_splits_evaluated": float(len(splits)),
        "beats_rule_portfolio": float(beats[BASE_RULE_PORTFOLIO]),
        "beats_buy_and_hold_basket": float(beats[BASE_BUY_AND_HOLD_BASKET]),
        "beats_single_position": float(beats[BASE_SINGLE_POSITION]),
        "splits_beating_rule_portfolio": float(splits_beating[BASE_RULE_PORTFOLIO]),
        "splits_beating_buy_and_hold_basket": float(
            splits_beating[BASE_BUY_AND_HOLD_BASKET]
        ),
        "splits_beating_single_position": float(splits_beating[BASE_SINGLE_POSITION]),
    }
    aggregate_baselines = {
        name: _aggregate_baseline(splits, name, agg_baseline_returns[name])
        for name in baseline_names
    }

    per_symbol = _symbol_breakdowns(model_trades, symbols, initial_capital)

    reasons = _reasons(splits, skipped, beats, beats_all, per_symbol)

    return MLPortfolioEvaluationResult(
        symbols=symbols,
        splits=splits,
        skipped=skipped,
        per_symbol=per_symbol,
        aggregate_model=aggregate_model,
        aggregate_baselines=aggregate_baselines,
        significance=significance,
        beats_all_baselines=beats_all,
        reasons=reasons,
    )


def _reasons(
    splits: list[PortfolioSplitResult],
    skipped: list[SkippedSplit],
    beats: Mapping[str, bool],
    beats_all: bool,
    per_symbol: Sequence[SymbolOOSBreakdown],
) -> list[str]:
    """Short, auditable notes: split coverage, baseline beats, and single-asset
    dependence (does one symbol carry the whole positive contribution?)."""
    reasons: list[str] = []
    if not splits:
        reasons.append(
            "No non-skipped splits — too little history or every fold degenerate; "
            "no portfolio verdict."
        )
        return reasons
    reasons.append(f"{len(splits)} split(s) evaluated, {len(skipped)} skipped.")
    for name, won in beats.items():
        reasons.append(f"beats_{name}: {'PASS' if won else 'FAIL'}")
    reasons.append(
        "beats_all_baselines: " + ("PASS" if beats_all else "FAIL")
    )
    positive = [b for b in per_symbol if b.contribution_pct > 0.0]
    total_positive = sum(b.contribution_pct for b in positive)
    if total_positive > 0.0 and positive:
        top = max(positive, key=lambda b: b.contribution_pct)
        share = top.contribution_pct / total_positive
        if share > 0.8:
            reasons.append(
                f"single-asset dependence: {top.symbol} supplies "
                f"{share * 100:.0f}% of the positive OOS contribution."
            )
    return reasons
