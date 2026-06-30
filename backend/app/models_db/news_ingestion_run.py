"""Audit record for one news-ingestion run (Phase 5 M2).

Mirrors :class:`IngestionRun` for market data: every backfill or incremental news
ingest writes one row so data problems are diagnosable and re-runs are traceable.
``items_dropped`` records how many fetched items the news data-quality gate
cleaned out (dedup, implausible timestamp, unattributable symbol) so a thin
written count is distinguishable from a thin *fetched* count.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models_db.base import Base


class NewsIngestionRun(Base):
    __tablename__ = "news_ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    range_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    range_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    items_fetched: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_written: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_dropped: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
