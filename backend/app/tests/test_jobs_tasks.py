"""DB-free tests for the background task functions.

The task bodies are driven directly with a fake ``ctx`` and a fake session/run,
matching the project's no-DB unit convention. Live-Redis enqueue and a real DB
status transition are manual integration steps (see the M6 plan), not unit tests.
"""

from __future__ import annotations

import asyncio

import pytest

from app.jobs import tasks

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeIngestionRun:
    def __init__(self, run_id: int, symbol: str, status: str) -> None:
        self.id = run_id
        self.symbol = symbol
        self.status = status


class _FakeEvaluationRun:
    def __init__(self) -> None:
        self.id = 7
        self.kind = "sweep"
        self.config: dict = {}
        self.status = "queued"
        self.error: str | None = None
        self.finished_at = None


class _FakeSession:
    """Records the run's status at each commit so transitions can be asserted."""

    def __init__(self, run: _FakeEvaluationRun) -> None:
        self._run = run
        self.transitions: list[str] = []
        self.closed = False

    def get(self, _model: object, _pk: object) -> _FakeEvaluationRun:
        return self._run

    def commit(self) -> None:
        self.transitions.append(self._run.status)

    def refresh(self, _obj: object) -> None:
        pass

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# ingest_task
# ---------------------------------------------------------------------------


def test_ingest_task_calls_incremental(monkeypatch: pytest.MonkeyPatch) -> None:
    """Incremental mode forwards symbols to run_incremental and returns a summary."""
    calls: dict[str, object] = {}

    def fake_incremental(symbols: list[str] | None = None) -> list[_FakeIngestionRun]:
        calls["symbols"] = symbols
        return [_FakeIngestionRun(1, "SPY", "completed")]

    monkeypatch.setattr(tasks, "run_incremental", fake_incremental)

    result = asyncio.run(tasks.ingest_task({}, mode="incremental", symbols=["SPY"]))

    assert calls["symbols"] == ["SPY"]
    assert result["mode"] == "incremental"
    assert result["runs"] == [{"id": 1, "symbol": "SPY", "status": "completed"}]


def test_ingest_task_bad_mode_raises() -> None:
    """An unknown mode is rejected before any work."""
    with pytest.raises(ValueError, match="mode"):
        asyncio.run(tasks.ingest_task({}, mode="sideways", symbols=None))


# ---------------------------------------------------------------------------
# evaluation_task
# ---------------------------------------------------------------------------


def test_evaluation_task_marks_running_then_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The task flips queued → running, runs the pipeline, then → completed."""
    run = _FakeEvaluationRun()
    session = _FakeSession(run)
    monkeypatch.setattr(tasks, "SessionLocal", lambda: session)

    def fake_execute(db: object, r: _FakeEvaluationRun) -> _FakeEvaluationRun:
        assert r.status == "running"  # running set before execution
        r.status = "completed"
        db.commit()  # type: ignore[attr-defined]
        return r

    monkeypatch.setattr(tasks, "execute_evaluation_run", fake_execute)

    result = asyncio.run(tasks.evaluation_task({}, evaluation_run_id=7))

    assert session.transitions == ["running", "completed"]
    assert run.status == "completed"
    assert result == {"evaluation_run_id": 7, "status": "completed"}
    assert session.closed


def test_evaluation_task_marks_failed_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pipeline error marks the run failed, records the error, and re-raises."""
    run = _FakeEvaluationRun()
    session = _FakeSession(run)
    monkeypatch.setattr(tasks, "SessionLocal", lambda: session)

    def fake_execute(db: object, r: _FakeEvaluationRun) -> _FakeEvaluationRun:
        raise RuntimeError("boom")

    monkeypatch.setattr(tasks, "execute_evaluation_run", fake_execute)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(tasks.evaluation_task({}, evaluation_run_id=7))

    assert run.status == "failed"
    assert run.error == "boom"
    assert session.closed
