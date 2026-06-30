"""Walk-forward, train-then-test out-of-sample evaluation for the ML strategy (M3b).

This is the honest verdict of Phase 4: per walk-forward split a fresh model is
trained on the in-sample window and scored, net of costs, on the strictly-later
held-out window through the SAME execution engine every other strategy uses. The
model is then compared to four baselines on the identical window, and the whole
battery is run through the §8 significance statistics (deflated Sharpe, PBO, a
Monte-Carlo random ensemble) to decide pass / fail / inconclusive.

Why this shape:

- **No reimplementation of execution or metrics.** Each strategy (model and every
  baseline) is driven through ``run_backtest`` on the very same OOS frame with the
  same fee/slippage, then scored with ``compute_metrics``. Next-bar-open fills and
  final-bar force-close come for free and stay consistent across strategies.

- **No look-ahead.** The purged splitter keys the train/test boundary to a single
  calendar date and purges training labels that reach into the held-out window. The
  OOS engine frame is sliced from the per-symbol frame strictly to the test
  calendar window, so it begins after the training window ends. Each split records
  its first OOS timestamp and the training-window end so the property is auditable.

- **Uniqueness-adjusted track length.** Overlapping H-day labels over-count, so the
  deflated Sharpe's track length is the effective sample size of the eval symbol's
  OOS rows (sum of Lopez de Prado uniqueness weights), not the raw bar count.

Pure logic, DB-free. The result carries a ``to_dict`` of plain JSON-serializable
types so M4 can persist it and M5 can render it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.backtesting.engine import BacktestResult, run_backtest
from app.backtesting.metrics import Metrics, compute_metrics
from app.ml.features import (
    COL_DECISION_TS,
    COL_LABEL,
    COL_SYMBOL,
    COL_WEIGHT,
    effective_sample_size,
)
from app.ml.model import TrainedModel
from app.ml.significance import (
    deflated_sharpe_ratio,
    pbo_cscv,
    returns_moments,
    verdict,
)
from app.ml.training import (
    TrainingConfig,
    TrainingError,
    train_model,
)
from app.strategies.base_strategy import (
    BaseStrategy,
    Position,
    StrategyDecision,
    StrategySignal,
)
from app.strategies.ml_classifier import MLClassifierStrategy
from app.strategies.trend_following import TrendFollowingStrategy

# Baseline keys, exported so M4/M5 reference names rather than string literals.
BASE_BUY_AND_HOLD = "buy_and_hold"
BASE_RULE = "rule"
BASE_LOGISTIC = "logistic_floor"
BASE_MC = "monte_carlo_ensemble"

# How many Monte-Carlo ensemble members contribute per-bar return columns to the
# PBO performance matrix. The full ensemble feeds the MC percentile; only a small
# sample feeds PBO so the candidate set stays a handful of comparable strategies.
_PBO_MC_SAMPLE = 4

# Factors used by ``default_n_config_trials`` to enumerate the effective search space.
# Each constant is a conservative documented lower bound; override the trial count at
# call time with the true search size if the actual hyperparameter sweep was larger.
#
# _N_LGBM_GRID: 4 commonly-tuned LightGBM knobs (n_estimators, num_leaves,
#     min_child_samples, learning_rate) × 2 candidate values each = 16 grid points.
#     Any real sweep will exceed this.
_N_LGBM_GRID: int = 16
# _N_HORIZON: at minimum two horizon choices typically evaluated (5-day, 10-day)
#     before selecting one for the reported model.
_N_HORIZON: int = 2
# _N_DEADBAND: at minimum three label deadband/threshold values evaluated (0 %,
#     0.5 %, 1 %) before selection; on/off alone understates the real search.
_N_DEADBAND: int = 3

# Logistic floor: enough iterations to converge on standardized features.
_LOGISTIC_MAX_ITER = 1_000

_PERIODS_PER_YEAR = 252.0


# ---------------------------------------------------------------------------
# Result types (frozen, serializable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyScore:
    """One strategy's OOS result on a single split.

    ``per_bar_returns`` are the equity curve's per-bar simple returns; they feed
    the aggregate moments and the PBO matrix. ``turnover_annualized`` exposes the
    cost intensity so a model whose edge vanishes under turnover is visible.
    """

    name: str
    metrics: Metrics
    turnover_annualized: float
    total_return_pct: float
    oos_round_trips: int
    per_bar_returns: tuple[float, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "metrics": asdict(self.metrics),
            "turnover_annualized": float(self.turnover_annualized),
            "total_return_pct": float(self.total_return_pct),
            "oos_round_trips": int(self.oos_round_trips),
            "per_bar_returns": [float(r) for r in self.per_bar_returns],
        }


@dataclass(frozen=True)
class SplitResult:
    """Everything scored for one non-skipped walk-forward split."""

    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_end: pd.Timestamp
    oos_first_ts: pd.Timestamp
    n_oos_bars: int
    model: StrategyScore
    baselines: dict[str, StrategyScore]
    mc_returns: tuple[float, ...]  # total_return_pct of every MC ensemble run
    mc_sample_per_bar: tuple[tuple[float, ...], ...]  # per-bar returns, PBO sample
    mc_mean_turnover: float  # mean annualized turnover of the MC ensemble on this split
    classification: dict[str, float]  # auc, brier (nan when single-class)
    beats: dict[str, bool]

    def no_look_ahead(self) -> bool:
        """True iff every OOS bar is strictly after the training window end."""
        return pd.Timestamp(self.oos_first_ts) > pd.Timestamp(self.train_end)

    def to_dict(self) -> dict[str, object]:
        return {
            "test_start": str(self.test_start),
            "test_end": str(self.test_end),
            "train_end": str(self.train_end),
            "oos_first_ts": str(self.oos_first_ts),
            "n_oos_bars": int(self.n_oos_bars),
            "no_look_ahead": bool(self.no_look_ahead()),
            "model": self.model.to_dict(),
            "baselines": {k: v.to_dict() for k, v in self.baselines.items()},
            "mc_returns": [float(r) for r in self.mc_returns],
            "mc_mean_turnover": float(self.mc_mean_turnover),
            "classification": {k: float(v) for k, v in self.classification.items()},
            "beats": {k: bool(v) for k, v in self.beats.items()},
        }


@dataclass(frozen=True)
class SkippedSplit:
    """A split skipped because the model could not be trained (e.g. single class)."""

    test_start: pd.Timestamp
    test_end: pd.Timestamp
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "test_start": str(self.test_start),
            "test_end": str(self.test_end),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SignificanceBlock:
    """The §8 statistics behind the verdict."""

    sharpe: float       # per-period (raw mean/std) over concatenated OOS bars
    skew: float
    kurtosis: float     # non-excess (3.0 for a Gaussian)
    n_obs: int          # raw concatenated OOS bar count
    n_eff: float        # uniqueness-adjusted effective sample size (DSR track length)
    var_trial_sharpes: float
    deflated_sharpe: float
    pbo: float
    mc_percentile: float
    n_config_trials: int
    n_oos_round_trips: int

    def to_dict(self) -> dict[str, object]:
        return {
            "sharpe": float(self.sharpe),
            "skew": float(self.skew),
            "kurtosis": float(self.kurtosis),
            "n_obs": int(self.n_obs),
            "n_eff": float(self.n_eff),
            "var_trial_sharpes": float(self.var_trial_sharpes),
            "deflated_sharpe": float(self.deflated_sharpe),
            "pbo": float(self.pbo),
            "mc_percentile": float(self.mc_percentile),
            "n_config_trials": int(self.n_config_trials),
            "n_oos_round_trips": int(self.n_oos_round_trips),
        }


@dataclass(frozen=True)
class MLEvaluationResult:
    """The complete walk-forward verdict for one evaluated symbol."""

    eval_symbol: str
    splits: list[SplitResult]
    skipped: list[SkippedSplit]
    aggregate_model: dict[str, float]
    aggregate_baselines: dict[str, dict[str, float]]
    significance: SignificanceBlock
    verdict: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "eval_symbol": self.eval_symbol,
            "splits": [s.to_dict() for s in self.splits],
            "skipped": [s.to_dict() for s in self.skipped],
            "aggregate_model": {k: float(v) for k, v in self.aggregate_model.items()},
            "aggregate_baselines": {
                name: {k: float(v) for k, v in m.items()}
                for name, m in self.aggregate_baselines.items()
            },
            "significance": self.significance.to_dict(),
            "verdict": self.verdict,
            "reasons": list(self.reasons),
        }


# ---------------------------------------------------------------------------
# Helper strategies (baselines that the engine drives identically to the model)
# ---------------------------------------------------------------------------


class _BuyAndHoldStrategy(BaseStrategy):
    """Enter on the first bar, never voluntarily exit; the engine force-closes the
    open position on the final bar. One entry + one exit, charged like any trade —
    so buy-and-hold pays the same single round-trip cost the model would."""

    name = BASE_BUY_AND_HOLD

    def generate_signal(
        self, row: pd.Series, current_position: Position
    ) -> StrategyDecision:
        if not current_position.is_open:
            return StrategyDecision(
                action=StrategySignal.BUY, reason="Buy and hold."
            )
        return StrategyDecision(action=StrategySignal.HOLD, reason="Holding.")


class _FlatStrategy(BaseStrategy):
    """Never trades — a do-nothing fallback so a degenerate baseline is still present
    and comparable (flat equity, zero round trips) rather than missing."""

    name = "flat"

    def generate_signal(
        self, row: pd.Series, current_position: Position
    ) -> StrategyDecision:
        return StrategyDecision(action=StrategySignal.HOLD, reason="Flat.")


class _RandomLongFlatStrategy(BaseStrategy):
    """A seeded random long/flat benchmark tuned to the model's in-market fraction.

    While flat it enters long with probability ``p``; once long it must hold at
    least ``min_hold`` bars (matching the model's holding discipline), after which
    it exits with probability ``1 - p``. This reproduces a comparable trade
    frequency and in-market fraction by chance alone — the null the model must beat.
    It is a heuristic match (not an exact stationary solve), which is sufficient for
    a random ensemble.
    """

    name = "random_long_flat"

    def __init__(self, p: float, min_hold: int, seed: int) -> None:
        self._p = float(min(1.0, max(0.0, p)))
        self._min_hold = int(max(0, min_hold))
        self._rng = np.random.default_rng(seed)
        self._bars_held = 0

    def generate_signal(
        self, row: pd.Series, current_position: Position
    ) -> StrategyDecision:
        self._bars_held = self._bars_held + 1 if current_position.is_open else 0
        if not current_position.is_open:
            if self._rng.random() < self._p:
                return StrategyDecision(action=StrategySignal.BUY, reason="Random enter.")
            return StrategyDecision(action=StrategySignal.HOLD, reason="Random flat.")
        if self._bars_held >= self._min_hold and self._rng.random() >= self._p:
            return StrategyDecision(action=StrategySignal.SELL, reason="Random exit.")
        return StrategyDecision(action=StrategySignal.HOLD, reason="Random hold.")


def _logistic_factory(config: TrainingConfig) -> Pipeline:
    """Standardize then logistic-regress: the 'more-parameters' floor.

    The scaler is part of the pipeline so it is fit ONLY on the training fold the
    trainer passes in — no out-of-sample statistics leak into standardization.
    """
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=_LOGISTIC_MAX_ITER, random_state=config.seed
                ),
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------


def _per_bar_returns(result: BacktestResult) -> np.ndarray:
    """Per-bar simple returns of an equity curve (length n_bars - 1)."""
    eq = np.array([p.equity for p in result.equity_curve], dtype=float)
    if eq.size < 2:
        return np.empty(0, dtype=float)
    prev = eq[:-1]
    out = np.where(prev != 0.0, np.diff(eq) / np.where(prev == 0.0, 1.0, prev), 0.0)
    return out


def _turnover_annualized(result: BacktestResult) -> float:
    """Annualized gross traded notional over mean equity.

    ``sum(|gross_value|) / mean_equity / years`` with ``years = n_bars / 252``.
    Guarded against empty curves and non-positive mean equity.
    """
    eq = [p.equity for p in result.equity_curve]
    n_bars = len(eq)
    if n_bars == 0:
        return 0.0
    mean_equity = float(np.mean(eq))
    years = n_bars / _PERIODS_PER_YEAR
    if mean_equity <= 0.0 or years <= 0.0:
        return 0.0
    gross = float(sum(abs(t.gross_value) for t in result.trades))
    return gross / mean_equity / years


def _score(name: str, result: BacktestResult, initial_capital: float) -> StrategyScore:
    metrics = compute_metrics(result.equity_curve, result.trades, initial_capital)
    return StrategyScore(
        name=name,
        metrics=metrics,
        turnover_annualized=_turnover_annualized(result),
        total_return_pct=float(result.total_return_pct),
        oos_round_trips=int(metrics.num_round_trips),
        per_bar_returns=tuple(float(r) for r in _per_bar_returns(result)),
    )


def _compound(returns_pct: Sequence[float]) -> float:
    """Compound a sequence of per-split percentage returns into one total return %."""
    growth = 1.0
    for r in returns_pct:
        growth *= 1.0 + r / 100.0
    return (growth - 1.0) * 100.0


def default_n_config_trials(config: TrainingConfig) -> int:
    """Documented default for the deflated-Sharpe trial count N (§8).

    N counts the effective number of configurations a researcher searched, so the
    DSR raises the false-discovery bar accordingly. The default enumerates every
    axis of the documented search space and is a FLOOR, not the real search size —
    any production hyperparameter sweep will exceed it. Always override with the
    true search size when reporting persisted results.

    Factors (all are module-level constants so callers reference names, not numbers):

    - enter-threshold grid: ``len(enter grid)`` candidates,
    - deadband on/off: x2,
    - hysteresis gap chosen/not: x2,
    - min-hold chosen/not: x2,
    - uniqueness weighting on/off: x2,
    - LightGBM hyperparameter grid: x``_N_LGBM_GRID``
      (4 knobs × 2 candidate values each — conservative floor; a real sweep is larger),
    - forecast horizon choices: x``_N_HORIZON``
      (e.g. 5-day vs 10-day, evaluated before selecting one),
    - label deadband/threshold choices: x``_N_DEADBAND``
      (3 values — understating on/off alone is too optimistic).

    So ``N = enter_grid_size * 16 * _N_LGBM_GRID * _N_HORIZON * _N_DEADBAND``.
    """
    grid = np.arange(
        config.enter_grid_lo,
        config.enter_grid_hi + 1e-9,
        config.enter_grid_step,
    )
    enter_grid_size = max(1, int(grid.size))
    return enter_grid_size * 16 * _N_LGBM_GRID * _N_HORIZON * _N_DEADBAND


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------


def evaluate_ml_walk_forward(
    panel: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    *,
    eval_symbol: str,
    training_config: TrainingConfig | None = None,
    horizon: int = 5,
    embargo: int | None = None,
    in_sample_dates: int = 504,
    out_sample_dates: int = 126,
    step_dates: int = 126,
    scheme: str = "anchored",
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    initial_capital: float = 100_000.0,
    n_config_trials: int | None = None,
    mc_runs: int = 200,
    seed: int = 42,
) -> MLEvaluationResult:
    """Train a fresh model per purged split, score it OOS against four baselines,
    and return the full significance verdict.

    ``panel`` is the pooled feature/label matrix (``build_pooled_panel``). ``frames``
    maps each symbol to its featured frame (OHLCV + indicators + ``f_*`` features);
    only ``frames[eval_symbol]`` is driven through the engine — M3 is
    single-symbol-first. A split whose model cannot be trained (e.g. a single-class
    in-sample fold) is recorded as skipped, never fatal.
    """
    from app.evaluation.walk_forward import generate_purged_splits

    # Guard overlapping OOS windows: when step_dates < out_sample_dates consecutive
    # test windows overlap, which would double-count OOS bars in the aggregate and
    # inflate performance metrics. Disjoint windows require step >= out_sample_dates.
    if step_dates < out_sample_dates:
        raise ValueError(
            f"step_dates={step_dates} < out_sample_dates={out_sample_dates}: "
            "overlapping test windows would double-count OOS bars and inflate the "
            "aggregate. Set step_dates >= out_sample_dates for disjoint windows."
        )

    training_config = training_config or TrainingConfig()
    if n_config_trials is None:
        n_config_trials = default_n_config_trials(training_config)

    if eval_symbol not in frames:
        raise ValueError(f"eval_symbol {eval_symbol!r} not in frames.")

    eval_frame = frames[eval_symbol]
    feat_cols = list(training_config.spec.feature_columns)

    splits = generate_purged_splits(
        panel,
        horizon=horizon,
        embargo=embargo,
        scheme=scheme,
        in_sample_dates=in_sample_dates,
        out_sample_dates=out_sample_dates,
        step_dates=step_dates,
    )

    # Logistic floor reuses the exact purged training pipeline; calibration off so the
    # wrapped classifier IS the scaler+logistic pipeline (its scaler fit on training
    # only), which the leakage test inspects directly.
    logistic_config = TrainingConfig(
        spec=training_config.spec,
        seed=training_config.seed,
        fit_fraction=training_config.fit_fraction,
        calib_fraction=training_config.calib_fraction,
        calibration="none",
        cost_bps=training_config.cost_bps,
        hysteresis_gap=training_config.hysteresis_gap,
        enter_grid_lo=training_config.enter_grid_lo,
        enter_grid_hi=training_config.enter_grid_hi,
        enter_grid_step=training_config.enter_grid_step,
        min_selected=training_config.min_selected,
        min_hold=training_config.min_hold,
        estimator_factory=_logistic_factory,
    )

    split_results: list[SplitResult] = []
    skipped: list[SkippedSplit] = []
    # Accumulates the eval symbol's OOS rows (for the effective sample size).
    oos_panel_mask = np.zeros(len(panel), dtype=bool)
    decision_np = panel[COL_DECISION_TS].to_numpy() if len(panel) else np.empty(0)
    symbol_np = panel[COL_SYMBOL].to_numpy() if len(panel) else np.empty(0)

    for split in splits:
        try:
            train_result = train_model(
                panel, split.train_idx, config=training_config
            )
        except TrainingError as exc:
            skipped.append(
                SkippedSplit(
                    test_start=split.test_start,
                    test_end=split.test_end,
                    reason=str(exc),
                )
            )
            continue

        model = train_result.model
        oos_frame = _slice_oos(eval_frame, split.test_start, split.test_end)
        if len(oos_frame) < 2:
            skipped.append(
                SkippedSplit(
                    test_start=split.test_start,
                    test_end=split.test_end,
                    reason="Out-of-sample window has fewer than 2 bars.",
                )
            )
            continue

        # --- Model ---
        model_res = run_backtest(
            oos_frame,
            MLClassifierStrategy.from_model(model),
            symbol=eval_symbol,
            initial_capital=initial_capital,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        model_score = _score("model", model_res, initial_capital)

        # --- Baselines on the identical window/costs ---
        bh_res = run_backtest(
            oos_frame, _BuyAndHoldStrategy(), symbol=eval_symbol,
            initial_capital=initial_capital, fee_bps=fee_bps, slippage_bps=slippage_bps,
        )
        rule_res = run_backtest(
            oos_frame, TrendFollowingStrategy(), symbol=eval_symbol,
            initial_capital=initial_capital, fee_bps=fee_bps, slippage_bps=slippage_bps,
        )
        log_score = _logistic_score(
            panel, split.train_idx, oos_frame, eval_symbol, logistic_config,
            initial_capital, fee_bps, slippage_bps,
        )

        baselines: dict[str, StrategyScore] = {
            BASE_BUY_AND_HOLD: _score(BASE_BUY_AND_HOLD, bh_res, initial_capital),
            BASE_RULE: _score(BASE_RULE, rule_res, initial_capital),
            BASE_LOGISTIC: log_score,
        }

        # --- Monte-Carlo random ensemble at the model's in-market fraction ---
        p = float(model_score.metrics.exposure_pct) / 100.0
        mc_returns, mc_sample, mc_mean_turn = _monte_carlo_ensemble(
            oos_frame, eval_symbol, p, model.min_hold, mc_runs, seed,
            initial_capital, fee_bps, slippage_bps,
        )

        beats = {
            BASE_BUY_AND_HOLD: model_score.total_return_pct
            > baselines[BASE_BUY_AND_HOLD].total_return_pct,
            BASE_RULE: model_score.total_return_pct
            > baselines[BASE_RULE].total_return_pct,
            BASE_LOGISTIC: model_score.total_return_pct
            > baselines[BASE_LOGISTIC].total_return_pct,
        }

        classification = _classification_metrics(
            model, panel, eval_symbol, split.test_start, split.test_end, feat_cols
        )

        oos_first_ts = pd.Timestamp(oos_frame["timestamp"].iloc[0])
        split_results.append(
            SplitResult(
                test_start=split.test_start,
                test_end=split.test_end,
                train_end=train_result.train_end,
                oos_first_ts=oos_first_ts,
                n_oos_bars=int(len(oos_frame)),
                model=model_score,
                baselines=baselines,
                mc_returns=tuple(float(r) for r in mc_returns),
                mc_sample_per_bar=tuple(tuple(r) for r in mc_sample),
                mc_mean_turnover=mc_mean_turn,
                classification=classification,
                beats=beats,
            )
        )

        if len(panel):
            window_mask = (
                (symbol_np == eval_symbol)
                & (decision_np >= np.datetime64(split.test_start))
                & (decision_np <= np.datetime64(split.test_end))
            )
            oos_panel_mask |= window_mask

    n_eff = (
        effective_sample_size(panel.loc[oos_panel_mask, COL_WEIGHT])
        if oos_panel_mask.any()
        else 0.0
    )

    return _aggregate(
        eval_symbol=eval_symbol,
        splits=split_results,
        skipped=skipped,
        n_eff=n_eff,
        n_config_trials=n_config_trials,
    )


def _slice_oos(
    frame: pd.DataFrame, test_start: pd.Timestamp, test_end: pd.Timestamp
) -> pd.DataFrame:
    """Contiguous rows of ``frame`` whose timestamp falls in [start, end] inclusive.

    The slice never crosses the training boundary: the splitter guarantees
    ``test_start`` is strictly later than every training date, and this keeps only
    rows at or after ``test_start``.
    """
    ts = frame["timestamp"]
    mask = (ts >= test_start) & (ts <= test_end)
    return frame.loc[mask].reset_index(drop=True)


def _logistic_score(
    panel: pd.DataFrame,
    train_idx: np.ndarray,
    oos_frame: pd.DataFrame,
    eval_symbol: str,
    logistic_config: TrainingConfig,
    initial_capital: float,
    fee_bps: float,
    slippage_bps: float,
) -> StrategyScore:
    """Train the logistic floor through the purged pipeline and score it OOS.

    If the floor cannot be trained on this fold (the same single-class condition
    that would have skipped the whole split), it scores as a flat, never-traded
    strategy so the baseline is still present and comparable.
    """
    try:
        log_result = train_model(panel, train_idx, config=logistic_config)
    except TrainingError:
        # Degenerate fold: score a do-nothing strategy (zero return, no trades).
        flat = run_backtest(
            oos_frame, _FlatStrategy(), symbol=eval_symbol,
            initial_capital=initial_capital, fee_bps=fee_bps, slippage_bps=slippage_bps,
        )
        return _score(BASE_LOGISTIC, flat, initial_capital)
    log_res = run_backtest(
        oos_frame,
        MLClassifierStrategy.from_model(log_result.model),
        symbol=eval_symbol,
        initial_capital=initial_capital,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    return _score(BASE_LOGISTIC, log_res, initial_capital)


def _monte_carlo_ensemble(
    oos_frame: pd.DataFrame,
    eval_symbol: str,
    p: float,
    min_hold: int,
    mc_runs: int,
    seed: int,
    initial_capital: float,
    fee_bps: float,
    slippage_bps: float,
) -> tuple[list[float], list[tuple[float, ...]], float]:
    """Run ``mc_runs`` seeded random long/flat strategies on the OOS frame.

    Returns:
    - each run's total return %,
    - for the first ``_PBO_MC_SAMPLE`` runs its per-bar return series (so PBO sees
      a few random columns alongside the real candidates),
    - the mean annualized turnover of the full MC ensemble (so a reviewer can check
      whether an MC win is cost-driven — the random null churning more than the model
      inflates MC returns relative to a low-turnover model).
    """
    returns: list[float] = []
    sample: list[tuple[float, ...]] = []
    turnovers: list[float] = []
    for run in range(mc_runs):
        strat = _RandomLongFlatStrategy(p=p, min_hold=min_hold, seed=seed + run)
        res = run_backtest(
            oos_frame, strat, symbol=eval_symbol, initial_capital=initial_capital,
            fee_bps=fee_bps, slippage_bps=slippage_bps,
        )
        returns.append(float(res.total_return_pct))
        turnovers.append(_turnover_annualized(res))
        if run < _PBO_MC_SAMPLE:
            sample.append(tuple(float(r) for r in _per_bar_returns(res)))
    mc_mean_turnover = float(np.mean(turnovers)) if turnovers else 0.0
    return returns, sample, mc_mean_turnover


def _classification_metrics(
    model: TrainedModel,
    panel: pd.DataFrame,
    eval_symbol: str,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    feat_cols: list[str],
) -> dict[str, float]:
    """AUC and Brier of ``predict_proba_up`` vs the 0/1 label on the eval symbol's
    OOS panel rows. Diagnostics only — never part of the verdict. Single-class or
    empty windows return nan (the metrics are undefined there)."""
    mask = (
        (panel[COL_SYMBOL] == eval_symbol)
        & (panel[COL_DECISION_TS] >= test_start)
        & (panel[COL_DECISION_TS] <= test_end)
    )
    rows = panel.loc[mask]
    if rows.empty:
        return {"auc": float("nan"), "brier": float("nan")}
    y = rows[COL_LABEL].astype(int).to_numpy()
    if len(np.unique(y)) < 2:
        return {"auc": float("nan"), "brier": float("nan")}
    proba = model.predict_proba_up(rows[feat_cols])
    return {
        "auc": float(roc_auc_score(y, proba)),
        "brier": float(brier_score_loss(y, proba)),
    }


# ---------------------------------------------------------------------------
# Aggregation across splits
# ---------------------------------------------------------------------------


def _aggregate(
    *,
    eval_symbol: str,
    splits: list[SplitResult],
    skipped: list[SkippedSplit],
    n_eff: float,
    n_config_trials: int,
) -> MLEvaluationResult:
    """Roll the per-split scores up into the significance battery and the verdict."""
    # Concatenated, time-ordered model OOS per-bar returns.
    model_bars = np.concatenate(
        [np.asarray(s.model.per_bar_returns, dtype=float) for s in splits]
    ) if splits else np.empty(0, dtype=float)
    moments = returns_moments(model_bars)

    # Dispersion across folds: each split's per-period model Sharpe (same basis as
    # the aggregate sharpe) — the trial dispersion the deflation needs.
    per_split_sharpes = [
        returns_moments(np.asarray(s.model.per_bar_returns, dtype=float)).sharpe
        for s in splits
    ]
    if len(per_split_sharpes) >= 2:
        var_trial = float(np.var(np.asarray(per_split_sharpes), ddof=1))
    else:
        var_trial = 0.0

    # Floor the cross-split variance with the Lo (2002) sampling variance of the
    # per-period Sharpe estimator under the false-strategy null:
    #
    #   sharpe_sampling_var = (1 + 0.5 * SR²) / n_eff
    #
    # This ensures the DSR multiple-testing correction never silently vanishes when
    # cross-split dispersion is ~0 (e.g. single split, or all splits return the same
    # Sharpe). Without this floor, var_trial = 0 → expected_max_sharpe = 0 →
    # DSR collapses to PSR(benchmark=0), erasing the entire correction and potentially
    # flipping a fail to a pass. Guard n_eff_floor >= 1 to avoid division by zero.
    n_eff_floor = max(1.0, n_eff)
    sharpe_sampling_var = (1.0 + 0.5 * moments.sharpe ** 2) / n_eff_floor
    var_trial = max(var_trial, sharpe_sampling_var)

    # Track length = the uniqueness-adjusted effective sample size, rounded to an
    # integer count (overlapping H-day labels over-count the raw bar total). PSR's
    # finite-track correction takes an integer observation count.
    n_track = int(round(n_eff))
    dsr = deflated_sharpe_ratio(
        moments.sharpe,
        n_track,
        moments.skew,
        moments.kurtosis,
        n_trials=n_config_trials,
        variance_of_trial_sharpes=var_trial,
    )

    pbo = _pbo(splits)

    # Aggregate compounded total returns.
    agg_model_ret = _compound([s.model.total_return_pct for s in splits])
    agg_bh = _compound([s.baselines[BASE_BUY_AND_HOLD].total_return_pct for s in splits])
    agg_rule = _compound([s.baselines[BASE_RULE].total_return_pct for s in splits])
    agg_log = _compound([s.baselines[BASE_LOGISTIC].total_return_pct for s in splits])

    mc_percentile = _mc_percentile(splits, agg_model_ret)

    n_oos_round_trips = int(sum(s.model.oos_round_trips for s in splits))

    beats_bh = agg_model_ret > agg_bh
    beats_rule = agg_model_ret > agg_rule
    beats_log = agg_model_ret > agg_log

    # Per-baseline per-split WIN COUNTS: how many non-skipped splits the model
    # beat each baseline. The aggregate beats-test can be carried by one outsized
    # split; these counts make that auditable (M5 renders them for visibility).
    splits_beating_bh = sum(1 for s in splits if s.beats.get(BASE_BUY_AND_HOLD, False))
    splits_beating_rule = sum(1 for s in splits if s.beats.get(BASE_RULE, False))
    splits_beating_log = sum(1 for s in splits if s.beats.get(BASE_LOGISTIC, False))
    n_splits_evaluated = len(splits)

    # MC ensemble mean turnover: placed alongside the model's mean turnover so a
    # reviewer can detect cost-driven MC wins (random null churning more than a
    # low-turnover model inflates MC returns relative to the model).
    mc_mean_turn_agg = float(
        np.mean([s.mc_mean_turnover for s in splits]) if splits else 0.0
    )

    decision = verdict(
        beats_buy_and_hold=beats_bh,
        beats_rule=beats_rule,
        beats_logistic=beats_log,
        mc_percentile=mc_percentile,
        deflated_sharpe=dsr,
        pbo=pbo,
        n_oos_trades=n_oos_round_trips,
    )

    significance = SignificanceBlock(
        sharpe=moments.sharpe,
        skew=moments.skew,
        kurtosis=moments.kurtosis,
        n_obs=int(model_bars.size),
        n_eff=float(n_eff),
        var_trial_sharpes=var_trial,
        deflated_sharpe=dsr,
        pbo=pbo,
        mc_percentile=mc_percentile,
        n_config_trials=int(n_config_trials),
        n_oos_round_trips=n_oos_round_trips,
    )

    aggregate_model = {
        "total_return_pct": agg_model_ret,
        "per_period_sharpe": moments.sharpe,
        "num_oos_round_trips": float(n_oos_round_trips),
        "mean_turnover_annualized": float(
            np.mean([s.model.turnover_annualized for s in splits]) if splits else 0.0
        ),
        "mc_mean_turnover_annualized": mc_mean_turn_agg,
        "beats_buy_and_hold": float(beats_bh),
        "beats_rule": float(beats_rule),
        "beats_logistic": float(beats_log),
        # Per-split win counts: how many of the n_splits_evaluated non-skipped
        # splits the model beat each baseline. Use these to detect an outsized
        # single-split carry in the aggregate beats.
        "splits_beating_buy_and_hold": float(splits_beating_bh),
        "splits_beating_rule": float(splits_beating_rule),
        "splits_beating_logistic": float(splits_beating_log),
        "n_splits_evaluated": float(n_splits_evaluated),
    }
    aggregate_baselines = {
        BASE_BUY_AND_HOLD: _aggregate_baseline(splits, BASE_BUY_AND_HOLD, agg_bh),
        BASE_RULE: _aggregate_baseline(splits, BASE_RULE, agg_rule),
        BASE_LOGISTIC: _aggregate_baseline(splits, BASE_LOGISTIC, agg_log),
    }

    return MLEvaluationResult(
        eval_symbol=eval_symbol,
        splits=splits,
        skipped=skipped,
        aggregate_model=aggregate_model,
        aggregate_baselines=aggregate_baselines,
        significance=significance,
        verdict=decision.verdict,
        reasons=decision.reasons,
    )


def _aggregate_baseline(
    splits: list[SplitResult], name: str, agg_total: float
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


def _mc_percentile(splits: list[SplitResult], agg_model_ret: float) -> float:
    """Fraction of MC ensemble runs whose aggregate OOS return the model beats.

    A run's aggregate return compounds that run index's per-split total returns, so
    the model is placed at its percentile of the random ensemble. Returns nan when
    no MC runs exist.
    """
    if not splits:
        return float("nan")
    n_runs = min(len(s.mc_returns) for s in splits)
    if n_runs == 0:
        return float("nan")
    agg_runs = np.empty(n_runs, dtype=float)
    for r in range(n_runs):
        agg_runs[r] = _compound([s.mc_returns[r] for s in splits])
    return float(np.mean(agg_model_ret > agg_runs))


def _pbo(splits: list[SplitResult]) -> float:
    """Build the per-observation performance matrix and run CSCV.

    Columns: model, rule, logistic_floor, buy_and_hold, plus a sample of MC members.
    Rows: the concatenated OOS per-bar returns shared by every candidate (all run on
    the same OOS frame each split, so their series align bar-for-bar). Returns nan
    when there is too little data for the test.
    """
    if not splits:
        return float("nan")

    columns: list[np.ndarray] = []

    def _concat(selector) -> np.ndarray:
        return np.concatenate(
            [np.asarray(selector(s), dtype=float) for s in splits]
        )

    columns.append(_concat(lambda s: s.model.per_bar_returns))
    columns.append(_concat(lambda s: s.baselines[BASE_RULE].per_bar_returns))
    columns.append(_concat(lambda s: s.baselines[BASE_LOGISTIC].per_bar_returns))
    columns.append(_concat(lambda s: s.baselines[BASE_BUY_AND_HOLD].per_bar_returns))

    # MC sample members. A member is included only if every split produced a
    # same-length per-bar series for it (so the column aligns with the others).
    n_mc = min((len(s.mc_sample_per_bar) for s in splits), default=0)
    for m in range(n_mc):
        try:
            col = np.concatenate(
                [np.asarray(s.mc_sample_per_bar[m], dtype=float) for s in splits]
            )
        except ValueError:
            continue
        if col.size == columns[0].size:
            columns.append(col)

    lengths = {c.size for c in columns}
    if len(lengths) != 1 or columns[0].size == 0:
        return float("nan")

    matrix = np.column_stack(columns)
    return pbo_cscv(matrix).pbo
