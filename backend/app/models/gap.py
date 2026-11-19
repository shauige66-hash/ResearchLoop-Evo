"""Candidate research gap schema with enforced multi-paper evidence.

A gap is a hypothesis about the literature, not a finding. Two rules are enforced
here rather than left to the caller:

- a gap must be supported by at least two distinct papers, so a single paper's
  Future Work section can never manufacture a gap on its own;
- every supporting item must quote a verbatim span from retrieved text.

Absence of counter-evidence means "not found within the current search scope",
never "does not exist".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .paper import EXTRACTION_MODE, EvidenceSource, ExtractionMethod

GapType = Literal[
    "method",
    "evaluation",
    "generalization",
    "reliability",
    "efficiency",
    "reproducibility",
    # Added by the LLM gap pipeline. The original six remain valid and unchanged.
    "coverage",
    "contradiction",
    "integration",
]

GapStatus = Literal["needs_human_review", "accepted", "rejected", "edited"]

# Evidence-backed labels, deliberately not statistical probabilities.
ConfidenceLabel = Literal["Low", "Medium", "High"]

GAP_TYPE_LABELS: dict[GapType, str] = {
    "method": "Method Gap",
    "evaluation": "Evaluation Gap",
    "generalization": "Generalization Gap",
    "reliability": "Reliability Gap",
    "efficiency": "Efficiency Gap",
    "reproducibility": "Reproducibility Gap",
    "coverage": "Coverage Gap",
    "contradiction": "Contradiction Gap",
    "integration": "Integration Gap",
}

SCOPE_NOTICE = (
    "No counter-evidence was found within the current search scope "
    "(selected sources, year range and top-k). This does not establish that the "
    "gap does not exist; it only bounds what this search could see."
)


class GapEvidenceItem(BaseModel):
    """A verbatim span from a supporting paper, tied to the field it came from."""

    paper_id: str
    title: str
    doi: str | None = None
    source_url: str
    field: str
    evidence_span: str
    # Records written before this field existed only ever quoted retrieved
    # abstracts, so "abstract" is the truthful default, never "fulltext".
    evidence_source: EvidenceSource = "abstract"
    extraction_method: str = "heuristic"

    @model_validator(mode="after")
    def _require_span(self) -> "GapEvidenceItem":
        if not self.evidence_span.strip():
            raise ValueError("supporting evidence must quote a non-empty verbatim span")
        return self


class CounterEvidenceItem(BaseModel):
    """A real paper retrieved by the automatic counter-evidence search.

    Only papers that address the specific claim of the gap are recorded here;
    topical similarity alone is not counter-evidence.
    """

    paper_id: str
    title: str
    doi: str | None = None
    source: str
    source_url: str
    publication_year: int | None = None
    abstract_snippet: str | None = None
    matched_query: str
    why_relevant: str
    matched_cue: str | None = None
    evidence_span: str | None = None


class RelatedWork(BaseModel):
    paper_id: str
    title: str
    doi: str | None = None
    source_url: str
    method_class: str | None = None
    why_closest: str


class Experimentability(BaseModel):
    """Whether a minimal, cheap experiment could actually probe this gap."""

    testable_minimally: bool
    proposed_experiment: str
    required_inputs: list[str] = Field(default_factory=list)
    blocking_reason: str | None = None


class ResearchGap(BaseModel):
    # --- the twelve required fields ---
    gap_id: str
    title: str
    description: str
    gap_type: GapType
    supporting_papers: list[str]
    supporting_evidence: list[GapEvidenceItem]
    counter_evidence: list[CounterEvidenceItem] = Field(default_factory=list)
    closest_related_work: list[RelatedWork] = Field(default_factory=list)
    unresolved_question: str
    experimentability: Experimentability
    confidence_label: ConfidenceLabel
    status: GapStatus = "needs_human_review"

    # --- provenance and human-review bookkeeping ---
    run_id: str
    topic: str = ""
    confidence_rationale: str
    counter_search_queries: list[str] = Field(default_factory=list)
    counter_search_scope: dict = Field(default_factory=dict)
    counter_search_errors: list[dict] = Field(default_factory=list)
    # What the detector actually keyed on, so counter-evidence can be judged
    # against the specific claim instead of the general topic.
    detection_key: str = ""
    scope_notice: str = SCOPE_NOTICE
    human_note: str | None = None
    created_at: str = ""
    updated_at: str | None = None

    # --- additive payload from the LLM gap pipeline ---
    # Rule-based gaps leave these empty; nothing downstream may require them.
    discovery_mode: Literal["rule_based", "llm_pipeline"] = "rule_based"
    pipeline_id: str | None = None
    candidate: dict = Field(default_factory=dict)
    critique: dict = Field(default_factory=dict)
    validation: dict = Field(default_factory=dict)
    gate: dict = Field(default_factory=dict)
    counter_status: str = "NOT_RUN"
    prior_art: list[dict] = Field(default_factory=list)
    novelty_risk: str = ""

    @model_validator(mode="after")
    def _require_multi_paper_support(self) -> "ResearchGap":
        distinct = list(dict.fromkeys(self.supporting_papers))
        if len(distinct) < 2:
            raise ValueError(
                "a research gap must be supported by at least two distinct papers; "
                "a single paper's future work is not sufficient evidence"
            )
        self.supporting_papers = distinct
        if not self.supporting_evidence:
            raise ValueError("a research gap must carry verbatim supporting evidence")
        unknown = {e.paper_id for e in self.supporting_evidence} - set(distinct)
        if unknown:
            raise ValueError(f"supporting evidence references non-supporting papers: {unknown}")
        if not self.confidence_rationale.strip():
            raise ValueError("confidence_label must be justified by a rationale")
        return self

    @model_validator(mode="after")
    def _derive_legacy_counter_status(self) -> "ResearchGap":
        # Gaps stored before counter_status existed still hold real retrieved
        # counter-evidence; reporting NOT_RUN for them would misstate the search.
        if self.counter_status == "NOT_RUN" and self.counter_evidence:
            self.counter_status = "COUNTER_EVIDENCE_FOUND"
        return self

    @property
    def type_label(self) -> str:
        return GAP_TYPE_LABELS[self.gap_type]


class GapDiscoveryRequest(BaseModel):
    run_id: str | None = None
    paper_ids: list[str] = Field(default_factory=list)
    topic: str = ""
    run_counter_search: bool = True
    counter_top_k: int = Field(default=10, ge=1, le=20)


class GapReviewRequest(BaseModel):
    status: GapStatus
    human_note: str | None = None
    title: str | None = None
    description: str | None = None
    unresolved_question: str | None = None


class GapListResponse(BaseModel):
    gaps: list[ResearchGap]
    total: int
    notice: str = SCOPE_NOTICE
    extraction_mode: ExtractionMethod = EXTRACTION_MODE
    detection_mode: str = "rule_based"