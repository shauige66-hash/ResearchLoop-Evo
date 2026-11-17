export type GapType =
  | "method"
  | "evaluation"
  | "generalization"
  | "reliability"
  | "efficiency"
  | "reproducibility";

export type GapStatus = "needs_human_review" | "accepted" | "rejected" | "edited";

export type ConfidenceLabel = "Low" | "Medium" | "High";

export const GAP_TYPE_LABELS: Record<GapType, string> = {
  method: "方法空白 / Method",
  evaluation: "评测空白 / Evaluation",
  generalization: "泛化空白 / Generalization",
  reliability: "可靠性空白 / Reliability",
  efficiency: "效率空白 / Efficiency",
  reproducibility: "可复现空白 / Reproducibility",
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