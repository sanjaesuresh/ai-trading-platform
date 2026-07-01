"""News API: routers mounted, validation, and enqueue (DB-free).

The enqueue path is exercised with the queue seam monkeypatched, so no live Redis
or DB is needed — the trigger routes validate and enqueue before any query runs.
Mirrors test_ingestion_api.py.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.routes import news
from app.main import create_app

client = TestClient(create_app())


def _fake_enqueue():
    async def fake_enqueue(task_name: str, **kwargs: object) -> str:
        return f"job-{task_name}"

    return fake_enqueue


def test_ingest_bad_mode_is_400() -> None:
    resp = client.post("/news/ingest", json={"mode": "wat"})
    assert resp.status_code == 400


def test_ingest_enqueues(monkeypatch) -> None:
    monkeypatch.setattr(news, "enqueue", _fake_enqueue())
    resp = client.post("/news/ingest", json={"mode": "incremental"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["job_id"] == "job-news_ingest_task"


def test_annotate_bad_phase_is_400() -> None:
    resp = client.post("/news/annotate", json={"phase": "nope"})
    assert resp.status_code == 400


def test_annotate_enqueues(monkeypatch) -> None:
    monkeypatch.setattr(news, "enqueue", _fake_enqueue())
    resp = client.post("/news/annotate", json={"phase": "submit"})
    assert resp.status_code == 202
    assert resp.json()["job_id"] == "job-news_annotate_task"


def test_ablation_requires_eval_symbol_in_symbols() -> None:
    resp = client.post(
        "/news/ablation",
        json={"symbols": ["AAPL"], "eval_symbol": "MSFT"},
    )
    assert resp.status_code == 400
