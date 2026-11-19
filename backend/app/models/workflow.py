"""The 18-step research workflow: real data in, real data out, resumable state.

Every step records the inputs it actually read and the outputs it actually
produced. A step is never marked complete because the UI asked for it: the
orchestrator only advances after the underlying service returned real records.
Two steps stop for a human decision and stay stopped until one arrives.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

StepId = Literal[
    "research_topic",
    "search_planning",
    "literature_discovery",
    "paper_extraction",
    "literature_matrix",
    "gap_discovery",
    "counter_evidence_search",
    "human_approval",
    "hypothesis",
    "experiment_spec",
    "baseline_execution",
    "candidate_execution",
    "independent_evaluation",
    "failure_diagnosis",
    "skill_mutation",
    "replay_evaluation",
    "promotion_decision",
    "research_dossier",
]

STEP_SEQUENCE: tuple[StepId, ...] = (
    "research_topic",
    "search_planning",
    "literature_discovery",
    "paper_extraction",
    "literature_matrix",
    "gap_discovery",
    "counter_evidence_search",
    "human_approval",
    "hypothesis",
    "experiment_spec",
    "baseline_execution",
    "candidate_execution",
    "independent_evaluation",
    "failure_diagnosis",
    "skill_mutation",
    "replay_evaluation",
    "promotion_decision",
    "research_dossier",
)

STEP_TITLES: dict[str, tuple[str, str]] = {
    "research_topic": ("Research Topic", "研究主题"),
    "search_planning": ("Search Planning", "检索规划"),
    "literature_discovery": ("Literature Discovery", "文献检索"),
    "paper_extraction": ("Paper Extraction", "论文字段抽取"),
    "literature_matrix": ("Literature Matrix", "文献对比矩阵"),
    "gap_discovery": ("Gap Discovery", "研究空白发现"),
    "counter_evidence_search": ("Counter-evidence Search", "反证检索"),
    "human_approval": ("Human Approval", "人工确认"),
    "hypothesis": ("Hypothesis", "研究假设"),
    "experiment_spec": ("Experiment Spec", "实验协议"),
    "baseline_execution": ("Baseline Execution", "基线执行"),
    "candidate_execution": ("Candidate Execution", "候选执行"),
    "independent_evaluation": ("Independent Evaluation", "独立评测"),
    "failure_diagnosis": ("Failure Diagnosis", "失败诊断"),
    "skill_mutation": ("Skill Mutation", "技能变异"),
    "replay_evaluation": ("Replay Evaluation", "回放评测"),
    "promotion_decision": ("Promotion / Rollback", "晋升 / 回滚"),
    "research_dossier": ("Research Dossier", "研究档案"),
}

# These steps cannot complete on their own. They wait for a recorded human decision.
HUMAN_STEPS: frozenset[str] = frozenset({"human_approval", "promotion_decision"})

# Context keys each step owns. Rewinding clears the keys of the reset steps so a
# redo cannot silently reuse an upstream decision (e.g. a stale gap approval).
STEP_CONTEXT_KEYS: dict[str, tuple[str, ...]] = {
    "research_topic": ("project_id",),
    "search_planning": ("gap_pipeline_id",),
    "literature_discovery": ("literature_run_id", "paper_ids"),
    "gap_discovery": ("gap_ids",),
    "human_approval": (
        "accepted_gap_id",
        "approval_decided_by",
        "approval_note",
        "rejected_gap_ids",
    ),
    "hypothesis": ("hypothesis",),
    "experiment_spec": ("spec_id", "case_ids", "candidate_version_id"),
    "baseline_execution": ("baseline_run_ids",),
    "candidate_execution": ("candidate_run_ids",),
    "independent_evaluation": ("promotion_gate",),
    "failure_diagnosis": ("diagnosis_count",),
    "skill_mutation": ("round_id", "proposed_version_ids"),
    "replay_evaluation": ("replay_spec_ids",),
    "promotion_decision": ("promotion_decision", "promotion_outcome"),
    "research_dossier": ("dossier",),
}

StepStatus = Literal[
    "pending", "running", "completed", "failed", "awaiting_human", "awaiting_budget", "skipped"
]
WorkflowStatus = Literal["running", "awaiting_human", "awaiting_budget", "completed", "failed"]

TERMINAL_STEP_STATES: frozenset[str] = frozenset({"completed", "skipped"})


class WorkflowStep(BaseModel):
    step_id: StepId
    index: int
    title: str
    title_zh: str
    status: StepStatus = "pending"
    attempts: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    notice: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STEP_STATES


class WorkflowRun(BaseModel):
    workflow_id: str
    topic: str
    query: str
    sources: list[Literal["openalex", "crossref", "arxiv"]] = Field(
        default_factory=lambda: ["openalex", "crossref", "arxiv"]
    )
    top_k: int = Field(default=12, ge=1, le=40)
    year_from: int | None = None
    year_to: int | None = None
    prefer_reviews: bool = False
    status: WorkflowStatus = "running"
    current_step: StepId = "research_topic"
    steps: list[WorkflowStep] = Field(default_factory=list)
    # Ids of the real artifacts each step produced, so any step can be audited
    # against the store instead of against this summary.
    context: dict[str, Any] = Field(default_factory=dict)
    notices: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @model_validator(mode="after")
    def _steps_follow_the_fixed_sequence(self) -> "WorkflowRun":
        if [s.step_id for s in self.steps] != list(STEP_SEQUENCE):
            raise ValueError("workflow steps must follow the fixed 18-step sequence")
        return self

    @property
    def completed_steps(self) -> int:
        return sum(1 for s in self.steps if s.is_terminal)

    @property
    def progress(self) -> float:
        return round(self.completed_steps / len(STEP_SEQUENCE), 4)

    def step(self, step_id: str) -> WorkflowStep:
        for item in self.steps:
            if item.step_id == step_id:
                return item
        raise KeyError(step_id)


def new_steps() -> list[WorkflowStep]:
    return [
        WorkflowStep(
            step_id=step_id,
            index=index,
            title=STEP_TITLES[step_id][0],
            title_zh=STEP_TITLES[step_id][1],
        )
        for index, step_id in enumerate(STEP_SEQUENCE, start=1)
    ]


class WorkflowStartRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=400)
    query: str | None = Field(default=None, max_length=400)
    sources: list[Literal["openalex", "crossref", "arxiv"]] = Field(
        default_factory=lambda: ["openalex", "crossref", "arxiv"]
    )
    top_k: int = Field(default=12, ge=1, le=40)
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    prefer_reviews: bool = False


class WorkflowAdvanceRequest(BaseModel):
    """Bounded execution: at most `max_steps` steps per call, never an open loop."""

    max_steps: int = Field(default=1, ge=1, le=len(STEP_SEQUENCE))
    from_step: StepId | None = None


class WorkflowApprovalRequest(BaseModel):
    gap_id: str = Field(min_length=1)
    decision: Literal["accepted", "rejected"] = "accepted"
    decided_by: str = Field(min_length=1, max_length=120)
    human_note: str = Field(default="", max_length=2000)


class WorkflowDecisionRequest(BaseModel):
    decision: Literal["promote", "rollback", "keep"]
    decided_by: str = Field(min_length=1, max_length=120)
    version_id: str | None = None
    reason: str = Field(default="", max_length=2000)


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowRun]
    total: int


class WorkflowResponse(BaseModel):
    workflow: WorkflowRun
    executed: list[str] = Field(default_factory=list)
    notice: str = (
        "Each step stores the real records it read and produced. A failed step keeps its "
        "error text and can be retried; nothing downstream runs on fabricated data."
    )