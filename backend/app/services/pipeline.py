"""Orchestration layer: multi-keyword × multi-source search with failure aggregation.

The pipeline:
1. Expand keywords (if enabled)
2. For each (keyword × source), call the source adapter
3. Collect all RawWorkRecord
4. Normalize to Paper
5. Dedupe (DOI + title similarity)
6. Rank (composite score)
7. Extract (heuristic from abstract)
8. Return SearchResponse with meta, papers, source_errors
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from ..models.paper import KeywordUsed, Paper, SearchMeta, SourceError
from ..models.schemas import SearchResponse, TopicInput
from .dedupe import dedupe
from .extract import extract_from_abstract
from .http import HttpFailure, get_client
from .normalize import normalize_record
from .rank import rank_papers
from .sources import arxiv, crossref, openalex

logger = logging.getLogger(__name__)


def _expand_keywords(topic: TopicInput) -> list[KeywordUsed]:
    """Expand user keywords with system-generated terms from topic.

    Simple heuristic: split topic into words, filter stopwords, keep unique.
    """
    keywords: list[KeywordUsed] = []
    seen: set[str] = set()

    # User-provided keywords first
    for kw in topic.keywords:
        if kw not in seen:
            keywords.append(KeywordUsed(keyword=kw, origin="user"))
            seen.add(kw)

    # System expansion: split topic into meaningful terms
    if topic.expand_keywords and topic.topic:
        # Remove punctuation, split on whitespace
        import re

        words = re.findall(r"[a-zA-Z\u4e00-\u9fff]+", topic.topic.lower())
        # Filter stopwords
        stopwords = {
            "the",
            "a",
            "an",
            "in",
            "on",
            "at",
            "for",
            "of",
            "with",
            "by",
            "to",
            "and",
            "or",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "can",
            "this",
            "that",
            "these",
            "those",
            "i",
            "you",
            "he",
            "she",
            "it",
            "we",
            "they",
            "what",
            "which",
            "who",
            "whom",
            "when",
            "where",
            "why",
            "how",
        }
        for word in words:
            if word not in stopwords and word not in seen and len(word) > 2:
                keywords.append(KeywordUsed(keyword=word, origin="system_expanded"))
                seen.add(word)

    return keywords[:6]  # cap at 6 keywords


async def _search_source(
    source: str, topic: TopicInput, keyword: str, refresh: bool
) -> tuple[list[Paper], SourceError | None]:
    """Search a single source for a single keyword. Returns (papers, error)."""
    try:
        if source == "openalex":
            records = await openalex.search_openalex(topic, keyword, refresh)
        elif source == "crossref":
            records = await crossref.search_crossref(topic, keyword, refresh)
        elif source == "arxiv":
            records = await arxiv.search_arxiv(topic, keyword, refresh)
        else:
            raise ValueError(f"unknown source: {source}")

        papers = [normalize_record(r) for r in records]
        return papers, None
    except HttpFailure as exc:
        error = SourceError(
            source=source,
            keyword=keyword,
            status=exc.status,
            detail=exc.detail,
        )
        return [], error
    except Exception as exc:
        # Attribute unexpected failures to the real source instead of "unknown",
        # and keep the traceback in the log so the cause stays diagnosable.
        logger.exception("Unexpected failure in %s for keyword %r", source, keyword)
        return [], SourceError(
            source=source,
            keyword=keyword,
            status=None,
            detail=f"{type(exc).__name__}: {exc}",
        )


async def search_pipeline(topic: TopicInput) -> SearchResponse:
    """Run the full search pipeline for a topic.

    Returns SearchResponse with papers, meta, and source_errors.
    """
    client = get_client()
    client.reset_stats()
    start_time = time.monotonic()

    # Generate run_id
    run_id = f"run_{int(time.time() * 1000)}"
    project_id = f"proj_{int(time.time() * 1000)}"

    # Expand keywords
    keywords = _expand_keywords(topic)
    if not keywords:
        keywords = [KeywordUsed(keyword=topic.topic, origin="user")]

    # Collect all source errors
    source_errors: list[SourceError] = []
    all_papers: list[Paper] = []

    # For each (keyword × source), search in parallel
    tasks: list[asyncio.Task] = []
    for kw in keywords:
        for source in topic.sources:
            tasks.append(
                asyncio.create_task(_search_source(source, topic, kw.keyword, topic.refresh))
            )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            # Shouldn't happen since we catch HttpFailure inside, but handle gracefully
            source_errors.append(
                SourceError(
                    source="unknown",
                    keyword=None,
                    status=None,
                    detail=str(result),
                )
            )
            continue
        papers, error = result
        if error:
            source_errors.append(error)
        all_papers.extend(papers)

    # Dedupe
    unique_papers = dedupe(all_papers)

    # Rank
    keyword_list = [kw.keyword for kw in keywords]
    ranked_papers = rank_papers(unique_papers, keyword_list, topic.prefer_reviews)

    # Truncate to top_k
    ranked_papers = ranked_papers[: topic.top_k]

    # Extract (heuristic from abstract)
    for paper in ranked_papers:
        extract_from_abstract(paper)
        paper.run_id = run_id

    # Build meta
    duration_ms = int((time.monotonic() - start_time) * 1000)
    stats = client.stats
    sources_failed = list({e.source for e in source_errors})

    meta = SearchMeta(
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        duration_ms=duration_ms,
        cache_hits=stats["cache_hits"],
        requests_made=stats["requests_made"],
        sources_requested=topic.sources,
        sources_failed=sources_failed,
        keywords_used=keywords,
    )

    return SearchResponse(
        run_id=run_id,
        project_id=project_id,
        topic=topic.topic,
        meta=meta.model_dump(),
        papers=ranked_papers,
        source_errors=source_errors,
        stats=stats,
    )
