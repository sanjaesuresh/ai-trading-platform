"""ML classifier strategy: decision logic, hysteresis, min-hold, engine integration."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.engine import run_backtest
from app.data.feature_engineering import add_technical_indicators
from app.ml.features import FEATURE_COLUMNS, FeatureLabelSpec, build_features, build_pooled_panel
from app.ml.model import TrainedModel
from app.ml.training import TrainingConfig, train_model
from app.strategies.base_strategy import Position, StrategySignal
from app.strategies.ml_classifier import MLClassifierStrategy
from app.strategies.registry import available_strategies

HORIZON = 5


class _StubClassifier:
    """Deterministic classifier: P(up) is the first feature value, clipped to [0,1]."""

    classes_ = np.array([0, 1])

    def predict_proba(self, features) -> np.ndarray:
        arr = np.asarray(features, dtype=float)
        p = np.clip(arr[:, 0], 0.0, 1.0)
        return np.column_stack([1.0 - p, p])


def _stub_model(enter: float = 0.6, exit_: float = 0.55, min_hold: int = 3) -> TrainedModel:
    return TrainedModel(
        classifier=_StubClassifier(),
        spec=FeatureLabelSpec(horizon=HORIZON, deadband=0.0),
        enter_threshold=enter,
        exit_threshold=exit_,
        min_hold=min_hold,
        calibrated=False,
    )


def _row(prob: float) -> pd.Series:
    # First feature carries the probability proxy for the stub; the rest are zero.
    data = dict.fromkeys(FEATURE_COLUMNS, 0.0)
    data[FEATURE_COLUMNS[0]] = prob
    return pd.Series(data)


def test_ml_classifier_is_registered() -> None:
    assert "ml_classifier" in available_strategies()


def test_enters_long_when_probability_clears_enter() -> None:
    strat = MLClassifierStrategy.from_model(_stub_model())
    decision = strat.generate_signal(_row(0.7), Position())
    assert decision.action == StrategySignal.BUY


def test_stays_flat_below_enter() -> None:
    strat = MLClassifierStrategy.from_model(_stub_model())
    decision = strat.generate_signal(_row(0.5), Position())
    assert decision.action == StrategySignal.HOLD


def test_min_hold_blocks_early_exit_then_allows_it() -> None:
    strat = MLClassifierStrategy.from_model(_stub_model(min_hold=3))
    pos = Position(quantity=1.0, entry_price=100.0)
    # Probability below exit the whole time, but min-hold must gate the first bars.
    assert strat.generate_signal(_row(0.1), pos).action == StrategySignal.HOLD  # held 1
    assert strat.generate_signal(_row(0.1), pos).action == StrategySignal.HOLD  # held 2
    assert strat.generate_signal(_row(0.1), pos).action == StrategySignal.SELL  # held 3


def test_holds_above_exit_even_after_min_hold() -> None:
    strat = MLClassifierStrategy.from_model(_stub_model(enter=0.6, exit_=0.55))
    pos = Position(quantity=1.0, entry_price=100.0)
    for _ in range(5):
        decision = strat.generate_signal(_row(0.8), pos)  # 0.8 >= exit 0.55
    assert decision.action == StrategySignal.HOLD


def test_warmup_nan_features_hold() -> None:
    strat = MLClassifierStrategy.from_model(_stub_model())
    row = _row(0.9)
    row[FEATURE_COLUMNS[1]] = np.nan
    assert strat.generate_signal(row, Position()).action == StrategySignal.HOLD


def test_missing_feature_column_raises() -> None:
    strat = MLClassifierStrategy.from_model(_stub_model())
    row = _row(0.9).drop(labels=[FEATURE_COLUMNS[2]])
    with pytest.raises(ValueError, match="feature column"):
        strat.generate_signal(row, Position())


def test_stale_feature_spec_is_refused() -> None:
    stale = TrainedModel(
        classifier=_StubClassifier(),
        spec=FeatureLabelSpec(version="v0-old"),
        enter_threshold=0.6,
        exit_threshold=0.55,
        min_hold=3,
        calibrated=False,
    )
    with pytest.raises(ValueError, match="feature-spec"):
        MLClassifierStrategy.from_model(stale)


def test_threshold_overrides_take_effect() -> None:
    strat = MLClassifierStrategy.from_model(_stub_model(enter=0.6), enter_threshold=0.3)
    assert strat.enter_threshold == 0.3
    assert strat.generate_signal(_row(0.4), Position()).action == StrategySignal.BUY


def _featured(rows: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, rows))
    close = np.maximum(close, 1.0)
    raw = pd.DataFrame(
        {
            "timestamp": pd.date_range("2018-01-02", periods=rows, freq="B"),
            "open": close * (1.0 + rng.normal(0, 0.002, rows)),
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": rng.integers(1_000, 5_000, rows).astype(float),
        }
    )
    return add_technical_indicators(raw)


def test_runs_through_engine_with_features() -> None:
    # A real trained model driven through the unchanged engine on a feature frame.
    spec = FeatureLabelSpec(horizon=HORIZON, deadband=0.0)
    config = TrainingConfig(spec=spec, min_selected=5)
    frames = {"SPY": _featured(500, 1), "AAPL": _featured(500, 2)}
    panel, _ = build_pooled_panel(frames, spec=spec)
    from app.evaluation.walk_forward import generate_purged_splits

    splits = generate_purged_splits(
        panel, horizon=HORIZON, in_sample_dates=300, out_sample_dates=80, step_dates=80
    )
    result = train_model(panel, splits[0].train_idx, config=config)

    # Lower the enter threshold so the smoke test actually trades.
    strat = MLClassifierStrategy.from_model(result.model, enter_threshold=0.45)
    frame = build_features(_featured(500, 3))
    out = run_backtest(frame, strat, symbol="TEST", initial_capital=100_000.0)

    assert len(out.equity_curve) == len(frame)
    assert np.isfinite(out.final_equity)
    # Every fill respects long-only alternation (BUY then SELL …) — engine invariant.
    sides = [t.side for t in out.trades]
    assert all(sides[i] != sides[i + 1] for i in range(len(sides) - 1))
