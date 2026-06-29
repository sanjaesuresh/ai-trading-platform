"""Audit record for one data-ingestion run.

Every invocation of the ingestion pipeline — backfill or incremental — writes one
row here so data problems are diagnosable and re-runs are traceable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models_db.base import Base


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # What was requested.
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    range_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    range_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Outcome counters — populated on completion.
    rows_fetched: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_written: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Status mirrors BacktestRun.status style: queued / running / completed / failed.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")

    # Error detail when status == "failed", NULL otherwise.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
