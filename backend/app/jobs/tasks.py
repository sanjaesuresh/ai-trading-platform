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
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.brokers.alpaca import AlpacaPaperBroker
from app.brokers.base import BrokerPort
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.data.ingestion.commands import run_backfill, run_incremental
from app.models_db.evaluation_run import EvaluationRun
from app.services.evaluation_service import (
    execute_evaluation_run,
    mark_failed,
    mark_running,
)
from app.services.paper_trading_service import (
    get_deployment,
    list_deployments,
    run_paper_cycle,
    run_reconcile_phase,
    run_submit_phase,
)

log = get_logger(__name__)


def _resolve_paper_broker() -> BrokerPort | None:
    """Build the Alpaca paper broker from settings, or None when no keys are
    configured (the daily runner then logs and skips — it cannot paper-trade
    without a real broker)."""
    settings = get_settings()
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        log.warning("No Alpaca paper keys configured; skipping paper run.")
        return None
    return AlpacaPaperBroker.from_settings(settings)


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


_PHASES = {
    "submit": run_submit_phase,
    "reconcile": run_reconcile_phase,
    "both": run_paper_cycle,
}


async def paper_run_task(
    ctx: dict[str, Any],
    *,
    deployment_id: int | None = None,
    trading_day: str | None = None,
    phase: str = "both",
    day_offset: int = 0,
) -> dict[str, Any]:
    """Run a paper-trading phase for one deployment (or all enabled deployments
    when ``deployment_id`` is None — the cron path).

    ``phase`` selects ``submit`` (pre-open, places opening-auction orders),
    ``reconcile`` (post-session, records fills + attributes slippage against the
    now-ingested modeled open), or ``both`` (a manual run-now). ``trading_day`` is
    an ISO date string; otherwise it is today (UTC) minus ``day_offset`` days — the
    reconcile cron uses offset 1 so it finalizes the *prior* session after that
    day's bar has been ingested. Skips cleanly when no Alpaca keys are configured.
    """
    runner = _PHASES.get(phase)
    if runner is None:
        raise ValueError(f"Unknown paper phase {phase!r}; expected submit/reconcile/both.")
    broker = _resolve_paper_broker()
    if broker is None:
        return {"skipped": "no_broker"}
    if trading_day:
        day = date.fromisoformat(trading_day)
    else:
        day = datetime.now(UTC).date() - timedelta(days=day_offset)

    session = SessionLocal()
    try:
        if deployment_id is not None:
            dep = get_deployment(session, deployment_id)
            deployments = [dep] if dep is not None else []
        else:
            deployments = [d for d in list_deployments(session) if d.enabled]

        results: list[dict[str, Any]] = []
        for dep in deployments:
            # Synchronous (DB + network); run off the event loop so the worker
            # heartbeat keeps firing. One job at a time → session stays single-threaded.
            res = await asyncio.to_thread(runner, session, broker, dep, day)
            results.append(
                {
                    "deployment_id": res.deployment_id,
                    "skipped": res.skipped,
                    "orders": res.num_orders,
                    "fills": res.num_fills,
                    "reconciliations": res.num_reconciliations,
                    "halted": res.halted,
                }
            )
        return {"trading_day": day.isoformat(), "phase": phase, "runs": results}
    finally:
        session.close()


async def paper_submit_cron(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron entry: pre-open SUBMIT pass for every enabled deployment (today)."""
    return await paper_run_task(ctx, phase="submit", day_offset=0)


async def paper_reconcile_cron(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron entry: RECONCILE the prior session (yesterday) after its bar has been
    ingested, so slippage is attributed against the real modeled open."""
    return await paper_run_task(ctx, phase="reconcile", day_offset=1)


# Task names, derived from the function objects so the enqueue side and the
# worker registry can never drift apart. Routes enqueue by these constants.
INGEST_TASK_NAME = ingest_task.__name__
EVALUATION_TASK_NAME = evaluation_task.__name__
PAPER_RUN_TASK_NAME = paper_run_task.__name__
