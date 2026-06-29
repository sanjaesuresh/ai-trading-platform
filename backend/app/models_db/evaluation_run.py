"""The persisted record of one evaluation run (parameter sweep or walk-forward).

One row holds the whole aggregate: typed summary columns plus two JSON blobs —
``config`` (the full request) and ``results`` (the per-combination / per-split
detail and the distribution summary, including the baseline comparison). This
mirrors how ``BacktestRun`` stores its ``equity_curve`` as JSON; no per-combination
child rows in M5 (the JSON blob is reproducible and comparable). ``status`` is
``completed`` in M5; M6 will use ``queued``/``running``/``failed`` when the runner
moves behind a background job.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models_db.base import Base


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # "sweep" | "walk_forward"
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    objective: Mapped[str] = mapped_column(String(64), nullable=False)

    # config: the full request (param grid, run params, walk-forward policy).
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # results: per-combination / per-split detail + the distribution summary.
    results: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Error detail when status == "failed", NULL otherwise (M6).
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
