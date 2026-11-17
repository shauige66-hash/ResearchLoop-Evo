import type { Arm, ReferenceStatus, SearchStrategy, Split } from "./experiment";

export type FailureType =
  | "query_too_narrow"
  | "missing_synonym"
  | "wrong_research_terminology"
  | "source_coverage_insufficient"
  | "time_filter_too_restrictive"
  | "api_failure";

export const FAILURE_LABELS: Record<FailureType, string> = {
  query_too_narrow: "查询过窄",
  missing_synonym: "缺少同义词",
  wrong_research_terminology: "术语不当",
  source_coverage_insufficient: "来源覆盖不足",
  time_filter_too_restrictive: "时间过滤过严",
  api_failure: "API 失败",
};

export const FAILURE_STYLES: Record<FailureType, string> = {
  query_too_narrow: "bg-blue-900/50 text-blue-300",
  missing_synonym: "bg-cyan-900/50 text-cyan-300",
  wrong_research_terminology: "bg-indigo-900/50 text-indigo-300",
  source_coverage_insufficient: "bg-purple-900/50 text-purple-300",
  time_filter_too_restrictive: "bg-orange-900/50 text-orange-300",
  api_failure: "bg-red-900/50 text-red-300",
};

export interface SourceTally {
  source: string;
  paper_count: number;
}

export interface TrialExperience {
  run_id: string;
  spec_id: string;
  case_id: string;
  topic: string;
  query: string;
  split: Split;
  arm: Arm;
  skill_version_id: string;
  queries_used: string[];
  status: string;
  reference_status: ReferenceStatus;
  unique_paper_count: number;
  top_k: number;
  api_request_count: number;
  cache_hits: number;
  execution_time_ms: number;
  coverage_at_k: number | null;
  hit_references: string[];
  missed_references: string[];
  source_errors: Record<string, unknown>[];
  source_tallies: SourceTally[];
  source_priority: string[];
  retrieved_titles: string[];
  reference_titles: string[];
  reference_years: number[];
  effective_year_from: number | null;
  effective_year_to: number | null;
  snapshot_available: boolean;
}

export interface FailureDiagnosis {
  failure_type: FailureType;
  run_id: string;
  case_id: string;
  split: Split;
  evidence: Record<string, unknown>;
  rationale: string;
  suggested_component: string;
}

export interface StrategyChange {
  component: string;
  before: unknown;
  after: unknown;
}

export interface CandidateProposal {
  version_id: string;
  parent_version: string;
  version_number: number;
  mutation_description: string;
  source_trials: string[];
  addressed_failures: FailureType[];
  changes: StrategyChange[];
  strategy: SearchStrategy;
  created_at: string;
  projected_query_count: number;
  projected_api_requests: number;
  projected_request_ratio: number | null;
  grounding: string;
}

export interface EvolutionRound {
  round_id: string;
  spec_id: string;
  parent_version_id: string;
  proposer_mode: "deterministic" | "llm";
  llm_skip_reason: string;
  experiences: TrialExperience[];
  diagnoses: FailureDiagnosis[];
  proposals: CandidateProposal[];
  skipped_mutations: { mutation: string; reason: string }[];
  baseline_api_requests: number;
  affordable_api_requests: number;
  affordable_query_count: number;
  created_at: string;
  notice: string;
}

export interface RoundSummary {
  round_id: string;
  spec_id: string;
  parent_version_id: string;
  proposer_mode: "deterministic" | "llm";
  experience_count: number;
  diagnosis_count: number;
  proposal_count: number;
  affordable_query_count: number;
  created_at: string;
}

export interface FailureTypeCatalog {
  failure_types: { key: FailureType; label: string }[];
  max_candidates_per_round: number;
  notice: string;
}

export interface SkillEvent {
  id: number;
  version_id: string;
  event: string;
  detail: Record<string, unknown>;
  created_at: string;
  version_number?: number;
  mutation_description?: string;
}

export interface SkillVersionDetail {
  version: import("./experiment").SkillVersion;
  events: SkillEvent[];
  runs_using_version: number;
}