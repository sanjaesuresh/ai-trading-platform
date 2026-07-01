"""Two-phase LLM annotation orchestration (Phase 5 M7/§5).

Mirrors the paper submit/reconcile split. The Batch API is asynchronous, so a
batch submitted on one pass is collected on a later one:

- **submit**: find articles needing annotation under the live prompt version,
  submit them as one batch. With the real Claude client the batch id is parked in
  a ``SystemFlag`` for a later collect pass. With the offline stub (no key) there
  is nothing to wait for, so it collects and persists synchronously — stub batches
  don't survive across worker processes, and no-key mode should still work
  end-to-end.
- **collect**: retrieve every parked batch; persist the completed ones (every
  result, incl. billed-but-failed, so the cost basis is honest), drop them from the
  pending list, and leave still-running batches for the next pass.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.client import AnnotationClient, build_annotation_client
from app.llm.db import articles_needing_annotation, persist_results
from app.llm.prompt import PROMPT_VERSION
from app.models_db.paper_trading import SystemFlag

log = get_logger(__name__)

_PENDING_FLAG = "news_annotation_pending_batches"


@dataclass
class AnnotateSummary:
    phase: str
    requested: int
    collected: int
    persisted: int
    pending_batches: int


def _build_client() -> AnnotationClient:
    settings = get_settings()
    return build_annotation_client(settings.anthropic_api_key, settings.annotation_model)


def _get_pending(session: Session) -> list[str]:
    flag = session.get(SystemFlag, _PENDING_FLAG)
    if flag is None:
        return []
    return list(flag.value.get("batch_ids", []))


def _set_pending(session: Session, batch_ids: list[str]) -> None:
    flag = session.get(SystemFlag, _PENDING_FLAG)
    if flag is None:
        session.add(SystemFlag(name=_PENDING_FLAG, value={"batch_ids": list(batch_ids)}))
    else:
        flag.value = {"batch_ids": list(batch_ids)}
    session.commit()


def run_annotate_submit(
    session: Session, *, client: AnnotationClient | None = None, limit: int | None = None
) -> AnnotateSummary:
    """Submit the day's un-annotated articles as one batch (§5 submit pass)."""
    client = client or _build_client()
    requests = articles_needing_annotation(session, PROMPT_VERSION, limit=limit)
    if not requests:
        return AnnotateSummary("submit", 0, 0, 0, len(_get_pending(session)))

    batch_id = client.submit_batch(requests)

    if client.name == "stub":
        results = client.collect_batch(batch_id) or []
        persisted = persist_results(session, results)
        session.commit()
        log.info("News annotate (stub): %d requested, %d persisted.", len(requests), persisted)
        return AnnotateSummary("submit", len(requests), len(results), persisted, 0)

    pending = _get_pending(session)
    pending.append(batch_id)
    _set_pending(session, pending)
    log.info("News annotate submit: %d requested, batch %s parked.", len(requests), batch_id)
    return AnnotateSummary("submit", len(requests), 0, 0, len(pending))


def run_annotate_collect(
    session: Session, *, client: AnnotationClient | None = None
) -> AnnotateSummary:
    """Collect + persist completed batches; leave still-running ones (§5 collect)."""
    client = client or _build_client()
    pending = _get_pending(session)
    if not pending:
        return AnnotateSummary("collect", 0, 0, 0, 0)

    still_running: list[str] = []
    collected = 0
    persisted = 0
    for batch_id in pending:
        results = client.collect_batch(batch_id)
        if results is None:
            still_running.append(batch_id)  # not finished yet
            continue
        collected += len(results)
        persisted += persist_results(session, results)
    session.commit()
    _set_pending(session, still_running)
    log.info(
        "News annotate collect: %d collected, %d persisted, %d still running.",
        collected, persisted, len(still_running),
    )
    return AnnotateSummary("collect", 0, collected, persisted, len(still_running))
