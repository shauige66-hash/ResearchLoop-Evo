"""Base record returned by every academic source before normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class RawWorkRecord:
    source: Literal["openalex", "crossref", "arxiv"]
    raw_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    abstract: str | None = None
    document_type: str | None = None
    is_review: bool = False
    review_evidence: str | None = None
    citation_count: int | None = None
    language: str | None = None
    relevance_score: float = 0.0
    source_url: str = ""
    oa_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
