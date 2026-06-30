"""ML classifier strategy: a trained model wearing the BaseStrategy interface.

``MLClassifierStrategy`` consults an already-trained model — it holds no training
logic. Each bar it builds the model's feature vector from the row, reads the calibrated
P(up), and emits long/flat with hysteresis (separate enter/exit thresholds) and a
minimum holding period pinned to the label horizon, so a 5-day forecast is not
re-traded every bar and trading costs do not quietly dominate (plan §2, §7).

To the engine and the Phase 3 portfolio core it is indistinguishable from a rule-based
strategy: next-bar-open semantics are preserved (the signal is acted on at the next
open, like every other strategy). The instance is single-run stateful (it counts bars
held), so resolve a fresh one per backtest — which the registry already does.

Two construction paths: by ``model_id`` (loads from the registry, used by the API/jobs)
or ``from_model`` with an in-memory ``TrainedModel`` (used by walk-forward retraining,
which trains a fresh model per split). Both assert the model's feature spec still
matches the live code before running.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.ml.model import TrainedModel
from app.ml.registry import assert_live_spec, load_model
from app.strategies.base_strategy import (
    BaseStrategy,
    Position,
    StrategyDecision,
    StrategySignal,
)


class MLClassifierParams(BaseModel):
    """Parameters for the registry path: which model, and optional decision overrides.

    Omitted thresholds / min-hold fall back to the values chosen at training time and
    stored with the model.
    """

    # model_id sits in pydantic's protected ``model_`` namespace; allow it explicitly.
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_id: str = Field(min_length=1)
    enter_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    exit_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    min_hold: int | None = Field(default=None, ge=0)


class MLClassifierStrategy(BaseStrategy):
    name = "ml_classifier"

    def __init__(
        self,
        model_id: str,
        enter_threshold: float | None = None,
        exit_threshold: float | None = None,
        min_hold: int | None = None,
        *,
        _model: TrainedModel | None = None,
    ) -> None:
        model = _model if _model is not None else load_model(model_id, get_settings().model_path)
        assert_live_spec(model)
        self._model = model
        self.model_id = model_id
        self.enter_threshold = (
            enter_threshold if enter_threshold is not None else model.enter_threshold
        )
        self.exit_threshold = (
            exit_threshold if exit_threshold is not None else model.exit_threshold
        )
        self.min_hold = min_hold if min_hold is not None else model.min_hold
        self._cols = list(model.spec.feature_columns)
        self._bars_held = 0

    @classmethod
    def from_model(
        cls, model: TrainedModel, *, model_id: str = "(in-memory)", **overrides: object
    ) -> MLClassifierStrategy:
        """Build a strategy around an in-memory model (walk-forward retraining path)."""
        return cls(model_id=model_id, _model=model, **overrides)  # type: ignore[arg-type]

    def generate_signal(
        self, row: pd.Series, current_position: Position
    ) -> StrategyDecision:
        # Track holding duration so the min-hold can gate exits. Counts bars the engine
        # reports the position as open (the fill landed at the next open after entry).
        self._bars_held = self._bars_held + 1 if current_position.is_open else 0

        missing = [c for c in self._cols if c not in row.index]
        if missing:
            raise ValueError(
                f"ML strategy needs feature column(s) not in the frame: "
                f"{', '.join(missing)}. Build features before running the engine."
            )
        if any(pd.isna(row.get(c)) for c in self._cols):
            return StrategyDecision(
                action=StrategySignal.HOLD,
                reason="Features not yet warmed up; holding.",
            )

        features = pd.DataFrame([{c: float(row[c]) for c in self._cols}])
        prob = float(self._model.predict_proba_up(features)[0])

        if not current_position.is_open:
            if prob >= self.enter_threshold:
                return StrategyDecision(
                    action=StrategySignal.BUY,
                    reason=f"P(up)={prob:.3f} >= enter {self.enter_threshold:.3f}.",
                )
            return StrategyDecision(
                action=StrategySignal.HOLD,
                reason=f"P(up)={prob:.3f} < enter {self.enter_threshold:.3f}; flat.",
            )

        if self._bars_held >= self.min_hold and prob < self.exit_threshold:
            return StrategyDecision(
                action=StrategySignal.SELL,
                reason=(
                    f"P(up)={prob:.3f} < exit {self.exit_threshold:.3f} "
                    f"after {self._bars_held} bars held."
                ),
            )
        return StrategyDecision(
            action=StrategySignal.HOLD,
            reason=f"P(up)={prob:.3f}; holding (min-hold {self.min_hold}).",
        )
