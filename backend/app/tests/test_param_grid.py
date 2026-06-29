"""Parameter-grid expansion: Cartesian product, validation, size counting."""

from __future__ import annotations

import pytest

from app.evaluation.grid import count_combinations, expand_param_grid
from app.strategies.registry import StrategyParamError, UnknownStrategyError


def test_two_keys_cartesian_product() -> None:
    grid = {"rsi_buy_low": [40.0, 45.0], "rsi_buy_high": [70.0, 75.0, 80.0]}
    combos = expand_param_grid("trend_following", grid)
    assert len(combos) == 6
    for combo in combos:
        assert set(combo) == {"rsi_buy_low", "rsi_buy_high"}
    # Every distinct pairing appears exactly once.
    pairs = {(c["rsi_buy_low"], c["rsi_buy_high"]) for c in combos}
    assert len(pairs) == 6


def test_single_key() -> None:
    combos = expand_param_grid("trend_following", {"rsi_buy_low": [40.0, 45.0]})
    assert len(combos) == 2
    assert [c["rsi_buy_low"] for c in combos] == [40.0, 45.0]


def test_empty_grid_yields_one_default_combo() -> None:
    combos = expand_param_grid("trend_following", {})
    assert combos == [{}]


def test_count_matches_len() -> None:
    grids = [
        {},
        {"rsi_buy_low": [40.0, 45.0]},
        {"rsi_buy_low": [40.0, 45.0], "rsi_buy_high": [70.0, 75.0, 80.0]},
    ]
    for grid in grids:
        assert count_combinations(grid) == len(expand_param_grid("trend_following", grid))


def test_invalid_combo_rejected() -> None:
    # exit_std must be < entry_std; this combo violates the param model.
    with pytest.raises(StrategyParamError):
        expand_param_grid("mean_reversion", {"entry_std": [1.0], "exit_std": [2.0]})


def test_unknown_strategy_rejected() -> None:
    with pytest.raises(UnknownStrategyError):
        expand_param_grid("does_not_exist", {"foo": [1, 2]})
