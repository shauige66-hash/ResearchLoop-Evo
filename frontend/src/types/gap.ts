export type GapType =
  | "method"
  | "evaluation"
  | "generalization"
  | "reliability"
  | "efficiency"
  | "reproducibility"
  | "coverage"
  | "contradiction"
  | "integration";

export type GapStatus = "needs_human_review" | "accepted" | "rejected" | "edited";

export type ConfidenceLabel = "Low" | "Medium" | "High";

export type RiskLabel = "LOW" | "MEDIUM" | "HIGH";

export type CounterStatus =
  | "NOT_RUN"
  | "COUNTER_EVIDENCE_FOUND"
  | "NO_COUNTER_EVIDENCE_FOUND"
  | "COUNTER_SEARCH_FAILED";

export const GAP_TYPE_LABELS: Record<GapType, string> = {
  method: "方法空白 / Method",
  evaluation: "评测空白 / Evaluation",
  generalization: "泛化空白 / Generalization",
  reliability: "可靠性空白 / Reliability",
  efficiency: "效率空白 / Efficiency",
  reproducibility: "可复现空白 / Reproducibility",
  coverage: "覆盖空白 / Coverage",
  contradiction: "矛盾空白 / Contradiction",
  integration: "整合空白 / Integration",
};

export const COUNTER_STATUS_LABELS: Record<CounterStatus, string> = {
  NOT_RUN: "未检索 / NOT_RUN",
  COUNTER_EVIDENCE_FOUND: "找到反证 / COUNTER_EVIDENCE_FOUND",
  NO_COUNTER_EVIDENCE_FOUND: "范围内未发现 / NO_COUNTER_EVIDENCE_FOUND",
  COUNTER_SEARCH_FAILED: "检索失败 / COUNTER_SEARCH_FAILED",
};

export const RISK_STYLES: Record<RiskLabel, string> = {
  LOW: "bg-emerald-900/40 text-emerald-300 border-emerald-700",
  MEDIUM: "bg-amber-900/40 text-amber-300 border-amber-700",
  HIGH: "bg-red-900/40 text-red-300 border-red-700",
};

export const GAP_STATUS_LABELS: Record<GapStatus, string> = {
  needs_human_review: "待人工确认",
  accepted: "已接受",
  rejected: "已拒绝",
  edited: "已编辑",
};

export interface GapEvidenceItem {
  paper_id: string;
  title: string;
  doi: string | null;
  source_url: string;
  field: string;
  evidence_span: string;
  extraction_method: string;
}

export interface CounterEvidenceItem {
  paper_id: string;
  title: string;
  doi: string | null;
  source: string;
  source_url: string;
  publication_year: number | null;
  abstract_snippet: string | null;
  matched_query: string;
  why_relevant: string;
  matched_cue: string | null;
  evidence_span: string | null;
}

export interface RelatedWork {
  paper_id: string;
  title: string;
  doi: string | null;
  source_url: string;
  method_class: string | null;
  why_closest: string;
}

export interface Experimentability {
  testable_minimally: boolean;
  proposed_experiment: string;
  required_inputs: string[];
  blocking_reason: string | null;
}

export interface CounterSearchScope {
  sources?: string[];
  top_k?: number;
  query?: string;
  requests_made?: number;
  cache_hits?: number;
  papers_retrieved?: number;
  rejected_as_not_addressing_claim?: number;
  acceptance_rule?: string;
}

export interface EvidenceRef {
  paper_id: string;
  field: string;
  evidence_span: string;
}

export interface CandidateGap {
  gap_claim: string;
  gap_type: string;
  problem_context: string;
  already_solved: string;
  unresolved_boundary: string;
  why_it_matters: string;
  supporting_papers: string[];
  supporting_evidence: EvidenceRef[];
  contradicting_evidence: EvidenceRef[];
  candidate_research_question: string;
  minimum_experiment: string;
  testability: string;
  novelty_risk: RiskLabel;
  novelty_rationale?: string;
  uncertainties: string[];
}

export interface GapCritique {
  gap_index: number;
  evidence_grounding: number;
  cross_paper_support: number;
  specificity: number;
  testability: number;
  novelty_risk: RiskLabel;
  contradiction_risk: RiskLabel;
  major_weaknesses: string[];
  missing_evidence: string[];
  recommended_action: "accept" | "revise" | "reject";
  rationale: string;
  from_cache: boolean;
}

export interface GapCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface GapValidation {
  gap_index: number;
  checks: GapCheck[];
  unique_supporting_papers: number;
  unique_counter_papers: number;
  valid_evidence_refs: number;
  invalid_evidence_refs: Array<Record<string, string>>;
  missing_papers: string[];
  unverified_dois: string[];
  duplicate_paper_counting: boolean;
  counter_search_status: string;
  prior_art_collisions: number;
  novelty_risk: RiskLabel;
  evidence_contradiction: boolean;
  passed: boolean;
  reasons: string[];
}

export interface GapGateResult {
  gap_index: number;
  status: "accepted" | "needs_human_review" | "rejected";
  python_passed: boolean;
  critic_rejected: boolean;
  reasons: string[];
  thresholds: Record<string, unknown>;
  notice: string;
}

export interface PriorArtItem {
  paper_id: string;
  title: string;
  doi: string | null;
  source: string;
  source_url: string;
  publication_year: number | null;
  matched_query: string;
  matched_cue: string | null;
  evidence_span: string | null;
  why_relevant: string;
}

export interface ResearchGap {
  gap_id: string;
  title: string;
  description: string;
  gap_type: GapType;
  supporting_papers: string[];
  supporting_evidence: GapEvidenceItem[];
  counter_evidence: CounterEvidenceItem[];
  closest_related_work: RelatedWork[];
  unresolved_question: string;
  experimentability: Experimentability;
  confidence_label: ConfidenceLabel;
  status: GapStatus;
  run_id: string;
  topic: string;
  confidence_rationale: string;
  counter_search_queries: string[];
  counter_search_scope: CounterSearchScope;
  counter_search_errors: Array<{
    source: string;
    keyword: string | null;
    status: number | null;
    detail: string;
  }>;
  detection_key: string;
  scope_notice: string;
  human_note: string | null;
  created_at: string;
  updated_at: string | null;
  // Additive payload from the LLM gap pipeline. Rule-based gaps leave these empty.
  discovery_mode: "rule_based" | "llm_pipeline";
  pipeline_id: string | null;
  candidate: Partial<CandidateGap>;
  critique: Partial<GapCritique>;
  validation: Partial<GapValidation>;
  gate: Partial<GapGateResult>;
  counter_status: CounterStatus;
  prior_art: PriorArtItem[];
  novelty_risk: string;
}

export interface GapListResponse {
  gaps: ResearchGap[];
  total: number;
  notice: string;
  extraction_mode: "heuristic" | "llm" | "manual" | "none";
  detection_mode: string;
}

export interface GapReview {
  id: number;
  gap_id: string;
  status: GapStatus;
  human_note: string | null;
  reviewed_at: string;
}