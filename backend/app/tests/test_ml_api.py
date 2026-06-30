"""ML API: router mounted, request validation → 422/400, enqueue lifecycle (DB-free).

All 4xx paths and the enqueue happy-path are exercised via FastAPI's TestClient.
Paths that need a live DB (model list/detail, evaluation detail) are manual
integration steps. The TestClient never reaches any database.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.routes import ml as ml_routes
from app.main import create_app

client = TestClient(create_app())


# ---------------------------------------------------------------------------
# Fake ORM objects for monkeypatching service layer
# ---------------------------------------------------------------------------


class _FakeMLModel:
    def __init__(self) -> None:
        self.id = 1
        self.model_id = "abc123def456abc1"
        self.feature_spec_version = "v1"
        self.symbols = ["SPY"]
        self.train_start = "2022-01-03"
        self.train_end = "2023-12-29"
        self.horizon = 5
        self.deadband = 0.0
        self.calibrated = True
        self.enter_threshold = 0.60
        self.exit_threshold = 0.55
        self.created_at = datetime.now(UTC)
        # Detail fields
        self.lgbm_params = {}
        self.seed = 42
        self.num_threads = 1
        self.calibration = "isotonic"
        self.min_hold = 5
        self.n_fit = 300
        self.n_calib = 100
        self.n_thresh = 100
        self.effective_n = 250.0
        self.selection_config = {}
        self.validation_metrics = {"auc": 0.55}
        self.code_git_hash = "abc"
        self.code_dirty = False
        self.code_diff_hash = None
        self.artifact_hash = "deadbeef" * 4


class _FakeRun:
    def __init__(self, kind: str = "ml_walk_forward") -> None:
        self.id = 42
        self.kind = kind
        self.symbol = "SPY"
        self.strategy_name = "ml_classifier"
        self.status = "queued"
        self.objective = "sharpe_ratio"
        self.created_at = datetime.now(UTC)
        self.config: dict = {}
        self.results: dict = {}
        self.error = None


# ---------------------------------------------------------------------------
# Routes are mounted
# ---------------------------------------------------------------------------


def test_ml_routes_are_mounted() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/ml/models" in paths
    assert "/ml/models/{model_id}" in paths
    assert "/ml/evaluations/walk-forward" in paths
    assert "/ml/evaluations/backtest" in paths
    assert "/ml/evaluations/{evaluation_id}" in paths


# ---------------------------------------------------------------------------
# MLTrainRequest validation
# ---------------------------------------------------------------------------


def test_train_empty_symbols_422() -> None:
    resp = client.post("/ml/models", json={"symbols": []})
    assert resp.status_code == 422


def test_train_missing_symbols_422() -> None:
    resp = client.post("/ml/models", json={})
    assert resp.status_code == 422


def test_train_bad_horizon_422() -> None:
    resp = client.post("/ml/models", json={"symbols": ["SPY"], "horizon": 0})
    assert resp.status_code == 422


def test_train_bad_deadband_422() -> None:
    resp = client.post("/ml/models", json={"symbols": ["SPY"], "deadband": -0.1})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# MLWalkForwardRequest validation
# ---------------------------------------------------------------------------


def test_walk_forward_empty_symbols_422() -> None:
    resp = client.post("/ml/evaluations/walk-forward", json={"symbols": [], "eval_symbol": "SPY"})
    assert resp.status_code == 422


def test_walk_forward_eval_symbol_not_in_symbols_422() -> None:
    resp = client.post(
        "/ml/evaluations/walk-forward",
        json={"symbols": ["SPY", "AAPL"], "eval_symbol": "MSFT"},
    )
    assert resp.status_code == 422


def test_walk_forward_missing_eval_symbol_422() -> None:
    resp = client.post(
        "/ml/evaluations/walk-forward",
        json={"symbols": ["SPY"]},
    )
    assert resp.status_code == 422


def test_walk_forward_bad_fee_bps_422() -> None:
    resp = client.post(
        "/ml/evaluations/walk-forward",
        json={"symbols": ["SPY"], "eval_symbol": "SPY", "fee_bps": -1},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# MLBacktestRequest validation
# ---------------------------------------------------------------------------


def test_backtest_missing_model_id_422() -> None:
    resp = client.post("/ml/evaluations/backtest", json={"symbol": "SPY"})
    assert resp.status_code == 422


def test_backtest_missing_symbol_422() -> None:
    resp = client.post("/ml/evaluations/backtest", json={"model_id": "abc123"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Walk-forward enqueue happy path
# ---------------------------------------------------------------------------


def test_walk_forward_enqueues_and_returns_queued(monkeypatch) -> None:
    """The walk-forward path persists a queued row and enqueues the ML task by id."""
    captured: dict[str, object] = {}

    def fake_create(req, *, kind, db):  # noqa: ANN001
        return _FakeRun(kind=kind)

    async def fake_enqueue(task_name: str, **kwargs: object) -> str:
        captured["task_name"] = task_name
        captured["kwargs"] = kwargs
        return "job-wf-1"

    monkeypatch.setattr(ml_routes, "create_queued_ml_run", fake_create)
    monkeypatch.setattr(ml_routes, "enqueue", fake_enqueue)

    resp = client.post(
        "/ml/evaluations/walk-forward",
        json={"symbols": ["SPY"], "eval_symbol": "SPY"},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["kind"] == "ml_walk_forward"
    assert captured["task_name"] == "ml_task"
    assert captured["kwargs"] == {"evaluation_run_id": 42}


def test_backtest_enqueues_and_returns_queued(monkeypatch) -> None:
    """The backtest path persists a queued row and enqueues the ML task by id."""
    captured: dict[str, object] = {}

    def fake_create(req, *, kind, db):  # noqa: ANN001
        return _FakeRun(kind=kind)

    async def fake_enqueue(task_name: str, **kwargs: object) -> str:
        captured["task_name"] = task_name
        captured["kwargs"] = kwargs
        return "job-bt-1"

    # model_id existence check added in finding #4 fix — stub it to return a model.
    monkeypatch.setattr(ml_routes, "get_ml_model", lambda db, mid: _FakeMLModel())
    monkeypatch.setattr(ml_routes, "create_queued_ml_run", fake_create)
    monkeypatch.setattr(ml_routes, "enqueue", fake_enqueue)

    resp = client.post(
        "/ml/evaluations/backtest",
        json={"model_id": "abc123", "symbol": "SPY"},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["kind"] == "ml_backtest"
    assert captured["task_name"] == "ml_task"


def test_walk_forward_enqueue_failure_marks_run_failed(monkeypatch) -> None:
    """If the queue is unreachable, the queued row is marked failed (503)."""
    run = _FakeRun()
    marked: dict[str, object] = {}

    def fake_create(req, *, kind, db):  # noqa: ANN001
        return run

    async def boom_enqueue(task_name: str, **kwargs: object) -> str:
        raise RuntimeError("redis down")

    def fake_mark_failed(db, r, error):  # noqa: ANN001
        marked["error"] = error
        r.status = "failed"
        return r

    monkeypatch.setattr(ml_routes, "create_queued_ml_run", fake_create)
    monkeypatch.setattr(ml_routes, "enqueue", boom_enqueue)
    monkeypatch.setattr(ml_routes, "mark_failed", fake_mark_failed)

    resp = client.post(
        "/ml/evaluations/walk-forward",
        json={"symbols": ["SPY"], "eval_symbol": "SPY"},
    )

    assert resp.status_code == 503
    assert run.status == "failed"
    assert "redis down" in str(marked["error"])


# ---------------------------------------------------------------------------
# Model endpoint: 404 for unknown model
# ---------------------------------------------------------------------------


def test_get_unknown_model_404(monkeypatch) -> None:
    monkeypatch.setattr(ml_routes, "get_ml_model", lambda db, mid: None)
    resp = client.get("/ml/models/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Finding #4 — enqueue backtest with unknown model_id → 404, not 202
# ---------------------------------------------------------------------------


def test_backtest_unknown_model_id_returns_404(monkeypatch) -> None:
    """POST /ml/evaluations/backtest with an unregistered model_id returns 404 at enqueue.

    The route checks model existence before creating the queued row so the caller
    gets a clean 4xx immediately rather than a 202 that fails asynchronously in
    the worker.
    """
    monkeypatch.setattr(ml_routes, "get_ml_model", lambda db, mid: None)

    resp = client.post(
        "/ml/evaluations/backtest",
        json={"model_id": "nonexistent_model", "symbol": "SPY"},
    )

    assert resp.status_code == 404
