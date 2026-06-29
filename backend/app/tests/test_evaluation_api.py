"""Evaluation API: router mounted, request errors map to 400 (DB-free paths).

The 4xx paths (oversized grid, unknown strategy) raise before any data load, so
they need no live DB. List/detail round-trips against a real DB are exercised in
the manual integration step.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.routes import evaluation
from app.main import create_app

client = TestClient(create_app())


class _FakeRun:
    """Stand-in for a persisted EvaluationRun (from_attributes validation)."""

    def __init__(self, status: str) -> None:
        self.id = 99
        self.kind = "sweep"
        self.symbol = "OSC"
        self.strategy_name = "trend_following"
        self.status = status
        self.objective = "sharpe_ratio"
        self.created_at = datetime.now(UTC)


def test_routes_are_mounted() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/evaluations/sweep" in paths
    assert "/evaluations/walk-forward" in paths
    assert "/evaluations/sweep/sync" in paths
    assert "/evaluations/walk-forward/sync" in paths
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


def test_sweep_enqueues_and_returns_queued(monkeypatch) -> None:
    """The default sweep path persists a queued row and enqueues the task by id."""
    captured: dict[str, object] = {}

    def fake_create(req, db):  # noqa: ANN001
        return _FakeRun("queued")

    async def fake_enqueue(task_name: str, **kwargs: object) -> str:
        captured["task_name"] = task_name
        captured["kwargs"] = kwargs
        return "job-xyz"

    monkeypatch.setattr(evaluation, "create_queued_sweep_run", fake_create)
    monkeypatch.setattr(evaluation, "enqueue", fake_enqueue)

    resp = client.post("/evaluations/sweep", json={"symbol": "OSC", "param_grid": {}})

    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"
    assert captured["task_name"] == "evaluation_task"
    assert captured["kwargs"] == {"evaluation_run_id": 99}


def test_sweep_enqueue_failure_marks_run_failed(monkeypatch) -> None:
    """If the queue is unreachable, the queued row is marked failed (not stranded)."""
    run = _FakeRun("queued")
    marked: dict[str, object] = {}

    def fake_create(req, db):  # noqa: ANN001
        return run

    async def boom_enqueue(task_name: str, **kwargs: object) -> str:
        raise RuntimeError("redis down")

    def fake_mark_failed(db, r, error):  # noqa: ANN001
        marked["error"] = error
        r.status = "failed"
        return r

    monkeypatch.setattr(evaluation, "create_queued_sweep_run", fake_create)
    monkeypatch.setattr(evaluation, "enqueue", boom_enqueue)
    monkeypatch.setattr(evaluation, "mark_failed", fake_mark_failed)

    resp = client.post("/evaluations/sweep", json={"symbol": "OSC", "param_grid": {}})

    assert resp.status_code == 503
    assert run.status == "failed"
    assert "redis down" in str(marked["error"])


def test_sync_path_still_runs_inline(monkeypatch) -> None:
    """The /sync sub-path keeps M5's inline behavior (201, completed)."""

    def fake_pipeline(req, db):  # noqa: ANN001
        return _FakeRun("completed")

    monkeypatch.setattr(evaluation, "run_sweep_pipeline", fake_pipeline)

    resp = client.post(
        "/evaluations/sweep/sync", json={"symbol": "OSC", "param_grid": {}}
    )

    assert resp.status_code == 201
    assert resp.json()["status"] == "completed"
