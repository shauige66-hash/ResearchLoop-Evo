import type { ExperimentComparison, PromotionGate, Split } from "./experiment";
import type { CandidateProposal, FailureDiagnosis, SourceTally } from "./evolution";
import type { ConfidenceLabel, CounterSearchScope, Experimentability, GapType } from "./gap";

export type StepId =
  | "research_topic"
  | "search_planning"
  | "literature_discovery"
  | "paper_extraction"
  | "literature_matrix"
  | "gap_discovery"
  | "counter_evidence_search"
  | "human_approval"
  | "hypothesis"
  | "experiment_spec"
  | "baseline_execution"
  | "candidate_execution"
  | "independent_evaluation"
  | "failure_diagnosis"
  | "skill_mutation"
  | "replay_evaluation"
  | "promotion_decision"
  | "research_dossier";

export type StepStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "awaiting_human"
  | "awaiting_budget"
  | "skipped";

export type WorkflowStatus =
  | "running"
  | "awaiting_human"
  | "awaiting_budget"
  | "completed"
  | "failed";

export interface ExecutedRun {
  run_id: string;
  case_id: string;
  split: Split;
  arm: "baseline" | "candidate";
  status: string;
  queries_used: string[];
  api_request_count: number;
  cache_hits: number;
  total_api_queries: number;
  unique_paper_count: number;
  execution_time_ms: number;
  source_errors: Record<string, unknown>[];
  error: string | null;
}

export interface ScoredRun {
  run_id: string;
  case_id: string;
  arm: "baseline" | "candidate";
  split: Split;
  status: "computed" | "awaiting_reference_set";
  coverage_at_k: number | null;
  hit_references: string[];
  missed_references: string[];
  api_query_count: number;
  cache_hits: number;
  unique_paper_count: number;
  execution_time_ms: number;
  reference_set_size: number;
  reference_fingerprint: string;
  recomputed_from: string;
}

export interface SpecCaseSummary {
  case_id: string;
  topic: string;
  split: Split;
  reference_count: number;
  confirmed_count: number;
  reference_status: "confirmed" | "awaiting_reference_set";
}

export interface GapSummary {
  gap_id: string;
  title: string;
  gap_type: GapType;
  confidence_label: ConfidenceLabel;
  supporting_papers: string[];
  status: string;
  experimentability: Experimentability;
}

export interface CounterGapResult {
  gap_id: string;
  query: string;
  counter_count: number;
  confidence_label: ConfidenceLabel;
  confidence_rationale: string;
  scope: CounterSearchScope;
  errors: Record<string, unknown>[];
}

export interface ReplayResult {
  spec_id: string;
  candidate_version_id: string;
  runs: ExecutedRun[];
  skipped_splits: string[];
  comparisons: ExperimentComparison[];
  promotion_gate: PromotionGate;
}

export interface FieldAudit {
  grounded: number;
  unknown: number;
  example_span: string | null;
  example_paper_id: string | null;
}

export interface DossierEvidenceChain {
  gap_claim: string;
  why_it_matters: string;
  unresolved_boundary: string;
  candidate_research_question: string;
  minimum_experiment: string;
  supporting_papers: {
    paper_id: string;
    title: string;
    doi: string | null;
    source_url: string;
    publication_year: number | null;
  }[];
  supporting_evidence: {
    paper_id: string;
    field: string;
    evidence_span: string;
    evidence_source: string;
    extraction_method: string;
  }[];
  counter_evidence: {
    paper_id: string;
    title: string;
    doi: string | null;
    source: string;
    matched_query: string;
    why_relevant: string;
    evidence_span: string | null;
  }[];
  counter_search: {
    status: string;
    queries: string[];
    scope: Record<string, unknown>;
    errors: Record<string, unknown>[];
    detection_key: string;
  };
  prior_art: Record<string, unknown>[];
  novelty_risk: string;
  novelty_rationale: string;
  critic: Record<string, unknown>;
  python_validation: Record<string, unknown>;
  gate: Record<string, unknown>;
  confidence: { label: string; rationale: string };
  final_status: string;
  human_note: string | null;
  scope_notice: string;
}

export interface DossierLlm {
  configured: boolean;
  status: string;
  provider: string;
  model: string;
  max_calls: number;
  calls_used: number;
  cache_hits: number;
  role_usage: Record<string, number>;
  failed_calls: number;
  total_tokens: number | null;
  notice: string;
  gap_pipeline_id: string | null;
  gap_pipeline_status: string;
  stage_status: Record<string, string>;
  evidence_cards: number;
  audit_endpoint: string;
}

export interface Dossier {
  topic: string;
  workflow_id: string;
  generated_at: string;
  literature: {
    run_id: string;
    paper_count: number;
    extraction_mode: string;
    report_id: string;
    report_sections: {
      id: string;
      title: string;
      kind: "facts" | "author_claims" | "system_inference" | "mixed";
      paragraphs: number;
      paper_ids: string[];
    }[];
    section_kind_counts: Record<string, number>;
    caveats: string[];
    report_endpoint: string;
  };
  gaps: {
    gap_id: string;
    title: string;
    gap_type: GapType;
    status: string;
    confidence_label: ConfidenceLabel;
    supporting_papers: number;
    counter_evidence: number;
    discovery_mode: "rule_based" | "llm_pipeline";
    counter_status: string;
    novelty_risk: string;
    gate_status: string;
    validation_passed: boolean | null;
    evidence_chain: DossierEvidenceChain;
  }[];
  accepted_gap_id: string | null;
  hypothesis: string | null;
  hypothesis_status: string;
  experiment: {
    spec_id: string | null;
    run_count: number;
    confirmed_reference_cases: number;
    promotion_gate: PromotionGate | null;
    comparisons: ExperimentComparison[];
  };
  evolution: {
    round_id: string | null;
    proposals: number;
    skipped_mutations: Record<string, unknown>[];
    replay_spec_ids: string[];
  };
  skill: {
    active_version_id: string | null;
    active_version_number: number | null;
    total_versions: number;
    promotion_outcome: PromotionOutcome | null;
  };
  llm?: DossierLlm;
  acceptance_status:
    | "self_evolution_accepted"
    | "awaiting_reference_set"
    | "evolution_not_accepted";
}

export interface PromotionOutcome {
  decision: "promote" | "rollback" | "keep";
  decided_by: string;
  outcome: "promoted" | "refused" | "rolled_back" | "kept" | "invalid" | "awaiting_human";
  reasons?: string[];
  reason?: string;
  version_id?: string;
  version_number?: number;
  active_version_id: string | null;
  active_version_number: number | null;
  promotion_gate: PromotionGate;
}

/** Every step writes a different subset of these keys; all are optional. */
export interface StepOutputs {
  project_id?: string;
  topic?: string;
  query?: string;
  sources?: string[];
  top_k?: number;
  year_window?: (number | null)[];
  keywords_used?: { keyword: string; origin: string }[];
  keyword_count?: number;
  planned_api_requests?: number;
  run_id?: string;
  paper_count?: number;
  paper_ids?: string[];
  requests_made?: number;
  cache_hits?: number;
  duration_ms?: number;
  sources_requested?: string[];
  sources_failed?: string[];
  source_errors?: Record<string, unknown>[];
  extraction_mode?: string;
  fields_audited?: number;
  per_field?: Record<string, FieldAudit>;
  papers_with_abstract?: number;
  grounded_cells?: number;
  unknown_cells?: number;
  row_count?: number;
  columns?: string[];
  method_distribution?: Record<string, number>;
  year_range?: (number | null)[];
  available_filters?: { method_class?: string[]; dataset?: string[]; metric?: string[] };
  matrix_endpoint?: string;
  export_endpoint?: string;
  gap_count?: number;
  gaps?: GapSummary[];
  gaps_searched?: number;
  counter_evidence_found?: number;
  per_gap?: CounterGapResult[];
  candidates?: { gap_id: string; title: string; status: string }[];
  accepted_gap_id?: string;
  title?: string;
  decided_by?: string;
  human_note?: string;
  rejected_gap_ids?: string[];
  hypothesis?: string;
  hypothesis_status?: string;
  template_id?: string;
  gap_id?: string;
  unresolved_question?: string;
  experimentability?: Experimentability;
  spec_id?: string;
  case_ids?: string[];
  cases?: SpecCaseSummary[];
  split_counts?: Record<string, number>;
  verification_errors?: { doi: string; detail: string }[];
  baseline_version_id?: string;
  candidate_version_id?: string;
  candidate_version_number?: number;
  mutation_description?: string;
  seed?: {
    grounding: string;
    before_templates: string[];
    after_templates: string[];
    affordable_api_requests: number;
    affordable_query_count: number;
    preview_case_id: string;
    planned_queries: string[];
  };
  max_api_requests?: number;
  reference_provenance?: string;
  runs?: ExecutedRun[];
  run_count?: number;
  skipped_splits?: string[];
  evaluations?: ScoredRun[];
  comparisons?: ExperimentComparison[];
  promotion_gate?: PromotionGate;
  runs_without_snapshot?: string[];
  experience_count?: number;
  diagnosis_count?: number;
  diagnoses?: FailureDiagnosis[];
  failure_type_counts?: Record<string, number>;
  source_tallies?: { run_id: string; arm: string; tallies: SourceTally[] }[];
  round_id?: string;
  proposer_mode?: string;
  llm_skip_reason?: string;
  baseline_api_requests?: number;
  affordable_api_requests?: number;
  affordable_query_count?: number;
  proposals?: CandidateProposal[];
  skipped_mutations?: Record<string, unknown>[];
  replays?: ReplayResult[];
  replay_count?: number;
  outcome?: PromotionOutcome["outcome"];
  active_version_id?: string | null;
  active_version_number?: number | null;
  decision?: string;
  reasons?: string[];
  reason?: string;
  version_id?: string;
  version_number?: number;
  dossier?: Dossier;
  literature?: Dossier["literature"];
  experiment?: Dossier["experiment"];
  evolution?: Dossier["evolution"];
  skill?: Dossier["skill"];
  acceptance_status?: Dossier["acceptance_status"];
  generated_at?: string;
  workflow_id?: string;
}

export interface WorkflowStep {
  step_id: StepId;
  index: number;
  title: string;
  title_zh: string;
  status: StepStatus;
  attempts: number;
  started_at: string | null;
  finished_at: string | null;
  inputs: Record<string, unknown>;
  outputs: StepOutputs;
  error: string | null;
  notice: string;
}

export interface WorkflowContext {
  project_id?: string;
  literature_run_id?: string;
  paper_ids?: string[];
  gap_ids?: string[];
  accepted_gap_id?: string;
  approval_decided_by?: string;
  approval_note?: string;
  rejected_gap_ids?: string[];
  hypothesis?: string;
  spec_id?: string;
  case_ids?: string[];
  candidate_version_id?: string;
  baseline_run_ids?: string[];
  candidate_run_ids?: string[];
  promotion_gate?: PromotionGate;
  diagnosis_count?: number;
  round_id?: string;
  proposed_version_ids?: string[];
  replay_spec_ids?: string[];
  promotion_decision?: {
    decision: string;
    decided_by: string;
    version_id: string | null;
    reason: string;
    recorded_at: string;
  };
  promotion_outcome?: PromotionOutcome;
  dossier?: Dossier;
}

export interface WorkflowRun {
  workflow_id: string;
  topic: string;
  query: string;
  sources: string[];
  top_k: number;
  year_from: number | null;
  year_to: number | null;
  prefer_reviews: boolean;
  status: WorkflowStatus;
  current_step: StepId;
  steps: WorkflowStep[];
  context: WorkflowContext;
  notices: string[];
  created_at: string;
  updated_at: string;
}

export interface WorkflowResponse {
  workflow: WorkflowRun;
  executed: StepId[];
  notice: string;
}

export interface StepCatalogEntry {
  step_id: StepId;
  index: number;
  title: string;
  title_zh: string;
  requires_human: boolean;
}

export const STEP_STYLES: Record<StepStatus, string> = {
  pending: "bg-slate-700 text-slate-300",
  running: "bg-blue-900/50 text-blue-300",
  completed: "bg-green-900/50 text-green-300",
  failed: "bg-red-900/50 text-red-300",
  awaiting_human: "bg-amber-900/50 text-amber-300",
  awaiting_budget: "bg-orange-900/50 text-orange-300",
  skipped: "bg-slate-700 text-slate-400",
};

export const WORKFLOW_STYLES: Record<WorkflowStatus, string> = {
  running: "bg-blue-900/50 text-blue-300",
  awaiting_human: "bg-amber-900/50 text-amber-300",
  awaiting_budget: "bg-orange-900/50 text-orange-300",
  completed: "bg-green-900/50 text-green-300",
  failed: "bg-red-900/50 text-red-300",
};

export const STEP_LABELS: Record<StepId, string> = {
  research_topic: "研究主题",
  search_planning: "检索规划",
  literature_discovery: "文献检索",
  paper_extraction: "字段抽取",
  literature_matrix: "对比矩阵",
  gap_discovery: "空白发现",
  counter_evidence_search: "反证检索",
  human_approval: "人工确认",
  hypothesis: "研究假设",
  experiment_spec: "实验协议",
  baseline_execution: "基线执行",
  candidate_execution: "候选执行",
  independent_evaluation: "独立评测",
  failure_diagnosis: "失败诊断",
  skill_mutation: "技能变异",
  replay_evaluation: "回放评测",
  promotion_decision: "晋升 / 回滚",
  research_dossier: "研究档案",
};