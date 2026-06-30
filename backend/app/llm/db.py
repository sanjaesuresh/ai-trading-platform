"""Thin DB-I/O layer for LLM annotations (Phase 5 M3).

The only place in the llm package that touches SQLAlchemy. The annotation table
is the content-hash cache: ``articles_needing_annotation`` returns the articles
whose (content_hash, prompt_version) is not yet stored, and ``persist_results``
writes results with ON CONFLICT DO NOTHING so a re-run never re-bills.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.llm.client import AnnotationRequest, AnnotationResult
from app.models_db.news_annotation import NewsAnnotation
from app.models_db.news_article import NewsArticle


def existing_annotation_keys(session: Session, prompt_version: str) -> set[str]:
    """Return the set of ``content_hash`` already annotated under *prompt_version*."""
    rows = session.scalars(
        select(NewsArticle.content_hash)
        .join(
            NewsAnnotation,
            (NewsAnnotation.content_hash == NewsArticle.content_hash)
            & (NewsAnnotation.prompt_version == prompt_version),
        )
        .distinct()
    ).all()
    return set(rows)


def articles_needing_annotation(
    session: Session, prompt_version: str, *, limit: int | None = None
) -> list[AnnotationRequest]:
    """Return annotation requests for distinct article texts not yet annotated.

    Deduplicates on ``content_hash`` (identical text across symbols annotates
    once) and skips any text already annotated under *prompt_version*.
    """
    annotated = select(NewsAnnotation.content_hash).where(
        NewsAnnotation.prompt_version == prompt_version
    )
    stmt = (
        select(
            NewsArticle.content_hash,
            NewsArticle.headline,
            NewsArticle.body,
            NewsArticle.id,
        )
        .where(NewsArticle.content_hash.notin_(annotated))
        .order_by(NewsArticle.id)
    )
    rows = session.execute(stmt).all()

    seen: set[str] = set()
    requests: list[AnnotationRequest] = []
    for content_hash, headline, body, article_id in rows:
        if content_hash in seen:
            continue
        seen.add(content_hash)
        requests.append(
            AnnotationRequest(
                content_hash=content_hash,
                headline=headline or "",
                body=body or "",
                article_id=article_id,
            )
        )
        if limit is not None and len(requests) >= limit:
            break
    return requests


def persist_results(session: Session, results: list[AnnotationResult]) -> int:
    """Insert annotation results; ON CONFLICT DO NOTHING on the cache key.

    Returns the number of input results (Postgres rowcount is unreliable under
    DO NOTHING). Every result — including billed-but-failed ones — is persisted
    with its cost so the ablation's cost basis is complete.
    """
    if not results:
        return 0
    rows = []
    for r in results:
        ann = r.annotation
        rows.append(
            {
                "content_hash": r.content_hash,
                "prompt_version": r.prompt_version,
                "model_id": r.model_id,
                "article_id": r.article_id,
                "sentiment": ann.sentiment if ann else None,
                "relevance": ann.relevance if ann else None,
                "event_type": ann.event_type if ann else None,
                "rationale": ann.rationale if ann else None,
                "input_tokens": r.usage.input_tokens,
                "output_tokens": r.usage.output_tokens,
                "cache_read_tokens": r.usage.cache_read_tokens,
                "cache_write_tokens": r.usage.cache_write_tokens,
                "cost_usd": r.cost_usd,
                "batch": True,
                "status": r.status,
                "error": r.error,
            }
        )
    stmt = pg_insert(NewsAnnotation).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        constraint="uq_news_annotation_content_prompt"
    )
    session.execute(stmt)
    return len(rows)
