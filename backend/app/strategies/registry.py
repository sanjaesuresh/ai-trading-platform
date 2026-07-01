"""Strategy registry: name → (strategy class, typed parameter model).

The single place strategies are registered. Resolution validates
``strategy_params`` against a per-strategy Pydantic model (so bad input is a
clean client error, never a 500) and constructs the strategy. Adding the
registry does not change existing behaviour: an unspecified strategy resolves to
``trend_following`` with its Phase 1 defaults.

Each param model is defined next to its strategy (the single source of truth for
that strategy's defaults and validation); the registry just maps names to them.
The same models back the M5 sweep runner and the M7 frontend selector.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.strategies.base_strategy import BaseStrategy
from app.strategies.event_overlay import EventOverlayParams, EventOverlayStrategy
from app.strategies.mean_reversion import MeanReversionParams, MeanReversionStrategy
from app.strategies.ml_classifier import MLClassifierParams, MLClassifierStrategy
from app.strategies.trend_following import TrendFollowingParams, TrendFollowingStrategy

# Default when a request does not name a strategy — keeps every existing caller
# and the current frontend working unchanged.
DEFAULT_STRATEGY = "trend_following"


class UnknownStrategyError(ValueError):
    """The requested strategy name is not registered."""


class StrategyParamError(ValueError):
    """The supplied strategy_params failed validation against the param schema."""


@dataclass(frozen=True)
class StrategyEntry:
    strategy_cls: type[BaseStrategy]
    params_model: type[BaseModel]


_REGISTRY: dict[str, StrategyEntry] = {
    "trend_following": StrategyEntry(TrendFollowingStrategy, TrendFollowingParams),
    "mean_reversion": StrategyEntry(MeanReversionStrategy, MeanReversionParams),
    "ml_classifier": StrategyEntry(MLClassifierStrategy, MLClassifierParams),
    "event_overlay": StrategyEntry(EventOverlayStrategy, EventOverlayParams),
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
