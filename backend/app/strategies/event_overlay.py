"""Event-overlay strategy (Phase 5 M6).

A ``BaseStrategy`` that wraps an underlying price strategy and modulates its
signal around high-confidence news events. It reads **stored event annotations**
(the point-in-time, cutoff-respecting news columns produced by
``build_news_features`` — ``n_event_flag`` and a decayed-sentiment column) that are
already joined onto the bar's row. It **never calls the LLM**: annotation happens
off the backtest path at ingest time (M3); here the overlay only consumes columns.

Because the event columns obey the §2 availability cutoff, the overlay is
leak-safe by construction — the row at bar N carries only event information
available by the cutoff for that decision.

Lever: in the long-only, one-position Phase 1 engine there is no per-bar position
scaling, so the overlay's lever is a **veto** — around a high-confidence *adverse*
event it blocks a new entry the underlying wanted, and (optionally) exits an open
position to sidestep the event. On benign or favourable events, or when no event
column is present, it passes the underlying decision through unchanged. It is
evaluated against the price-only underlying net of cost through the same engine.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.strategies.base_strategy import (
    BaseStrategy,
    Position,
    StrategyDecision,
    StrategySignal,
)


class EventOverlayParams(BaseModel):
    """Tunable parameters for the event overlay."""

    model_config = ConfigDict(extra="forbid")

    underlying_strategy: str = "trend_following"
    underlying_params: dict[str, Any] = Field(default_factory=dict)
    # Point-in-time news columns the overlay reads (from build_news_features).
    event_flag_col: str = "n_event_flag"
    event_sentiment_col: str = "n_sent_decay"
    # An event is "adverse" when the flag is set and decayed sentiment is below
    # -veto_threshold. Larger = only stronger negative events veto.
    veto_threshold: float = Field(default=0.3, ge=0.0)
    # Exit an open position around an adverse high-confidence event.
    exit_on_adverse: bool = True

    @model_validator(mode="after")
    def _no_recursive_overlay(self) -> EventOverlayParams:
        if self.underlying_strategy == "event_overlay":
            raise ValueError("underlying_strategy cannot be 'event_overlay' (no recursion).")
        return self


_DEFAULTS = EventOverlayParams()


class EventOverlayStrategy(BaseStrategy):
    name = "event_overlay"

    def __init__(
        self,
        underlying_strategy: str = _DEFAULTS.underlying_strategy,
        underlying_params: dict[str, Any] | None = None,
        event_flag_col: str = _DEFAULTS.event_flag_col,
        event_sentiment_col: str = _DEFAULTS.event_sentiment_col,
        veto_threshold: float = _DEFAULTS.veto_threshold,
        exit_on_adverse: bool = _DEFAULTS.exit_on_adverse,
    ) -> None:
        params = EventOverlayParams(
            underlying_strategy=underlying_strategy,
            underlying_params=underlying_params or {},
            event_flag_col=event_flag_col,
            event_sentiment_col=event_sentiment_col,
            veto_threshold=veto_threshold,
            exit_on_adverse=exit_on_adverse,
        )
        # Lazy import breaks the registry <-> strategy import cycle.
        from app.strategies.registry import resolve_strategy

        self._underlying = resolve_strategy(
            params.underlying_strategy, params.underlying_params
        )
        self.underlying_strategy = params.underlying_strategy
        self.event_flag_col = params.event_flag_col
        self.event_sentiment_col = params.event_sentiment_col
        self.veto_threshold = params.veto_threshold
        self.exit_on_adverse = params.exit_on_adverse

    def generate_signal(
        self, row: pd.Series, current_position: Position
    ) -> StrategyDecision:
        base = self._underlying.generate_signal(row, current_position)

        flag = row.get(self.event_flag_col)
        sentiment = row.get(self.event_sentiment_col)
        # No event data on this bar → pass the underlying decision through.
        if flag is None or sentiment is None or pd.isna(flag) or pd.isna(sentiment):
            return base

        adverse = float(flag) >= 0.5 and float(sentiment) < -self.veto_threshold
        if not adverse:
            return base

        if current_position.is_open and self.exit_on_adverse:
            return StrategyDecision(
                action=StrategySignal.SELL,
                reason=(
                    f"Event overlay: exiting on adverse high-confidence event "
                    f"(decayed sentiment {float(sentiment):.2f})."
                ),
            )
        if base.action is StrategySignal.BUY:
            return StrategyDecision(
                action=StrategySignal.HOLD,
                reason=(
                    f"Event overlay: vetoed entry around adverse event "
                    f"(decayed sentiment {float(sentiment):.2f})."
                ),
            )
        return base
