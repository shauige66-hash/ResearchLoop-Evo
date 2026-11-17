"""Evolution contracts: real trials in, evidence-backed diagnoses and proposals out.

An evolution round never asserts that a candidate is better. It records what the
executed trials actually did, names the failures with the numbers that justify
them, and emits at most three candidate strategies for the evaluator to judge.

Two boundaries are structural rather than conventional:
- proposals are derived from development trials only, so validation and holdout
  material cannot leak into a mutation;
- a diagnosis that can only be fixed by changing the frozen protocol is reported
  as such and produces no candidate, because a candidate may not touch the spec.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .experiment import Arm, ReferenceStatus, Split
from .skill import SearchStrategy

FailureType = Literal[
    "query_too_narrow",
    "missing_synonym",
    "wrong_research_terminology",
    "source_coverage_insufficient",
    "time_filter_too_restrictive",
    "api_failure",
]

FAILURE_LABELS: dict[str, str] = {
    "query_too_narrow": "Query Too Narrow",
    "missing_synonym": "Missing Synonym",
    "wrong_research_terminology": "Wrong Research Terminology",
    "source_coverage_insufficient": "Source Coverage Insufficient",
    "time_filter_too_restrictive": "Time Filter Too Restrictive",
    "api_failure": "API Failure",
}

EVOLVABLE_COMPONENTS = (
    "query_templates",
    "domain_synonyms",
    "keyword_expansion_rules",
    "source_priority",
    "search_filters",
    "retrieval_budget",
)

IMMUTABLE_COMPONENTS = (
    "benchmark reference DOIs",
    "dataset splits",
    "evaluator code and formulas",
    "API source set",
    "spec budget ceilings",
)

# A diagnosis whose only fix lies outside the evolvable surface.
FROZEN_FIX = "none — requires a new frozen spec authored by a human"

MAX_CANDIDATES_PER_ROUND = 3

ROUND_NOTICE = (
    "Candidates are proposals, not verified improvements. Nothing here activates a "
    "version: promotion requires the independent evaluator to pass every gate, "
    "including a human-confirmed reference set."
)


class SourceTally(BaseModel):
    """Per-source contribution inside the retained top-k of one real run."""

    source: str
    paper_count: int


class TrialExperience(BaseModel):
    """One executed arm, reduced to the signals a diagnosis may legitimately use."""

    run_id: str
    spec_id: str
    case_id: str
    topic: str
    query: str
    split: Split
    arm: Arm
    skill_version_id: str
    queries_used: list[str] = Field(default_factory=list)
    status: str
    reference_status: ReferenceStatus
    unique_paper_count: int = 0
    top_k: int = 0
    api_request_count: int = 0
    cache_hits: int = 0
    execution_time_ms: int = 0
    coverage_at_k: float | None = None
    hit_references: list[str] = Field(default_factory=list)
    missed_references: list[str] = Field(default_factory=list)
    source_errors: list[dict] = Field(default_factory=list)
    source_tallies: list[SourceTally] = Field(default_factory=list)
    source_priority: list[str] = Field(default_factory=list)
    retrieved_titles: list[str] = Field(default_factory=list)
    # Confirmed reference titles and years, available only for development trials.
    reference_titles: list[str] = Field(default_factory=list)
    reference_years: list[int] = Field(default_factory=list)
    effective_year_from: int | None = None
    effective_year_to: int | None = None
    snapshot_available: bool = False

    @property
    def total_api_queries(self) -> int:
        return self.api_request_count + self.cache_hits


class FailureDiagnosis(BaseModel):
    failure_type: FailureType
    run_id: str
    case_id: str
    split: Split
    evidence: dict = Field(default_factory=dict)
    rationale: str = Field(min_length=1)
    suggested_component: str = Field(min_length=1)

    @property
    def label(self) -> str:
        return FAILURE_LABELS[self.failure_type]


class StrategyChange(BaseModel):
    component: str
    before: object = None
    after: object = None


class CandidateProposal(BaseModel):
    version_id: str
    parent_version: str
    version_number: int
    mutation_description: str
    source_trials: list[str] = Field(default_factory=list)
    addressed_failures: list[FailureType] = Field(default_factory=list)
    changes: list[StrategyChange] = Field(default_factory=list)
    strategy: SearchStrategy
    created_at: str
    # Cost is projected from the real baseline request count, not guessed.
    projected_query_count: int = 0
    projected_api_requests: int = 0
    projected_request_ratio: float | None = None
    grounding: str = ""

    @model_validator(mode="after")
    def _changes_stay_inside_the_evolvable_surface(self) -> "CandidateProposal":
        for change in self.changes:
            if change.component not in EVOLVABLE_COMPONENTS:
                raise ValueError(
                    f"{change.component} is not an evolvable component; a candidate may "
                    "not modify the benchmark, the evaluator or the frozen protocol"
                )
        return self


class EvolutionRound(BaseModel):
    round_id: str
    spec_id: str
    parent_version_id: str
    proposer_mode: Literal["deterministic", "llm"] = "deterministic"
    llm_skip_reason: str = ""
    experiences: list[TrialExperience] = Field(default_factory=list)
    diagnoses: list[FailureDiagnosis] = Field(default_factory=list)
    proposals: list[CandidateProposal] = Field(default_factory=list)
    skipped_mutations: list[dict] = Field(default_factory=list)
    baseline_api_requests: int = 0
    affordable_api_requests: int = 0
    affordable_query_count: int = 0
    created_at: str = ""
    notice: str = ROUND_NOTICE

    @model_validator(mode="after")
    def _candidate_cap(self) -> "EvolutionRound":
        if len(self.proposals) > MAX_CANDIDATES_PER_ROUND:
            raise ValueError(
                f"an evolution round may propose at most {MAX_CANDIDATES_PER_ROUND} candidates"
            )
        return self


class EvolveRequest(BaseModel):
    spec_id: str = Field(min_length=1)
    max_candidates: int = Field(default=MAX_CANDIDATES_PER_ROUND, ge=1, le=MAX_CANDIDATES_PER_ROUND)
    use_llm: bool = False


class EvaluateRequest(BaseModel):
    spec_id: str = Field(min_length=1)
    split: Split | None = None


class PromoteRequest(BaseModel):
    spec_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    decided_by: str = Field(min_length=1, max_length=120)


class RollbackRequest(BaseModel):
    version_id: str = Field(min_length=1)
    decided_by: str = Field(min_length=1, max_length=120)
    reason: str = Field(default="", max_length=1000)