"""Schemas for the LLM-driven, multi-role research gap pipeline.

Division of labour enforced by these types:

- an LLM may synthesise and propose, but every factual field it emits must carry a
  span that Python can find verbatim in the text that was actually fed to it;
- a critique is a semantic opinion on a 0..5 scale, never a percentage;
- the final gate is computed by Python from recorded facts, not by the model.

Nothing here may claim a full text was read: the only retrieved text this pipeline
feeds to a model is the abstract, so `evidence_source` is pinned to "abstract".
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .gap import GapType
from .llm import LLM_NOT_CONFIGURED
from .paper import FieldEvidence

RiskLabel = Literal["LOW", "MEDIUM", "HIGH"]
RISK_ORDER: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

# The gap vocabulary the LLM is asked to use. Existing internal types are kept;
# three genuinely new kinds are added rather than replacing the old taxonomy.
PipelineGapType = Literal[
    "coverage_gap",
    "method_gap",
    "evaluation_gap",
    "generalization_gap",
    "contradiction_gap",
    "integration_gap",
]

GAP_TYPE_ALIASES: dict[str, GapType] = {
    "coverage_gap": "coverage",
    "method_gap": "method",
    "evaluation_gap": "evaluation",
    "generalization_gap": "generalization",
    "contradiction_gap": "contradiction",
    "integration_gap": "integration",
    # tolerate the internal spelling too
    "method": "method",
    "evaluation": "evaluation",
    "generalization": "generalization",
    "reliability": "reliability",
    "efficiency": "efficiency",
    "reproducibility": "reproducibility",
    "coverage": "coverage",
    "contradiction": "contradiction",
    "integration": "integration",
}

PIPELINE_GAP_LABELS: dict[str, str] = {
    "coverage": "Coverage Gap",
    "contradiction": "Contradiction Gap",
    "integration": "Integration Gap",
}

# The seven Evidence Card fields. `setting` and `evaluation` are card-level names;
# they map onto the existing Paper fields when a card is written back.
CARD_FIELDS: tuple[str, ...] = (
    "research_problem",
    "method",
    "setting",
    "dataset",
    "evaluation",
    "limitations",
    "future_work",
)

CARD_TO_PAPER_FIELD: dict[str, str] = {
    "research_problem": "research_problem",
    "method": "method",
    "setting": "agent_architecture",
    "dataset": "dataset",
    "evaluation": "evaluation_metrics",
    "limitations": "limitations",
    "future_work": "future_work",
}

PROMPT_VERSION = "gap-pipeline-v1"


class PlanQueryGroup(BaseModel):
    """One search angle. A plan must cover more than a single query."""

    angle: str
    queries: list[str] = Field(min_length=1)


class ResearchPlan(BaseModel):
    research_topic: str
    research_questions: list[str] = Field(default_factory=list)
    search_angles: list[str] = Field(default_factory=list)
    review_queries: list[str] = Field(default_factory=list)
    method_queries: list[str] = Field(default_factory=list)
    challenge_queries: list[str] = Field(default_factory=list)
    recent_queries: list[str] = Field(default_factory=list)
    foundational_queries: list[str] = Field(default_factory=list)
    inclusion_criteria: list[str] = Field(default_factory=list)
    exclusion_criteria: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _must_cover_the_five_angles(self) -> "ResearchPlan":
        groups = {
            "survey/review": self.review_queries,
            "foundational": self.foundational_queries,
            "recent": self.recent_queries,
            "representative methods": self.method_queries,
            "limitations/challenges": self.challenge_queries,
        }
        missing = [name for name, queries in groups.items() if not queries]
        if missing:
            raise ValueError(
                "a research plan must cover survey/review, foundational, recent, "
                f"representative methods and limitations/challenges; missing: {missing}"
            )
        if not self.research_questions:
            raise ValueError("a research plan must state at least one research question")
        return self

    def all_queries(self) -> list[str]:
        seen: list[str] = []
        for group in (
            self.review_queries,
            self.foundational_queries,
            self.method_queries,
            self.challenge_queries,
            self.recent_queries,
        ):
            for query in group:
                cleaned = query.strip()
                if cleaned and cleaned not in seen:
                    seen.append(cleaned)
        return seen


class EvidenceCardField(BaseModel):
    """One claim plus the verbatim span that grounds it."""

    claim: str = ""
    evidence_span: str = ""
    evidence_source: Literal["abstract"] = "abstract"
    # A model that does not state a confidence is recorded conservatively as low,
    # never silently upgraded.
    confidence: Literal["high", "medium", "low"] = "low"

    @property
    def is_filled(self) -> bool:
        return bool(self.claim.strip() and self.evidence_span.strip())

    def to_field_evidence(self, source_url: str | None) -> FieldEvidence:
        if not self.is_filled:
            return FieldEvidence.unknown()
        return FieldEvidence(
            value=self.claim.strip(),
            evidence_source="abstract",
            evidence_span=self.evidence_span,
            source_url=source_url,
            confidence=self.confidence,
            extraction_method="llm",
        )


class EvidenceCard(BaseModel):
    paper_id: str
    pipeline_id: str = ""
    title: str = ""
    doi: str | None = None
    source_url: str = ""
    research_problem: EvidenceCardField = Field(default_factory=EvidenceCardField)
    method: EvidenceCardField = Field(default_factory=EvidenceCardField)
    setting: EvidenceCardField = Field(default_factory=EvidenceCardField)
    dataset: EvidenceCardField = Field(default_factory=EvidenceCardField)
    evaluation: EvidenceCardField = Field(default_factory=EvidenceCardField)
    limitations: EvidenceCardField = Field(default_factory=EvidenceCardField)
    future_work: EvidenceCardField = Field(default_factory=EvidenceCardField)

    extraction_method: Literal["llm", "heuristic"] = "llm"
    abstract_hash: str = ""
    prompt_version: str = PROMPT_VERSION
    # Fields whose span could not be found verbatim in the abstract that was fed
    # to the model. They are dropped, never auto-accepted.
    rejected_fields: list[dict[str, str]] = Field(default_factory=list)
    grounded_fields: list[str] = Field(default_factory=list)
    from_cache: bool = False
    created_at: str = ""

    def field(self, name: str) -> EvidenceCardField:
        return getattr(self, name)

    def grounded_items(self) -> list[tuple[str, EvidenceCardField]]:
        return [(name, self.field(name)) for name in CARD_FIELDS if self.field(name).is_filled]


class EvidenceRef(BaseModel):
    """A pointer from a candidate gap back to a specific card field."""

    paper_id: str
    field: str
    evidence_span: str

    @model_validator(mode="after")
    def _require_span(self) -> "EvidenceRef":
        if not self.evidence_span.strip():
            raise ValueError("an evidence reference must quote a non-empty span")
        return self


class CandidateGap(BaseModel):
    """The fifteen fields every LLM-proposed candidate must carry."""

    gap_claim: str = Field(min_length=8)
    gap_type: PipelineGapType
    problem_context: str = ""
    already_solved: str = ""
    unresolved_boundary: str = ""
    why_it_matters: str = ""
    supporting_papers: list[str] = Field(default_factory=list)
    supporting_evidence: list[EvidenceRef] = Field(default_factory=list)
    contradicting_evidence: list[EvidenceRef] = Field(default_factory=list)
    candidate_research_question: str = ""
    minimum_experiment: str = ""
    testability: str = ""
    novelty_risk: RiskLabel = "MEDIUM"
    # The label is an enum, so the justification needs somewhere else to live:
    # without this field a model writes "MEDIUM: because ..." and is rejected.
    novelty_rationale: str = ""
    uncertainties: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_fake_probability(self) -> "CandidateGap":
        if not self.gap_claim.strip():
            raise ValueError("gap_claim must be a specific statement, not empty")
        return self

    @property
    def internal_gap_type(self) -> GapType:
        return GAP_TYPE_ALIASES[self.gap_type]


class CrossPaperSynthesis(BaseModel):
    """The nine questions the gap analyst must answer across cards."""

    already_solved: list[str] = Field(default_factory=list)
    main_method_routes: list[str] = Field(default_factory=list)
    consistent_findings: list[str] = Field(default_factory=list)
    conflicting_findings: list[str] = Field(default_factory=list)
    uncovered_scenarios: list[str] = Field(default_factory=list)
    shared_limitations: list[str] = Field(default_factory=list)
    uncovered_metrics: list[str] = Field(default_factory=list)
    repeatedly_mentioned_unresolved: list[str] = Field(default_factory=list)
    mature_but_uncombined: list[str] = Field(default_factory=list)


class GapAnalystOutput(BaseModel):
    synthesis: CrossPaperSynthesis = Field(default_factory=CrossPaperSynthesis)
    candidates: list[CandidateGap] = Field(default_factory=list)


class GapCritique(BaseModel):
    """Semantic judgement from an agent that never saw the gap agent's reasoning."""

    gap_index: int = 0
    evidence_grounding: int = Field(ge=0, le=5)
    cross_paper_support: int = Field(ge=0, le=5)
    specificity: int = Field(ge=0, le=5)
    testability: int = Field(ge=0, le=5)
    novelty_risk: RiskLabel = "MEDIUM"
    contradiction_risk: RiskLabel = "MEDIUM"
    major_weaknesses: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    recommended_action: Literal["accept", "revise", "reject"] = "revise"
    rationale: str = ""
    from_cache: bool = False

    @property
    def mean_score(self) -> float:
        return round(
            (
                self.evidence_grounding
                + self.cross_paper_support
                + self.specificity
                + self.testability
            )
            / 4,
            2,
        )


class CounterSearchOutcome(BaseModel):
    """Distinguishes "searched and found nothing" from "search failed"."""

    status: Literal[
        "COUNTER_EVIDENCE_FOUND",
        "NO_COUNTER_EVIDENCE_FOUND",
        "COUNTER_SEARCH_FAILED",
        "NOT_RUN",
    ] = "NOT_RUN"
    queries: list[str] = Field(default_factory=list)
    detection_key: str = ""
    sources: list[str] = Field(default_factory=list)
    requests_made: int = 0
    cache_hits: int = 0
    papers_retrieved: int = 0
    rejected_as_not_addressing_claim: int = 0
    prior_art: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    query_source: Literal["llm", "deterministic"] = "deterministic"
    notice: str = ""


class GapCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class GapValidation(BaseModel):
    """Pure-Python verification. Independent of every LLM opinion."""

    gap_index: int = 0
    checks: list[GapCheck] = Field(default_factory=list)
    unique_supporting_papers: int = 0
    unique_counter_papers: int = 0
    valid_evidence_refs: int = 0
    invalid_evidence_refs: list[dict[str, str]] = Field(default_factory=list)
    missing_papers: list[str] = Field(default_factory=list)
    unverified_dois: list[str] = Field(default_factory=list)
    duplicate_paper_counting: bool = False
    counter_search_status: str = "NOT_RUN"
    prior_art_collisions: int = 0
    novelty_risk: RiskLabel = "MEDIUM"
    evidence_contradiction: bool = False
    passed: bool = False
    reasons: list[str] = Field(default_factory=list)

    @property
    def by_name(self) -> dict[str, GapCheck]:
        return {c.name: c for c in self.checks}


class GapGateResult(BaseModel):
    gap_index: int = 0
    status: Literal["accepted", "needs_human_review", "rejected"] = "needs_human_review"
    python_passed: bool = False
    critic_rejected: bool = False
    reasons: list[str] = Field(default_factory=list)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    notice: str = ""


class ValidatedGap(BaseModel):
    """One candidate plus everything the system independently established about it."""

    candidate: CandidateGap
    critique: GapCritique | None = None
    counter: CounterSearchOutcome = Field(default_factory=CounterSearchOutcome)
    validation: GapValidation = Field(default_factory=GapValidation)
    gate: GapGateResult = Field(default_factory=GapGateResult)
    gap_id: str | None = None


StageId = Literal[
    "planner",
    "selection",
    "literature_analysis",
    "gap_analysis",
    "gap_critic",
    "counter_evidence",
    "validation",
]

STAGE_SEQUENCE: tuple[StageId, ...] = (
    "planner",
    "selection",
    "literature_analysis",
    "gap_analysis",
    "gap_critic",
    "counter_evidence",
    "validation",
)

STAGE_TITLES: dict[str, tuple[str, str]] = {
    "planner": ("Research Planner Agent", "检索规划 Agent"),
    "selection": ("Paper Selection (Python)", "候选论文筛选（确定性）"),
    "literature_analysis": ("Literature Analyst Agent", "文献分析 Agent"),
    "gap_analysis": ("Research Gap Analyst Agent", "空白综合 Agent"),
    "gap_critic": ("Gap Critic / Judge Agent", "空白评审 Agent"),
    "counter_evidence": ("Counter-evidence Retrieval", "反证检索"),
    "validation": ("Python Gap Validator + Gate", "Python 独立验证与门禁"),
}

PipelineStatus = Literal[
    "running",
    "completed",
    "failed",
    "awaiting_budget",
    "awaiting_human",
    "not_configured",
]


class PipelineStage(BaseModel):
    stage_id: StageId
    index: int
    title: str
    title_zh: str
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    attempts: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    notice: str = ""
    llm_calls: int = 0
    cache_hits: int = 0

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "skipped")


class GapPipelineRun(BaseModel):
    pipeline_id: str
    topic: str
    run_id: str = ""
    workflow_id: str | None = None
    status: PipelineStatus = "running"
    current_stage: StageId = "planner"
    stages: list[PipelineStage] = Field(default_factory=list)
    paper_ids: list[str] = Field(default_factory=list)
    selected_paper_ids: list[str] = Field(default_factory=list)
    # Run parameters are persisted so a resume uses the same scope it started with.
    max_papers: int = Field(default=25, ge=2, le=30)
    max_gaps: int = Field(default=5, ge=1, le=8)
    run_counter_search: bool = True
    plan: ResearchPlan | None = None
    synthesis: CrossPaperSynthesis | None = None
    gaps: list[ValidatedGap] = Field(default_factory=list)
    llm_calls_used: int = 0
    llm_cache_hits: int = 0
    llm_budget: int = 0
    provider: str = LLM_NOT_CONFIGURED
    model: str = ""
    notices: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @model_validator(mode="after")
    def _stages_follow_sequence(self) -> "GapPipelineRun":
        if [s.stage_id for s in self.stages] != list(STAGE_SEQUENCE):
            raise ValueError("pipeline stages must follow the fixed seven-stage sequence")
        return self

    def stage(self, stage_id: str) -> PipelineStage:
        for item in self.stages:
            if item.stage_id == stage_id:
                return item
        raise KeyError(stage_id)

    @property
    def completed_stages(self) -> int:
        return sum(1 for s in self.stages if s.is_terminal)


def new_stages() -> list[PipelineStage]:
    return [
        PipelineStage(
            stage_id=stage_id,
            index=index,
            title=STAGE_TITLES[stage_id][0],
            title_zh=STAGE_TITLES[stage_id][1],
        )
        for index, stage_id in enumerate(STAGE_SEQUENCE, start=1)
    ]


class PipelineStartRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=400)
    run_id: str | None = None
    paper_ids: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    max_papers: int = Field(default=25, ge=2, le=30)
    max_gaps: int = Field(default=5, ge=1, le=8)
    run_counter_search: bool = True


class PipelineAdvanceRequest(BaseModel):
    max_stages: int = Field(default=7, ge=1, le=len(STAGE_SEQUENCE))
    from_stage: StageId | None = None


class PipelineListResponse(BaseModel):
    pipelines: list[GapPipelineRun]
    total: int


class PipelineResponse(BaseModel):
    pipeline: GapPipelineRun
    executed: list[str] = Field(default_factory=list)
    notice: str = (
        "LLM roles propose; Python and real retrieval verify. Every stage stores the "
        "records it actually produced, and a resume reuses them instead of paying twice."
    )