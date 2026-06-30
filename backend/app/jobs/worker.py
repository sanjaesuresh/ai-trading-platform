"""ARQ worker entrypoint: function registry, Redis wiring, and the nightly cron.

Run it with::

    arq app.jobs.worker.WorkerSettings

The compose ``worker`` service runs exactly that. One scheduled job — a nightly
incremental ingest over the configured universe — is the only cron in Phase 2;
everything else is enqueued on demand from the API.
"""

from __future__ import annotations

from arq import cron

from app.jobs.queue import redis_settings
from app.jobs.tasks import (
    evaluation_task,
    ingest_task,
    ml_task,
    paper_reconcile_cron,
    paper_run_task,
    paper_submit_cron,
)

# Nightly incremental ingest. Fixed off-hours UTC time, well after the US EOD
# close so a fresh daily bar is available from the provider. ``ingest_task``
# defaults to ``incremental`` over the universe when cron calls it with no args.
_NIGHTLY_INGEST_HOUR_UTC = 6
_NIGHTLY_INGEST_MINUTE_UTC = 0

# Daily paper run in two scheduled passes. SUBMIT runs pre-open (places the
# opening-auction orders for today); RECONCILE runs the next morning, AFTER the
# 06:00 ingest, for the *prior* session — so fills are attributed against that
# day's real modeled open rather than a fallback. Times are fixed UTC; the US open
# is 13:30 UTC (EDT) / 14:30 UTC (EST), so 13:00 is pre-open year-round. (DST drift
# and a non-calendar-aware trading day are documented limitations; a calendar-aware
# scheduler is future work.)
_PAPER_SUBMIT_HOUR_UTC = 13
_PAPER_RECONCILE_HOUR_UTC = 7


class WorkerSettings:
    """ARQ worker configuration discovered by the ``arq`` CLI."""

    functions = [
        ingest_task, evaluation_task, paper_run_task,
        paper_submit_cron, paper_reconcile_cron, ml_task,
    ]
    cron_jobs = [
        cron(
            ingest_task,
            hour=_NIGHTLY_INGEST_HOUR_UTC,
            minute=_NIGHTLY_INGEST_MINUTE_UTC,
        ),
        cron(paper_submit_cron, hour=_PAPER_SUBMIT_HOUR_UTC, minute=0),
        cron(paper_reconcile_cron, hour=_PAPER_RECONCILE_HOUR_UTC, minute=0),
    ]
    redis_settings = redis_settings()
