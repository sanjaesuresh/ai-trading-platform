"""The ARQ worker registers both task functions and a nightly cron job.

Importing WorkerSettings does not touch Redis (the pool only opens when the
worker runs), so this is a pure unit check.
"""

from __future__ import annotations

from app.jobs.tasks import evaluation_task, ingest_task
from app.jobs.worker import WorkerSettings


def test_worker_registers_tasks() -> None:
    assert ingest_task in WorkerSettings.functions
    assert evaluation_task in WorkerSettings.functions


def test_worker_has_a_cron_job() -> None:
    assert len(WorkerSettings.cron_jobs) >= 1
