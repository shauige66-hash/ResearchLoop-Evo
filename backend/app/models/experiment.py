"""Minimal experiment lab: one agent-evolution template, real arms, honest metrics.

The hypothesis under test is that experience-driven query strategy evolution
improves retrieval coverage on unseen subtopics while controlling extra retrieval
cost. Nothing here assumes the hypothesis holds; the evaluator decides.

Two invariants are enforced by the models rather than by convention:
- coverage is measured against a human-confirmed reference set, never against an
  invented ground truth, and an unconfirmed set yields no coverage number at all;
- a run records the strategy snapshot it actually used, so replays stay comparable.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .skill import SearchStrategy

Split = Literal["development", "validation", "holdout"]
Arm = Literal["baseline", "candidate"]
RunStatus = Literal["pending", "running", "completed", "failed", "awaiting_reference_set"]
ReferenceStatus = Literal["awaiting_reference_set", "confirmed"]

TEMPLATE_ID = "agent_evolution_retrieval"

HYPOTHESIS = (
    "Experience-driven query strategy evolution improves literature retrieval "
    "coverage on unseen subtopics while controlling extra retrieval cost."
)

EVALUATOR_VERSION = "1.0.0"

COVERAGE_NOTICE = (
    "Reference Coverage@K is measured against the human-confirmed reference set for "
    "this benchmark case only. It is not the absolute recall of the academic field."
)


def fingerprint(payload: object) -> str:
    """Stable sha256 over canonical JSON, used to detect silent data changes."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class BenchmarkReference(BaseModel):
    """A real DOI whose existence was checked against Crossref or OpenAlex."""

    doi: str
    title: str = ""
    source_url: str = ""
    publication_year: int | None = None
    verified_via: Literal["crossref", "openalex", "manual"] = "manual"
    verified_at: str = ""
    # Metadata verification alone is not ground truth: a human must confirm that
    # this paper really belongs to the case's reference set.
    confirmed_by: str | None = None
    confirmed_at: str | None = None

    @property
    def is_confirmed(self) -> bool:
        return bool(self.confirmed_by)


class BenchmarkCase(BaseModel):
    case_id: str
    topic: str
    query: str
    reference_dois: list[str] = Field(default_factory=list)
    split: Split = "development"
    source: Literal["manual", "derived_from_run"] = "manual"
    verified_by: str | None = None
    created_at: str = ""
    notes: str = ""
    references: list[BenchmarkReference] = Field(default_factory=list)

    @property
    def confirmed_dois(self) -> list[str]:
        return [r.doi for r in self.references if r.is_confirmed]

    @property
    def reference_status(self) -> ReferenceStatus:
        return "confirmed" if self.confirmed_dois else "awaiting_reference_set"

    @model_validator(mode="after")
    def _references_must_match_dois(self) -> "BenchmarkCase":
        declared = {d.lower() for d in self.reference_dois}
        for ref in self.references:
            if ref.doi.lower() not in declared:
                raise ValueError(f"reference {ref.doi} is not listed in reference_dois")
        return self


class ExperimentSpec(BaseModel):
    """The frozen protocol both arms must obey."""

    spec_id: str
    template_id: str = TEMPLATE_ID
    hypothesis: str = HYPOTHESIS
    gap_id: str | None = None
    case_ids: list[str] = Field(min_length=1)
    sources: list[Literal["openalex", "crossref", "arxiv"]] = Field(
        default_factory=lambda: ["openalex", "crossref", "arxiv"]
    )
    year_from: int | None = None
    year_to: int | None = None
    top_k: int = Field(default=20, ge=1, le=200)
    # Hard ceiling on API requests per arm per case. A candidate cannot raise it.
    max_api_requests: int = Field(default=6, ge=1, le=60)
    use_cache: bool = True
    baseline_version_id: str
    candidate_version_id: str
    created_at: str = ""
    created_by: str = "human"
    # Holdout is a one-shot final check: it stays closed until the candidate is
    # locked, and it never reopens afterwards.
    candidate_locked_at: str | None = None

    @model_validator(mode="after")
    def _arms_must_differ(self) -> "ExperimentSpec":
        if self.baseline_version_id == self.candidate_version_id:
            raise ValueError("baseline and candidate must be different skill versions")
        return self


class EvaluationReport(BaseModel):
    """Computed by the independent evaluator from a run's raw retrieval record."""

    status: Literal["computed", "awaiting_reference_set"]
    coverage_at_k: float | None = None
    hit_references: list[str] = Field(default_factory=list)
    missed_references: list[str] = Field(default_factory=list)
    api_query_count: int = 0
    cache_hits: int = 0
    unique_paper_count: int = 0
    execution_time_ms: int = 0
    reference_set_size: int = 0
    reference_fingerprint: str = ""
    dataset_fingerprint: str = ""
    evaluator_version: str = EVALUATOR_VERSION
    computed_at: str = ""
    notice: str = COVERAGE_NOTICE

    @model_validator(mode="after")
    def _no_coverage_without_references(self) -> "EvaluationReport":
        if self.status == "awaiting_reference_set" and self.coverage_at_k is not None:
            raise ValueError("coverage must not be reported without a confirmed reference set")
        if self.status == "computed" and self.reference_set_size == 0:
            raise ValueError("a computed report needs a non-empty confirmed reference set")
        return self


class ExperimentRun(BaseModel):
    run_id: str
    spec_id: str
    case_id: str
    arm: Arm
    skill_version_id: str
    # Frozen copy: later edits to the registry cannot rewrite history.
    skill_snapshot: SearchStrategy
    queries_used: list[str] = Field(default_factory=list)
    status: RunStatus = "pending"
    started_at: str = ""
    finished_at: str | None = None
    api_request_count: int = 0
    cache_hits: int = 0
    unique_paper_count: int = 0
    execution_time_ms: int = 0
    retrieved_dois: list[str] = Field(default_factory=list)
    retrieved_paper_ids: list[str] = Field(default_factory=list)
    source_errors: list[dict] = Field(default_factory=list)
    raw_snapshot_path: str | None = None
    evaluation: EvaluationReport | None = None
    error: str | None = None
    literature_run_id: str | None = None

    @property
    def unhandled_api_errors(self) -> list[dict]:
        return [e for e in self.source_errors if e.get("status") != 429]

    @property
    def total_api_queries(self) -> int:
        """Network requests plus cache hits: caching must not hide retrieval cost."""
        return self.api_request_count + self.cache_hits


class ExperimentComparison(BaseModel):
    spec_id: str
    case_id: str
    split: Split
    baseline: ExperimentRun | None = None
    candidate: ExperimentRun | None = None
    coverage_delta: float | None = None
    request_ratio: float | None = None
    reference_status: ReferenceStatus = "awaiting_reference_set"
    notice: str = COVERAGE_NOTICE


class BenchmarkCaseCreate(BaseModel):
    topic: str = Field(min_length=3, max_length=400)
    query: str = Field(min_length=3, max_length=400)
    reference_dois: list[str] = Field(default_factory=list)
    split: Split | None = None
    notes: str = ""
    source: Literal["manual", "derived_from_run"] = "manual"
    verify_references: bool = True


class ReferenceAddRequest(BaseModel):
    dois: list[str] = Field(min_length=1, max_length=50)


class ReferenceConfirmRequest(BaseModel):
    confirmed_by: str = Field(min_length=1, max_length=120)
    dois: list[str] = Field(default_factory=list)


class SpecCreateRequest(BaseModel):
    case_ids: list[str] = Field(min_length=1)
    baseline_version_id: str
    candidate_version_id: str
    gap_id: str | None = None
    sources: list[Literal["openalex", "crossref", "arxiv"]] = Field(
        default_factory=lambda: ["openalex", "crossref", "arxiv"]
    )
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    top_k: int = Field(default=20, ge=1, le=200)
    max_api_requests: int = Field(default=6, ge=1, le=60)
    use_cache: bool = True


class RunRequest(BaseModel):
    spec_id: str
    split: Split | None = None
    arms: list[Arm] = Field(default_factory=lambda: ["baseline", "candidate"])


class VerifyRequest(BaseModel):
    run_id: str


class BenchmarkCaseResponse(BaseModel):
    case: BenchmarkCase
    verification_errors: list[dict] = Field(default_factory=list)


class BenchmarkListResponse(BaseModel):
    cases: list[BenchmarkCase]
    total: int
    confirmed_cases: int
    awaiting_cases: int
    split_counts: dict[str, int] = Field(default_factory=dict)
    notice: str = (
        "A reference DOI is ground truth only after a human confirms it belongs to the "
        "case. Metadata verification alone is not confirmation."
    )


class PromotionGate(BaseModel):
    allowed: bool
    reasons: list[str] = Field(default_factory=list)


class RunResponse(BaseModel):
    spec_id: str
    runs: list[ExperimentRun]
    comparisons: list[ExperimentComparison]
    promotion_gate: PromotionGate
    notice: str = COVERAGE_NOTICE


class VerifyResponse(BaseModel):
    run_id: str
    evaluation: EvaluationReport
    stored_evaluation: EvaluationReport | None = None
    recomputed_from: str
    matches_stored: bool
    notice: str = (
        "Metrics were recomputed by the independent evaluator from the stored raw "
        "retrieval snapshot, not taken from the agent's own report."
    )