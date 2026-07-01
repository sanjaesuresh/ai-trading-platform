"""Request/response contracts for the news + annotation + ablation endpoints (M7).

Triggering enqueues a background job and returns the job id; the audit rows
(``NewsIngestionRun``) and annotation summary are the record of what ran. All
surfaces are simulated research — LLM-derived sentiment is a research signal, not
financial advice.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class NewsIngestRequest(BaseModel):
    """Trigger a news-ingestion job."""

    mode: str = Field(
        default="incremental",
        description="'backfill' (full history) or 'incremental' (only new items).",
    )
    symbols: list[str] | None = Field(
        default=None, description="Symbols to ingest; omit for the configured universe."
    )


class NewsAnnotateRequest(BaseModel):
    """Trigger an annotation phase."""

    phase: str = Field(
        default="submit",
        description="'submit' (enqueue a batch), 'collect' (retrieve), or 'both'.",
    )


class JobEnqueueResponse(BaseModel):
    """Returned when a news/annotate job is accepted onto the queue."""

    job_id: str | None
    status: str
    detail: str


class NewsIngestionRunSummary(BaseModel):
    """One audit row describing a single symbol's news ingestion."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    symbol: str
    range_start: date | None
    range_end: date | None
    items_fetched: int | None
    items_written: int | None
    items_dropped: int | None
    status: str
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class NewsAnnotationSummary(BaseModel):
    """Aggregate annotation state: coverage and honest billed cost."""

    prompt_version: str
    total_annotations: int
    ok_annotations: int
    failed_annotations: int
    total_cost_usd: float
    pending_articles: int


class NewsAblationRequest(BaseModel):
    """Trigger a price-only vs price-plus-news ablation (§6)."""

    symbols: list[str] = Field(min_length=1)
    eval_symbol: str = Field(min_length=1, max_length=32)
    n_news_configs_tried: int = Field(
        default=1,
        ge=1,
        description="Number of news-feature configs searched; multiplies the news "
        "arm's deflated-Sharpe trial count.",
    )
    news_embargo: int = Field(default=1, ge=1)
    relevance_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    horizon: int = Field(default=5, ge=1)
    deadband: float = Field(default=0.0, ge=0.0)
    in_sample_dates: int = Field(default=504, ge=1)
    out_sample_dates: int = Field(default=126, ge=1)
    step_dates: int = Field(default=126, ge=1)
    fee_bps: float = Field(default=5.0, ge=0, le=1_000)
    slippage_bps: float = Field(default=5.0, ge=0, le=1_000)
    initial_capital: float = Field(default=100_000.0, gt=0)
    mc_runs: int = Field(default=200, ge=1)
    seed: int = Field(default=42)
