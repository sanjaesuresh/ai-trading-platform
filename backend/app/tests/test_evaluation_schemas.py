"""Evaluation request/response contracts: defaults and field constraints."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.evaluation import SweepRequest, WalkForwardRequest


def test_sweep_request_defaults() -> None:
    req = SweepRequest(symbol="SPY", param_grid={"rsi_buy_low": [40.0, 45.0]})
    assert req.strategy_name == "trend_following"
    assert req.objective == "sharpe_ratio"
    assert req.max_combinations == 200
    assert req.initial_capital == 100_000.0


def test_walk_forward_defaults() -> None:
    req = WalkForwardRequest(symbol="SPY", param_grid={"rsi_buy_low": [40.0, 45.0]})
    assert req.scheme == "anchored"
    assert req.in_sample_size == 504
    assert req.out_sample_size == 126
    assert req.step == 126
    assert req.baseline_strategy_name == "trend_following"
    assert req.baseline_params == {}


def test_param_grid_accepts_lists() -> None:
    req = SweepRequest(
        symbol="SPY",
        param_grid={"rsi_buy_low": [40.0, 45.0], "rsi_buy_high": [70.0, 75.0]},
    )
    assert req.param_grid["rsi_buy_low"] == [40.0, 45.0]


def test_scheme_constrained() -> None:
    assert WalkForwardRequest(symbol="SPY", param_grid={}, scheme="rolling").scheme == "rolling"
    with pytest.raises(ValidationError):
        WalkForwardRequest(symbol="SPY", param_grid={}, scheme="sideways")


def test_max_combinations_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        SweepRequest(symbol="SPY", param_grid={}, max_combinations=0)
