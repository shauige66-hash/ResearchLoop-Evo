"""Request/response models for the Literature Discovery API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .paper import EvidenceSource, FieldEvidence, KeywordUsed, Paper, SourceError

DocumentType = Literal[
    "article",
    "review",
    "conference-paper",
    "book-chapter",
    "preprint",
    "dissertation",
    "report",
    "other",
]


class TopicInput(BaseModel):
    """Everything a researcher declares before a search runs."""

    topic: str = Field(min_length=3, max_length=400)
    field: str | None = Field(default=None, max_length=120)
    keywords: list[str] = Field(default_factory=list)
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    document_types: list[DocumentType] = Field(default_factory=list)
    prefer_reviews: bool = False
    sources: list[Literal["openalex", "crossref", "arxiv"]] = Field(
        default_factory=lambda: ["openalex", "crossref"]
    )
    top_k: int = Field(default=40, ge=1, le=200)
    expand_keywords: bool = True
    refresh: bool = Field(default=False, description="bypass the HTTP cache")

    @field_validator("keywords", mode="before")
    @classmethod
    def _clean_keywords(cls, raw: object) -> list[str]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ValueError("keywords must be a list of strings")
        out: list[str] = []
        for item in raw:
            text = str(item).strip()
            if text and text not in out:
                out.append(text)
        return out

    @model_validator(mode="after")
    def _check_range(self) -> "TopicInput":
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from must be <= year_to")
        if not self.sources:
            raise ValueError("select at least one source")
        return self


class SearchResponse(BaseModel):
    run_id: str
    project_id: str
    topic: str
    meta: dict
    papers: list[Paper]
    source_errors: list[SourceError] = Field(default_factory=list)
    stats: dict


class RunSummary(BaseModel):
    run_id: str
    project_id: str
    topic: str
    created_at: str
    finished_at: str | None
    status: str
    paper_count: int
    sources: list[str]
    failed_sources: list[str]


class PaperListResponse(BaseModel):
    papers: list[Paper]
    total: int
    page: int
    page_size: int


class FieldPatch(BaseModel):
    value: str | None = None
    evidence_source: EvidenceSource
    evidence_span: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _reject_remote_fulltext(self) -> "FieldPatch":
        if self.evidence_source == "fulltext" and not (
            self.evidence_span and self.evidence_span.strip()
        ):
            raise ValueError(
                "fulltext edits must quote the passage that supports them"
            )
        return self


class MatrixColumn(BaseModel):
    key: str
    label: str


class MatrixCell(BaseModel):
    paper_id: str
    column: str
    evidence: FieldEvidence
    edited_at: str | None = None


class MatrixRow(BaseModel):
    paper: Paper
    cells: dict[str, MatrixCell]


class MatrixResponse(BaseModel):
    columns: list[MatrixColumn]
    rows: list[MatrixRow]
    generated_at: str
    notice: str


class MatrixRequest(BaseModel):
    paper_ids: list[str] = Field(min_length=1, max_length=50)


class ReportRequest(BaseModel):
    run_id: str | None = None
    paper_ids: list[str] = Field(default_factory=list)


class ReportSection(BaseModel):
    id: str
    title: str
    kind: Literal["facts", "author_claims", "system_inference", "mixed"]
    paragraphs: list[str]
    paper_ids: list[str] = Field(default_factory=list)


class ReportResponse(BaseModel):
    report_id: str
    topic: str
    generated_at: str
    paper_count: int
    sections: list[ReportSection]
    markdown: str
    caveats: list[str]
