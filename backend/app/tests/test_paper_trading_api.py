"""Paper-trading API: routes mounted, input validation, run trigger enqueues.

DB-free (TestClient without lifespan, validation rejects before any query; the
run trigger is fully DB-free). List/portfolio/comparison round-trips against a
real DB are a manual integration step.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.routes import paper_trading
from app.main import create_app
from app.schemas.paper_trading import DeploymentRiskConfig
from app.services.paper_trading_service import slippage_stats

client = TestClient(create_app())


def _valid_create() -> dict:
    return {
        "name": "SPY basket",
        "strategy_name": "trend_following",
        "symbols": ["SPY", "AAPL"],
        "starting_capital": 100_000.0,
    }


def test_paper_routes_are_mounted() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/paper/deployments" in paths
    assert "/paper/deployments/{deployment_id}" in paths
    assert "/paper/deployments/{deployment_id}/run" in paths
    assert "/paper/deployments/{deployment_id}/portfolio" in paths
    assert "/paper/deployments/{deployment_id}/comparison" in paths
    assert "/paper/kill-switch" in paths


def test_create_rejects_empty_symbols() -> None:
    body = _valid_create() | {"symbols": []}
    assert client.post("/paper/deployments", json=body).status_code == 422


def test_create_rejects_nonpositive_capital() -> None:
    body = _valid_create() | {"starting_capital": 0.0}
    assert client.post("/paper/deployments", json=body).status_code == 422


def test_create_rejects_leverage_in_config() -> None:
    # gross_exposure_cap > 1.0 means leverage — out of bounds (cash account).
    body = _valid_create() | {"config": {"gross_exposure_cap": 2.0}}
    assert client.post("/paper/deployments", json=body).status_code == 422


def test_create_rejects_unknown_config_field() -> None:
    body = _valid_create() | {"config": {"bogus_knob": 1.0}}
    assert client.post("/paper/deployments", json=body).status_code == 422


def test_run_trigger_enqueues(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_enqueue(task_name: str, **kwargs: object) -> str:
        captured["task_name"] = task_name
        captured["kwargs"] = kwargs
        return "job-xyz"

    monkeypatch.setattr(paper_trading, "enqueue", fake_enqueue)

    resp = client.post(
        "/paper/deployments/7/run",
        json={"trading_day": "2026-01-05", "phase": "submit"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"] == "job-xyz"
    assert body["deployment_id"] == 7
    assert body["phase"] == "submit"
    assert captured["task_name"] == "paper_run_task"
    assert captured["kwargs"] == {
        "deployment_id": 7, "trading_day": "2026-01-05", "phase": "submit",
    }


def test_run_trigger_defaults_to_both_phase(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_enqueue(task_name: str, **kwargs: object) -> str:
        captured.update(kwargs)
        return "job-1"

    monkeypatch.setattr(paper_trading, "enqueue", fake_enqueue)
    resp = client.post("/paper/deployments/3/run", json={})
    assert resp.status_code == 202
    assert captured["phase"] == "both"
    assert captured["trading_day"] is None


def test_kill_switch_requires_active_flag() -> None:
    assert client.post("/paper/kill-switch", json={"reason": "x"}).status_code == 422


# --- Schema / pure-helper unit tests ---------------------------------------


def test_risk_config_defaults_follow_plan() -> None:
    cfg = DeploymentRiskConfig()
    assert cfg.gross_exposure_cap == 1.0  # no leverage
    assert cfg.max_open_positions == 5
    assert cfg.max_drawdown_cutoff_pct == 0.20  # -20% kill


def test_slippage_stats_distribution() -> None:
    stats = slippage_stats([0.5, -0.5, 1.0])
    assert stats["count"] == 3
    assert stats["mean"] == 1.0 / 3
    assert stats["median"] == 0.5
    assert stats["min"] == -0.5
    assert stats["max"] == 1.0


def test_slippage_stats_empty_is_safe() -> None:
    stats = slippage_stats([])
    assert stats == {"count": 0, "mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
