"""Ingestion API: router mounted, bad mode → 400, trigger enqueues (DB-free).

The enqueue path is exercised with the queue seam monkeypatched, so no live Redis
is needed. List/detail round-trips against a real DB are a manual integration step.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.routes import ingestion
from app.main import create_app

client = TestClient(create_app())


def test_ingestion_routes_are_mounted() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/ingestion/run" in paths
    assert "/ingestion" in paths
    assert "/ingestion/{ingestion_id}" in paths


def test_ingestion_run_bad_mode_400() -> None:
    resp = client.post("/ingestion/run", json={"mode": "sideways"})
    assert resp.status_code == 400
    assert "Unknown ingest mode" in resp.json()["detail"]["message"]


def test_ingestion_run_enqueues(monkeypatch) -> None:
    calls: dict[str, object] = {}

    async def fake_enqueue(task_name: str, **kwargs: object) -> str:
        calls["task_name"] = task_name
        calls["kwargs"] = kwargs
        return "job-abc"

    monkeypatch.setattr(ingestion, "enqueue", fake_enqueue)

    resp = client.post(
        "/ingestion/run", json={"mode": "incremental", "symbols": ["SPY", "AAPL"]}
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body == {
        "job_id": "job-abc",
        "status": "queued",
        "mode": "incremental",
        "symbols": ["SPY", "AAPL"],
    }
    assert calls["task_name"] == "ingest_task"
    assert calls["kwargs"] == {"mode": "incremental", "symbols": ["SPY", "AAPL"]}


def test_ingestion_run_defaults_to_incremental_universe(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_enqueue(task_name: str, **kwargs: object) -> str:
        captured.update(kwargs)
        return "job-1"

    monkeypatch.setattr(ingestion, "enqueue", fake_enqueue)

    resp = client.post("/ingestion/run", json={})

    assert resp.status_code == 202
    assert captured == {"mode": "incremental", "symbols": None}
