"""Content-hash annotation cache key (Phase 5 M3/§5).

The cache key is the article's content hash plus the prompt version: an unchanged
article under an unchanged prompt is never re-sent, so re-running the pipeline
costs nothing for already-seen news. A revised body changes the content hash (a
new availability event, §2) and a prompt revision changes the version — either
busts the cache and re-bills, which is the honest, intended behavior.
"""

from __future__ import annotations

from collections.abc import Iterable


def cache_key(content_hash: str, prompt_version: str) -> str:
    """The cache key for an article's text under a given prompt version."""
    return f"{content_hash}:{prompt_version}"


def filter_uncached(
    items: Iterable[tuple[str, object]],
    existing_keys: set[str],
    *,
    prompt_version: str,
) -> list[object]:
    """Return the items whose (content_hash, prompt_version) is not yet cached.

    *items* is an iterable of ``(content_hash, payload)`` pairs; the returned list
    holds the payloads that still need annotation. Deduplicates within the input
    too — two articles sharing identical text (same content hash) annotate once.
    """
    seen: set[str] = set()
    out: list[object] = []
    for content_hash, payload in items:
        key = cache_key(content_hash, prompt_version)
        if key in existing_keys or key in seen:
            continue
        seen.add(key)
        out.append(payload)
    return out
