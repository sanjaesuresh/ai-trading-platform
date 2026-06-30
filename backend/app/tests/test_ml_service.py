"""ML service: DB-free unit tests.

Tests cover:
- ``_metadata_to_orm``: ModelMetadata → MLModel ORM field mapping.
- ``build_ml_inputs`` transform logic (pure path, mocked DB).
- ``create_queued_ml_run``: correct kind, symbol, strategy_name on the row.
- ``execute_ml_run``: dispatches walk-forward vs backtest by kind, raises on unknown.
- ML_TASK_NAME constant and worker registration.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# ModelMetadata → MLModel round-trip (no DB)
# ---------------------------------------------------------------------------


def test_metadata_to_orm_fields() -> None:
    """_metadata_to_orm maps every ModelMetadata field to the correct ORM column."""
    from app.ml.registry import ModelMetadata
    from app.services.ml_service import _metadata_to_orm

    meta = ModelMetadata(
        model_id="abc123def456abc1",
        feature_spec_version="v1",
        feature_columns=["f_rsi_14"],
        horizon=5,
        deadband=0.01,
        symbols=["SPY", "AAPL"],
        train_start="2022-01-03",
        train_end="2023-12-29",
        lgbm_params={"n_estimators": 400},
        seed=42,
        num_threads=1,
        calibration="isotonic",
        calibrated=True,
        enter_threshold=0.62,
        exit_threshold=0.57,
        min_hold=5,
        n_fit=300,
        n_calib=100,
        n_thresh=100,
        effective_n=250.0,
        selection_config={"cost_bps": 10.0},
        validation_metrics={"auc": 0.55, "brier": 0.24},
        code_git_hash="deadbeef",
        code_dirty=False,
        code_diff_hash=None,
        artifact_hash="a" * 64,
    )
    row = _metadata_to_orm(meta)

    assert row.model_id == "abc123def456abc1"
    assert row.feature_spec_version == "v1"
    assert row.symbols == ["SPY", "AAPL"]
    assert row.train_start == "2022-01-03"
    assert row.train_end == "2023-12-29"
    assert row.horizon == 5
    assert row.deadband == 0.01
    assert row.lgbm_params == {"n_estimators": 400}
    assert row.seed == 42
    assert row.num_threads == 1
    assert row.calibration == "isotonic"
    assert row.calibrated is True
    assert row.enter_threshold == pytest.approx(0.62)
    assert row.exit_threshold == pytest.approx(0.57)
    assert row.min_hold == 5
    assert row.n_fit == 300
    assert row.n_calib == 100
    assert row.n_thresh == 100
    assert row.effective_n == pytest.approx(250.0)
    assert row.selection_config == {"cost_bps": 10.0}
    assert row.validation_metrics == {"auc": 0.55, "brier": 0.24}
    assert row.code_git_hash == "deadbeef"
    assert row.code_dirty is False
    assert row.code_diff_hash is None
    assert row.artifact_hash == "a" * 64


# ---------------------------------------------------------------------------
# MLModel ORM object: field access without DB
# ---------------------------------------------------------------------------


def test_ml_model_orm_instance_attrs() -> None:
    """MLModel can be constructed and its attrs read without touching a DB session."""
    from app.models_db.ml_model import MLModel

    row = MLModel(
        model_id="testid",
        feature_spec_version="v1",
        symbols=["SPY"],
        train_start="2022-01-03",
        train_end="2023-12-29",
        horizon=5,
        deadband=0.0,
        lgbm_params={},
        seed=42,
        num_threads=1,
        calibration="isotonic",
        calibrated=True,
        enter_threshold=0.60,
        exit_threshold=0.55,
        min_hold=5,
        n_fit=300,
        n_calib=100,
        n_thresh=100,
        effective_n=250.0,
        selection_config={},
        validation_metrics={},
        code_git_hash="abc",
        code_dirty=False,
        code_diff_hash=None,
        artifact_hash="x" * 64,
    )
    assert row.model_id == "testid"
    assert row.symbols == ["SPY"]
    assert row.calibrated is True
    # created_at gets its default when persisted; None before the session assigns it.
    # The important thing is the column exists on the class.
    assert hasattr(row, "created_at")


# ---------------------------------------------------------------------------
# create_queued_ml_run: kind, symbol, strategy_name
# ---------------------------------------------------------------------------


class _FakeDB:
    """Minimal fake session that tracks what was added and supports refresh."""

    def __init__(self) -> None:
        self._added: list = []
        self._next_id = 99

    def add(self, obj: object) -> None:
        self._added.append(obj)

    def commit(self) -> None:
        for obj in self._added:
            if not hasattr(obj, "id") or obj.id is None:
                obj.id = self._next_id
                self._next_id += 1

    def refresh(self, obj: object) -> None:
        pass


def test_create_queued_walk_forward_run() -> None:
    from app.schemas.ml import MLWalkForwardRequest
    from app.services.ml_service import create_queued_ml_run

    req = MLWalkForwardRequest(symbols=["SPY", "AAPL"], eval_symbol="SPY")
    db = _FakeDB()
    run = create_queued_ml_run(req, kind="ml_walk_forward", db=db)

    assert run.kind == "ml_walk_forward"
    assert run.symbol == "SPY"          # eval_symbol
    assert run.strategy_name == "ml_classifier"
    assert run.status == "queued"
    assert run.results == {}


def test_create_queued_backtest_run() -> None:
    from app.schemas.ml import MLBacktestRequest
    from app.services.ml_service import create_queued_ml_run

    req = MLBacktestRequest(model_id="abc123", symbol="AAPL")
    db = _FakeDB()
    run = create_queued_ml_run(req, kind="ml_backtest", db=db)

    assert run.kind == "ml_backtest"
    assert run.symbol == "AAPL"
    assert run.strategy_name == "ml_classifier"
    assert run.status == "queued"


def test_create_queued_ml_run_bad_kind_raises() -> None:
    from app.schemas.ml import MLBacktestRequest
    from app.services.ml_service import create_queued_ml_run

    req = MLBacktestRequest(model_id="abc", symbol="SPY")
    db = _FakeDB()
    with pytest.raises(ValueError, match="Unknown ML evaluation kind"):
        create_queued_ml_run(req, kind="invalid_kind", db=db)


# ---------------------------------------------------------------------------
# execute_ml_run: dispatches by kind, raises on unknown
# ---------------------------------------------------------------------------


class _FakeRunObj:
    def __init__(self, kind: str) -> None:
        self.id = 1
        self.kind = kind
        self.status = "running"
        self.results: dict = {}
        self.error = None
        self.finished_at = None
        self.config: dict = {}


def test_execute_ml_run_dispatches_walk_forward(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import ml_service

    called: dict[str, bool] = {}

    def fake_wf(db, run):  # noqa: ANN001
        called["wf"] = True
        return run

    monkeypatch.setattr(ml_service, "run_ml_walk_forward", fake_wf)

    run = _FakeRunObj("ml_walk_forward")
    ml_service.execute_ml_run(object(), run)
    assert called.get("wf") is True


def test_execute_ml_run_dispatches_backtest(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import ml_service

    called: dict[str, bool] = {}

    def fake_bt(db, run):  # noqa: ANN001
        called["bt"] = True
        return run

    monkeypatch.setattr(ml_service, "run_ml_backtest", fake_bt)

    run = _FakeRunObj("ml_backtest")
    ml_service.execute_ml_run(object(), run)
    assert called.get("bt") is True


def test_execute_ml_run_unknown_kind_raises() -> None:
    from app.services.ml_service import execute_ml_run

    run = _FakeRunObj("unknown_kind")
    with pytest.raises(ValueError, match="Unknown ML evaluation kind"):
        execute_ml_run(object(), run)


# ---------------------------------------------------------------------------
# ML_TASK_NAME is in the worker function list and enqueue uses it
# ---------------------------------------------------------------------------


def test_ml_task_name_constant() -> None:
    from app.jobs.tasks import ML_TASK_NAME, ml_task

    assert ML_TASK_NAME == "ml_task"
    assert ml_task.__name__ == ML_TASK_NAME


def test_ml_task_registered_in_worker() -> None:
    from app.jobs.tasks import ml_task
    from app.jobs.worker import WorkerSettings

    assert ml_task in WorkerSettings.functions


# ---------------------------------------------------------------------------
# MLWalkForwardRequest: eval_symbol validation
# ---------------------------------------------------------------------------


def test_walk_forward_req_eval_symbol_must_be_in_symbols() -> None:
    from pydantic import ValidationError

    from app.schemas.ml import MLWalkForwardRequest

    with pytest.raises(ValidationError, match="eval_symbol"):
        MLWalkForwardRequest(symbols=["SPY", "AAPL"], eval_symbol="MSFT")


def test_walk_forward_req_eval_symbol_in_symbols_ok() -> None:
    from app.schemas.ml import MLWalkForwardRequest

    req = MLWalkForwardRequest(symbols=["SPY", "AAPL"], eval_symbol="AAPL")
    assert req.eval_symbol == "AAPL"
    assert "AAPL" in req.symbols


# ---------------------------------------------------------------------------
# build_ml_inputs pure-transform path: mocked DB
# ---------------------------------------------------------------------------


def test_build_ml_inputs_quality_gate_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_ml_inputs raises BacktestRequestError when data quality fails."""
    import pandas as pd

    from app.services import ml_service
    from app.services.backtest_service import BacktestRequestError

    # Simulate DB returning rows but quality check failing.
    class _BadReport:
        passed = False
        errors = ["quality error"]

    monkeypatch.setattr(ml_service, "query_market_data", lambda db, sym: [object()])
    monkeypatch.setattr(
        ml_service, "orm_rows_to_frame",
        lambda rows: pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    )
    monkeypatch.setattr(ml_service, "check_data_quality", lambda frame: _BadReport())

    with pytest.raises(BacktestRequestError, match="quality"):
        ml_service.build_ml_inputs(object(), ["SPY"])


def test_build_ml_inputs_no_data_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_ml_inputs raises BacktestRequestError when the DB has no rows."""
    from app.services import ml_service
    from app.services.backtest_service import BacktestRequestError

    monkeypatch.setattr(ml_service, "query_market_data", lambda db, sym: [])

    with pytest.raises(BacktestRequestError, match="No market data"):
        ml_service.build_ml_inputs(object(), ["SPY"])
