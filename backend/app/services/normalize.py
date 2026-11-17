"""Normalize raw records from different sources into unified Paper schema.

Each Paper carries provenance: source, source_url, and evidence_status.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from ..models.paper import Paper
from .sources.base import RawWorkRecord


def canonical_doi(doi: str | None) -> str | None:
    """Normalize DOI to bare form (10.xxxx/yyyy) without URL prefix."""
    if not doi:
        return None
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
    return doi.lower() if doi else None


def _best_relevance(primary: float | None, secondary: float | None) -> float | None:
    """Keep the highest relevance reported by any source; None means none did."""
    scores = [s for s in (primary, secondary) if s is not None]
    return max(scores) if scores else None


def normalize_record(record: RawWorkRecord, run_id: str | None = None) -> Paper:
    """Convert a RawWorkRecord into a Paper with full provenance."""
    paper_id = f"{record.source}:{record.raw_id}"
    doi = canonical_doi(record.doi)

    return Paper(
        paper_id=paper_id,
        title=record.title,
        authors=record.authors,
        publication_year=record.year,
        venue=record.venue,
        doi=doi,
        abstract=record.abstract,
        source=record.source,
        source_url=record.source_url,
        oa_url=record.oa_url,
        document_type=record.document_type,
        is_review=record.is_review,
        review_evidence=record.review_evidence,
        citation_count=record.citation_count,
        language=record.language,
        relevance_score=record.relevance_score,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        run_id=run_id,
    )


def merge_records(primary: RawWorkRecord, secondary: RawWorkRecord) -> RawWorkRecord:
    """Merge two records for the same paper, preferring non-null fields.

    Used when the same paper appears in multiple sources. We keep the primary
    record's identity but fill gaps from the secondary.
    """
    merged = RawWorkRecord(
        source=primary.source,
        raw_id=primary.raw_id,
        title=primary.title or secondary.title,
        authors=primary.authors or secondary.authors,
        year=primary.year or secondary.year,
        venue=primary.venue or secondary.venue,
        doi=primary.doi or secondary.doi,
        abstract=primary.abstract or secondary.abstract,
        document_type=primary.document_type or secondary.document_type,
        is_review=primary.is_review or secondary.is_review,
        review_evidence=primary.review_evidence or secondary.review_evidence,
        citation_count=primary.citation_count or secondary.citation_count,
        language=primary.language or secondary.language,
        relevance_score=_best_relevance(primary.relevance_score, secondary.relevance_score),
        source_url=primary.source_url or secondary.source_url,
        oa_url=primary.oa_url or secondary.oa_url,
        raw={**secondary.raw, **primary.raw},
    )
    return merged
