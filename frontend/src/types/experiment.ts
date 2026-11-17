export type Split = "development" | "validation" | "holdout";
export type Arm = "baseline" | "candidate";
export type RunStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "awaiting_reference_set";
export type ReferenceStatus = "awaiting_reference_set" | "confirmed";
export type SkillStatus = "active" | "candidate" | "archived" | "rejected";

export const SPLIT_LABELS: Record<Split, string> = {
  development: "Development（开发集）",
  validation: "Validation（验证集）",
  holdout: "Holdout（锁定终检）",
};

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  pending: "等待执行",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
  awaiting_reference_set: "等待人工确认参考集",
};

export interface BenchmarkReference {
  doi: string;
  title: string;
  source_url: string;
  verified_via: "crossref" | "openalex" | "manual";
  verified_at: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
}

export interface BenchmarkCase {
  case_id: string;
  topic: string;
  query: string;
  reference_dois: string[];
  split: Split;
  source: "manual" | "derived_from_run";
  verified_by: string | null;
  created_at: string;
  notes: string;
  references: BenchmarkReference[];
}

export interface BenchmarkListResponse {
  cases: BenchmarkCase[];
  total: number;
  confirmed_cases: number;
  awaiting_cases: number;
  split_counts: Record<string, number>;
  notice: string;
}

export interface BenchmarkCaseResponse {
  case: BenchmarkCase;
  verification_errors: { doi: string; detail: string }[];
}

export interface SearchFilters {
  year_from: number | null;
  year_to: number | null;
  document_types: string[];
  prefer_reviews: boolean;
}

export interface RetrievalBudget {
  top_k: number;
  max_keywords: number;
  max_api_requests: number;
}

export interface SearchStrategy {
  query_templates: string[];
  domain_synonyms: Record<string, string[]>;
  keyword_expansion_rules: ("topic_terms" | "domain_synonyms" | "query_terms")[];
  source_priority: string[];
  search_filters: SearchFilters;
  retrieval_budget: RetrievalBudget;
}

export interface SkillVersion {
  version_id: string;
  skill_id: string;
  version_number: number;
  parent_version: string | null;
  strategy: SearchStrategy;
  mutation_description: string;
  source_trials: string[];
  created_at: string;
  status: SkillStatus;
  created_by: "seed" | "human" | "proposer";
}

export interface ExperimentSpec {
  spec_id: string;
  template_id: string;
  hypothesis: string;
  gap_id: string | null;
  case_ids: string[];
  sources: string[];
  year_from: number | null;
  year_to: number | null;
  top_k: number;
  max_api_requests: number;
  use_cache: boolean;
  baseline_version_id: string;
  candidate_version_id: string;
  created_at: string;
  created_by: string;
  candidate_locked_at: string | null;
}

export interface EvaluationReport {
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
  dataset_fingerprint: string;
  evaluator_version: string;
  computed_at: string;
  notice: string;
}

export interface SourceErrorRecord {
  source: string;
  keyword: string | null;
  status: number | null;
  detail: string;
}

export interface ExperimentRun {
  run_id: string;
  spec_id: string;
  case_id: string;
  arm: Arm;
  skill_version_id: string;
  skill_snapshot: SearchStrategy;
  queries_used: string[];
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  api_request_count: number;
  cache_hits: number;
  unique_paper_count: number;
  execution_time_ms: number;
  retrieved_dois: string[];
  retrieved_paper_ids: string[];
  source_errors: SourceErrorRecord[];
  raw_snapshot_path: string | null;
  evaluation: EvaluationReport | null;
  error: string | null;
  literature_run_id: string | null;
}

export interface ExperimentComparison {
  spec_id: string;
  case_id: string;
  split: Split;
  baseline: ExperimentRun | null;
  candidate: ExperimentRun | null;
  coverage_delta: number | null;
  request_ratio: number | null;
  reference_status: ReferenceStatus;
  notice: string;
}

export interface PromotionGate {
  allowed: boolean;
  reasons: string[];
}

export interface RunResponse {
  spec_id: string;
  runs: ExperimentRun[];
  comparisons: ExperimentComparison[];
  promotion_gate: PromotionGate;
  notice: string;
}

export interface VerifyResponse {
  run_id: string;
  evaluation: EvaluationReport;
  stored_evaluation: EvaluationReport | null;
  recomputed_from: string;
  matches_stored: boolean;
  notice: string;
}

export interface ExperimentTemplate {
  template_id: string;
  name: string;
  hypothesis: string;
  hypothesis_status: string;
  arms: { arm: Arm; description: string }[];
  metrics: { key: string; label: string; needs_references: boolean }[];
  evaluator_version: string;
  notice: string;
}

export interface SpecDetail {
  spec: ExperimentSpec;
  cases: BenchmarkCase[];
  run_count: number;
  promotion_gate: PromotionGate;
}

export interface CompareResponse {
  spec: ExperimentSpec;
  comparisons: ExperimentComparison[];
  promotion_gate: PromotionGate;
  notice: string;
}