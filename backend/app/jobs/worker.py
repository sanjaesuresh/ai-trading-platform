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
from app.jobs.tasks import evaluation_task, ingest_task

# Nightly incremental ingest. Fixed off-hours UTC time, well after the US EOD
# close so a fresh daily bar is available from the provider. ``ingest_task``
# defaults to ``incremental`` over the universe when cron calls it with no args.
_NIGHTLY_INGEST_HOUR_UTC = 6
_NIGHTLY_INGEST_MINUTE_UTC = 0


class WorkerSettings:
    """ARQ worker configuration discovered by the ``arq`` CLI."""

    functions = [ingest_task, evaluation_task]
    cron_jobs = [
        cron(
            ingest_task,
            hour=_NIGHTLY_INGEST_HOUR_UTC,
            minute=_NIGHTLY_INGEST_MINUTE_UTC,
        )
    ]
    redis_settings = redis_settings()
