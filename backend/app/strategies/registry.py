"""Strategy registry: name → (strategy class, typed parameter model).

The single place strategies are registered. Resolution validates
``strategy_params`` against a per-strategy Pydantic model (so bad input is a
clean client error, never a 500) and constructs the strategy. Adding the
registry does not change existing behaviour: an unspecified strategy resolves to
``trend_following`` with its Phase 1 defaults.

The same param models back the M5 sweep runner and the M7 frontend selector, so
each schema is owned next to its strategy and built once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.strategies.base_strategy import BaseStrategy
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.trend_following import TrendFollowingStrategy

# Default when a request does not name a strategy — keeps every existing caller
# and the current frontend working unchanged.
DEFAULT_STRATEGY = "trend_following"


class UnknownStrategyError(ValueError):
    """The requested strategy name is not registered."""


class StrategyParamError(ValueError):
    """The supplied strategy_params failed validation against the param schema."""


class TrendFollowingParams(BaseModel):
    """Tunable RSI bands for trend-following. Defaults = Phase 1 baseline."""

    model_config = ConfigDict(extra="forbid")

    rsi_buy_low: float = Field(default=45.0, ge=0.0, le=100.0)
    rsi_buy_high: float = Field(default=75.0, ge=0.0, le=100.0)
    rsi_sell_high: float = Field(default=80.0, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def _bands_ordered(self) -> TrendFollowingParams:
        if self.rsi_buy_low > self.rsi_buy_high:
            raise ValueError("rsi_buy_low must be <= rsi_buy_high.")
        return self


class MeanReversionParams(BaseModel):
    """Band widths (in rolling-std units) for mean reversion."""

    model_config = ConfigDict(extra="forbid")

    entry_std: float = Field(default=2.0, gt=0.0, le=10.0)
    exit_std: float = Field(default=0.0, ge=0.0, le=10.0)

    @model_validator(mode="after")
    def _entry_below_exit(self) -> MeanReversionParams:
        if self.exit_std >= self.entry_std:
            raise ValueError("exit_std must be < entry_std (exit band above entry band).")
        return self


@dataclass(frozen=True)
class StrategyEntry:
    strategy_cls: type[BaseStrategy]
    params_model: type[BaseModel]


_REGISTRY: dict[str, StrategyEntry] = {
    "trend_following": StrategyEntry(TrendFollowingStrategy, TrendFollowingParams),
    "mean_reversion": StrategyEntry(MeanReversionStrategy, MeanReversionParams),
}


def available_strategies() -> list[str]:
    """Registered strategy names."""
    return list(_REGISTRY)


def _get_entry(name: str) -> StrategyEntry:
    entry = _REGISTRY.get(name)
    if entry is None:
        raise UnknownStrategyError(
            f"Unknown strategy '{name}'. Available: {', '.join(_REGISTRY)}."
        )
    return entry


def resolve_strategy(name: str, params: dict[str, Any] | None = None) -> BaseStrategy:
    """Construct the strategy named *name* with validated *params*.

    Raises ``UnknownStrategyError`` for an unregistered name and
    ``StrategyParamError`` for params that fail the schema — both client errors.
    """
    entry = _get_entry(name)
    try:
        validated = entry.params_model(**(params or {}))
    except ValidationError as exc:
        messages = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '(model)'}: {err['msg']}"
            for err in exc.errors()
        )
        raise StrategyParamError(
            f"Invalid params for strategy '{name}': {messages}"
        ) from exc
    return entry.strategy_cls(**validated.model_dump())


def list_strategies() -> list[dict[str, Any]]:
    """Available strategies with their JSON parameter schemas (for the API)."""
    return [
        {"name": name, "params_schema": entry.params_model.model_json_schema()}
        for name, entry in _REGISTRY.items()
    ]
