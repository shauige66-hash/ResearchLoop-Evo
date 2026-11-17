"""Unified paper schema with enforced evidence provenance.

The design rule of this module: a field may only carry a value if the value can be
pointed back at something that was actually retrieved. That is what keeps the
product from pretending it read a full text it never fetched.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

EvidenceSource = Literal["abstract", "fulltext", "manual", "model_inference", "none"]
Confidence = Literal["high", "medium", "low", "unknown"]
EvidenceStatus = Literal[
    "abstract_grounded",
    "fulltext_grounded",
    "metadata_only",
    "partially_missing",
    "unknown",
]

# Fields whose content is derived from reading, not from bibliographic metadata.
EXTRACTED_FIELDS: tuple[str, ...] = (
    "research_problem",
    "method",
    "dataset",
    "evaluation_metrics",
    "findings",
    "limitations",
    "future_work",
)

# Sources that require a verbatim span taken from retrieved text.
SPAN_REQUIRED_SOURCES: frozenset[str] = frozenset({"abstract", "model_inference"})


class FieldEvidence(BaseModel):
    """One extracted field plus the evidence that justifies it."""

    value: str | None = None
    evidence_source: EvidenceSource = "none"
    evidence_span: str | None = None
    source_url: str | None = None
    confidence: Confidence = "unknown"
    updated_at: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> "FieldEvidence":
        has_value = self.value is not None and str(self.value).strip() != ""
        if self.evidence_source == "none" and has_value:
            raise ValueError(
                f"evidence_source='none' requires an empty value, got: {self.value!r}"
            )
        if self.evidence_source != "none" and not has_value:
            raise ValueError(
                f"evidence_source='{self.evidence_source}' requires a non-empty value"
            )
        if self.evidence_source in SPAN_REQUIRED_SOURCES and not (
            self.evidence_span and self.evidence_span.strip()
        ):
            raise ValueError(
                f"evidence_source='{self.evidence_source}' requires an evidence_span "
                "copied verbatim from the retrieved text"
            )
        if self.evidence_source != "none" and self.confidence == "unknown":
            raise ValueError("a grounded field must state a confidence level")
        return self

    @classmethod
    def unknown(cls) -> "FieldEvidence":
        return cls()

    @property
    def is_known(self) -> bool:
        return self.evidence_source != "none"


class Paper(BaseModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    publication_year: int | None = None
    venue: str | None = None
    doi: str | None = None
    abstract: str | None = None

    research_problem: FieldEvidence = Field(default_factory=FieldEvidence.unknown)
    method: FieldEvidence = Field(default_factory=FieldEvidence.unknown)
    dataset: FieldEvidence = Field(default_factory=FieldEvidence.unknown)
    evaluation_metrics: FieldEvidence = Field(default_factory=FieldEvidence.unknown)
    findings: FieldEvidence = Field(default_factory=FieldEvidence.unknown)
    limitations: FieldEvidence = Field(default_factory=FieldEvidence.unknown)
    future_work: FieldEvidence = Field(default_factory=FieldEvidence.unknown)

    source: Literal["openalex", "crossref", "arxiv"]
    source_url: str
    oa_url: str | None = None
    document_type: str | None = None
    is_review: bool = False
    review_evidence: str | None = None
    citation_count: int | None = None
    language: str | None = None
    relevance_score: float | None = None

    evidence_status: EvidenceStatus = "unknown"
    missing_fields: list[str] = Field(default_factory=list)
    duplicate_of: str | None = None
    merged_from: list[str] = Field(default_factory=list)
    retrieved_at: str = ""
    run_id: str | None = None

    @model_validator(mode="after")
    def _derive_evidence_state(self) -> "Paper":
        missing = [name for name in EXTRACTED_FIELDS if not getattr(self, name).is_known]
        self.missing_fields = missing
        grounded = [name for name in EXTRACTED_FIELDS if getattr(self, name).is_known]
        if not grounded:
            self.evidence_status = "metadata_only" if self.title else "unknown"
        elif any(
            getattr(self, name).evidence_source == "fulltext" for name in grounded
        ):
            self.evidence_status = "fulltext_grounded"
        elif missing:
            self.evidence_status = "partially_missing"
        else:
            self.evidence_status = "abstract_grounded"
        return self


class SourceError(BaseModel):
    """A real failure reported by a real upstream API, never swallowed."""

    source: str
    keyword: str | None = None
    status: int | None = None
    detail: str


class KeywordUsed(BaseModel):
    keyword: str
    origin: Literal["user", "system_expanded"]


class SearchMeta(BaseModel):
    retrieved_at: str
    duration_ms: int
    cache_hits: int
    requests_made: int
    sources_requested: list[str]
    sources_failed: list[str]
    keywords_used: list[KeywordUsed] = Field(default_factory=list)
    notice: str = (
        "Phase 1 extracts from retrieved metadata and abstracts only. "
        "No full text was read. Fields marked unknown were not found in the "
        "retrieved material."
    )
