"""ARQ connection configuration and the central enqueue seam.

Routes depend only on ``enqueue``; they never touch ARQ directly. Swapping the
queue backend is one file.
"""

from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings


def redis_settings() -> RedisSettings:
    """Build ARQ ``RedisSettings`` from the configured ``REDIS_URL``."""
    return RedisSettings.from_dsn(get_settings().redis_url)


async def enqueue(task_name: str, /, *args: object, **kwargs: object) -> str | None:
    """Enqueue *task_name* with *args*/*kwargs* and return the ARQ job id.

    Opens a short-lived pool, enqueues exactly one job, then closes the pool.
    Returns ``None`` if ARQ returns no job object (e.g., duplicate-job guard).
    """
    pool: ArqRedis = await create_pool(redis_settings())
    try:
        # ARQ types enqueue_job's **kwargs as its own keyword-only options
        # (_job_id, _defer_until, …); our task kwargs are passed through by name.
        job = await pool.enqueue_job(task_name, *args, **kwargs)  # type: ignore[arg-type]
        return job.job_id if job else None
    finally:
        await pool.aclose()
