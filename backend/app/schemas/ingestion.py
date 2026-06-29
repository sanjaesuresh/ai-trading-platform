"""Request/response contracts for the ingestion trigger + audit endpoints (M6).

Triggering ingestion enqueues a background job and returns immediately with the
job id; the audit rows (``IngestionRun``) are the record of what actually ran.
``mode`` is validated in the route (not as an enum) so an unknown mode is a clean
400 business error, matching the rest of the API.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class IngestionRunRequest(BaseModel):
    """Trigger a data-ingestion job."""

    mode: str = Field(
        default="incremental",
        description="'backfill' (full history) or 'incremental' (only new bars).",
    )
    symbols: list[str] | None = Field(
        default=None,
        description="Symbols to ingest; omit to use the configured universe.",
    )


class IngestionEnqueueResponse(BaseModel):
    """Returned when an ingestion job is accepted onto the queue."""

    job_id: str | None
    status: str
    mode: str
    symbols: list[str] | None


class IngestionRunSummary(BaseModel):
    """One audit row describing a single symbol's ingestion."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    symbol: str
    range_start: date | None
    range_end: date | None
    rows_fetched: int | None
    rows_written: int | None
    status: str
    error: str | None
    created_at: datetime
    finished_at: datetime | None
