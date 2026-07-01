"""Strategy registry: resolution, validation, and discovery. Pure-logic, DB-free."""

from __future__ import annotations

import pytest

from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.registry import (
    DEFAULT_STRATEGY,
    StrategyParamError,
    UnknownStrategyError,
    available_strategies,
    list_strategies,
    resolve_strategy,
)
from app.strategies.trend_following import TrendFollowingStrategy


def test_both_strategies_registered() -> None:
    names = available_strategies()
    assert "trend_following" in names
    assert "mean_reversion" in names


def test_default_strategy_constant_is_trend_following() -> None:
    assert DEFAULT_STRATEGY == "trend_following"


def test_resolve_default_params_is_trend_following_baseline() -> None:
    strat = resolve_strategy("trend_following", {})
    assert isinstance(strat, TrendFollowingStrategy)
    assert strat.rsi_buy_low == 45.0
    assert strat.rsi_buy_high == 75.0
    assert strat.rsi_sell_high == 80.0


def test_resolve_none_params_uses_defaults() -> None:
    strat = resolve_strategy("trend_following", None)
    assert isinstance(strat, TrendFollowingStrategy)
    assert strat.rsi_buy_low == 45.0


def test_resolve_custom_trend_params_applied() -> None:
    strat = resolve_strategy("trend_following", {"rsi_buy_low": 50.0, "rsi_sell_high": 70.0})
    assert isinstance(strat, TrendFollowingStrategy)
    assert strat.rsi_buy_low == 50.0
    assert strat.rsi_sell_high == 70.0


def test_resolve_mean_reversion_with_params() -> None:
    strat = resolve_strategy("mean_reversion", {"entry_std": 1.5, "exit_std": 0.5})
    assert isinstance(strat, MeanReversionStrategy)
    assert strat.entry_std == 1.5
    assert strat.exit_std == 0.5


def test_unknown_strategy_raises() -> None:
    with pytest.raises(UnknownStrategyError, match="Unknown strategy"):
        resolve_strategy("does_not_exist", {})


def test_out_of_range_param_raises_param_error() -> None:
    with pytest.raises(StrategyParamError):
        resolve_strategy("mean_reversion", {"entry_std": -1.0})


def test_extra_param_rejected() -> None:
    with pytest.raises(StrategyParamError):
        resolve_strategy("trend_following", {"not_a_param": 1.0})


def test_wrong_type_param_raises_param_error() -> None:
    with pytest.raises(StrategyParamError):
        resolve_strategy("mean_reversion", {"entry_std": "wide"})


def test_trend_band_ordering_validated() -> None:
    with pytest.raises(StrategyParamError):
        resolve_strategy("trend_following", {"rsi_buy_low": 90.0, "rsi_buy_high": 50.0})


def test_mean_reversion_exit_must_be_below_entry() -> None:
    with pytest.raises(StrategyParamError):
        resolve_strategy("mean_reversion", {"entry_std": 1.0, "exit_std": 1.0})


def test_list_strategies_includes_schemas() -> None:
    listed = list_strategies()
    names = {item["name"] for item in listed}
    assert names == {
        "trend_following",
        "mean_reversion",
        "ml_classifier",
        "event_overlay",
    }
    for item in listed:
        assert "params_schema" in item
        assert "properties" in item["params_schema"]
