"""Background task functions run by the ARQ worker.

Each task owns its own ``SessionLocal`` session (never request-scoped state) and
either runs to completion or records the failure on the audit/run row before
re-raising so the worker logs it. Ingest is idempotent: the ``(symbol, timestamp)``
upsert means a retry never duplicates bars. An evaluation re-run repeats the work
and overwrites ``results`` (also idempotent in effect).

The pipelines and ingest commands are synchronous; the worker processes one job
at a time, so calling them inline (rather than offloading to a thread) keeps the
session single-threaded and is fine for this single-user tool.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.data.ingestion.commands import run_backfill, run_incremental
from app.models_db.evaluation_run import EvaluationRun
from app.services.evaluation_service import (
    execute_evaluation_run,
    mark_failed,
    mark_running,
)

log = get_logger(__name__)


async def ingest_task(
    ctx: dict[str, Any], *, mode: str = "incremental", symbols: list[str] | None = None
) -> dict[str, Any]:
    """Run a backfill or incremental ingest over *symbols* (None → the universe).

    Returns a small summary of the resulting ``IngestionRun`` ids/statuses. The
    underlying command opens and closes its own session. ``mode`` defaults to
    ``incremental`` so the nightly cron (which passes no args) does the safe,
    cheap update; a full ``backfill`` is always an explicit request.
    """
    # Resolve via the module globals (not a frozen map) so the choice stays
    # monkeypatchable and adding a mode is a one-line change.
    if mode == "backfill":
        command = run_backfill
    elif mode == "incremental":
        command = run_incremental
    else:
        raise ValueError(
            f"Unknown ingest mode {mode!r}; expected 'backfill' or 'incremental'."
        )
    log.info("Ingest task: mode=%s symbols=%s", mode, symbols)
    # The command is synchronous (network + DB); run it off the event loop so the
    # worker stays responsive and ARQ's heartbeat/timeout can still fire.
    runs = await asyncio.to_thread(command, symbols)
    return {
        "mode": mode,
        "runs": [{"id": r.id, "symbol": r.symbol, "status": r.status} for r in runs],
    }


async def evaluation_task(
    ctx: dict[str, Any], *, evaluation_run_id: int
) -> dict[str, Any]:
    """Run a queued evaluation row: queued → running → completed/failed.

    Loads the row the enqueue endpoint created, flips it to ``running``, runs the
    matching pipeline in place from the stored ``config``, then marks it
    ``completed``. On error the row is marked ``failed`` (with the message) and the
    exception is re-raised so the worker sees the failure.
    """
    session = SessionLocal()
    try:
        run = session.get(EvaluationRun, evaluation_run_id)
        if run is None:
            raise ValueError(f"EvaluationRun {evaluation_run_id} not found.")
        mark_running(session, run)
        try:
            # Synchronous, CPU-bound pipeline — run off the event loop. The task
            # processes one job at a time, so the session stays single-threaded.
            await asyncio.to_thread(execute_evaluation_run, session, run)
        except Exception as exc:
            mark_failed(session, run, str(exc))
            raise
        return {"evaluation_run_id": run.id, "status": run.status}
    finally:
        session.close()


# Task names, derived from the function objects so the enqueue side and the
# worker registry can never drift apart. Routes enqueue by these constants.
INGEST_TASK_NAME = ingest_task.__name__
EVALUATION_TASK_NAME = evaluation_task.__name__
