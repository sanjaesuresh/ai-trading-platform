"""Evaluation API: router mounted, request errors map to 400 (DB-free paths).

The 4xx paths (oversized grid, unknown strategy) raise before any data load, so
they need no live DB. List/detail round-trips against a real DB are exercised in
the manual integration step.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_routes_are_mounted() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/evaluations/sweep" in paths
    assert "/evaluations/walk-forward" in paths
    assert "/evaluations" in paths
    assert "/evaluations/{evaluation_id}" in paths


def test_sweep_endpoint_validation_error() -> None:
    resp = client.post(
        "/evaluations/sweep",
        json={
            "symbol": "OSC",
            "strategy_name": "trend_following",
            "param_grid": {"rsi_buy_low": [40.0, 45.0], "rsi_buy_high": [70.0, 75.0]},
            "max_combinations": 3,  # product 4 > 3
        },
    )
    assert resp.status_code == 400
    body = resp.json()["detail"]
    assert "message" in body and "combinations" in body["message"]


def test_unknown_strategy_400() -> None:
    resp = client.post(
        "/evaluations/sweep",
        json={"symbol": "OSC", "strategy_name": "nope", "param_grid": {"x": [1, 2]}},
    )
    assert resp.status_code == 400


def test_walk_forward_endpoint_accepts_policy() -> None:
    # Valid policy fields parse (no 422); the oversized grid makes it a 400 business
    # error before any DB load — proving the router accepts the walk-forward policy.
    resp = client.post(
        "/evaluations/walk-forward",
        json={
            "symbol": "OSC",
            "param_grid": {"rsi_buy_low": [40.0, 45.0], "rsi_buy_high": [70.0, 75.0]},
            "max_combinations": 3,
            "scheme": "rolling",
            "in_sample_size": 252,
            "out_sample_size": 63,
            "step": 63,
        },
    )
    assert resp.status_code == 400


def test_bad_scheme_is_422() -> None:
    resp = client.post(
        "/evaluations/walk-forward",
        json={"symbol": "OSC", "param_grid": {}, "scheme": "sideways"},
    )
    assert resp.status_code == 422
