"""News endpoints: trigger ingest/annotate/ablation and read the audit trail (M7).

Triggering enqueues a background job and returns 202 with the job id — the work
runs on the worker, not in the request. All surfaces are simulated research;
LLM-derived sentiment is a research signal, not financial advice.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.jobs.queue import enqueue
from app.jobs.tasks import (
    ML_TASK_NAME,
    NEWS_ANNOTATE_TASK_NAME,
    NEWS_INGEST_TASK_NAME,
)
from app.llm.db import articles_needing_annotation
from app.llm.prompt import PROMPT_VERSION
from app.models_db.evaluation_run import EvaluationRun
from app.models_db.news_annotation import NewsAnnotation
from app.models_db.news_ingestion_run import NewsIngestionRun
from app.schemas.news import (
    JobEnqueueResponse,
    NewsAblationRequest,
    NewsAnnotateRequest,
    NewsAnnotationSummary,
    NewsIngestionRunSummary,
    NewsIngestRequest,
)

router = APIRouter(prefix="/news", tags=["news"])

_VALID_INGEST_MODES = ("backfill", "incremental")
_VALID_ANNOTATE_PHASES = ("submit", "collect", "both")


@router.post("/ingest", response_model=JobEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_news_ingest(req: NewsIngestRequest) -> JobEnqueueResponse:
    """Enqueue a news backfill or incremental ingest."""
    if req.mode not in _VALID_INGEST_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown mode {req.mode!r}; expected {list(_VALID_INGEST_MODES)}.",
        )
    job_id = await enqueue(NEWS_INGEST_TASK_NAME, mode=req.mode, symbols=req.symbols)
    return JobEnqueueResponse(
        job_id=job_id, status="queued", detail=f"news ingest ({req.mode})"
    )


@router.post("/annotate", response_model=JobEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_news_annotate(req: NewsAnnotateRequest) -> JobEnqueueResponse:
    """Enqueue an LLM annotation phase (submit / collect / both)."""
    if req.phase not in _VALID_ANNOTATE_PHASES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown phase {req.phase!r}; expected {list(_VALID_ANNOTATE_PHASES)}.",
        )
    job_id = await enqueue(NEWS_ANNOTATE_TASK_NAME, phase=req.phase)
    return JobEnqueueResponse(
        job_id=job_id, status="queued", detail=f"news annotate ({req.phase})"
    )


@router.post("/ablation", status_code=status.HTTP_202_ACCEPTED)
async def trigger_news_ablation(
    req: NewsAblationRequest, db: Session = Depends(get_db)
) -> dict[str, object]:
    """Create a queued news-ablation evaluation and enqueue it; returns its run id.

    The result is read back through the standard evaluation-detail endpoint
    (``GET /evaluations/{id}``), so the ablation view reuses that surface.
    """
    if req.eval_symbol not in req.symbols:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="eval_symbol must be one of symbols.",
        )
    run = EvaluationRun(
        kind="ml_news_ablation",
        symbol=req.eval_symbol,
        strategy_name="ml_classifier",
        status="queued",
        objective="sharpe_ratio",
        config=req.model_dump(),
        results={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    job_id = await enqueue(ML_TASK_NAME, evaluation_run_id=run.id)
    return {"evaluation_run_id": run.id, "job_id": job_id, "status": "queued"}


@router.get("/ingestion", response_model=list[NewsIngestionRunSummary])
def list_news_ingestion_runs(
    db: Session = Depends(get_db),
) -> list[NewsIngestionRunSummary]:
    """Return news-ingestion audit rows, newest first."""
    runs = db.scalars(
        select(NewsIngestionRun).order_by(NewsIngestionRun.id.desc())
    ).all()
    return [NewsIngestionRunSummary.model_validate(r) for r in runs]


@router.get("/ingestion/{ingestion_id}", response_model=NewsIngestionRunSummary)
def get_news_ingestion_run(
    ingestion_id: int, db: Session = Depends(get_db)
) -> NewsIngestionRunSummary:
    """Return one news-ingestion audit row, or 404 if unknown."""
    run = db.get(NewsIngestionRun, ingestion_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"News ingestion run {ingestion_id} not found.",
        )
    return NewsIngestionRunSummary.model_validate(run)


@router.get("/annotations/summary", response_model=NewsAnnotationSummary)
def annotation_summary(db: Session = Depends(get_db)) -> NewsAnnotationSummary:
    """Annotation coverage + honest billed cost under the live prompt version."""
    total = (
        db.scalar(
            select(func.count()).where(NewsAnnotation.prompt_version == PROMPT_VERSION)
        )
        or 0
    )
    ok = (
        db.scalar(
            select(func.count()).where(
                NewsAnnotation.prompt_version == PROMPT_VERSION,
                NewsAnnotation.status == "ok",
            )
        )
        or 0
    )
    cost = (
        db.scalar(
            select(func.coalesce(func.sum(NewsAnnotation.cost_usd), 0.0)).where(
                NewsAnnotation.prompt_version == PROMPT_VERSION
            )
        )
        or 0.0
    )
    pending = len(articles_needing_annotation(db, PROMPT_VERSION))
    return NewsAnnotationSummary(
        prompt_version=PROMPT_VERSION,
        total_annotations=int(total),
        ok_annotations=int(ok),
        failed_annotations=int(total) - int(ok),
        total_cost_usd=float(cost),
        pending_articles=pending,
    )
