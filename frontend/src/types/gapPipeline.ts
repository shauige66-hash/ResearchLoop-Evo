import type {
  CandidateGap,
  CounterStatus,
  GapCritique,
  GapGateResult,
  GapValidation,
  PriorArtItem,
  ResearchGap,
  RiskLabel,
} from "./gap";

export type StageId =
  | "planner"
  | "selection"
  | "literature_analysis"
  | "gap_analysis"
  | "gap_critic"
  | "counter_evidence"
  | "validation";

export type StageStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export type PipelineStatus =
  | "running"
  | "completed"
  | "failed"
  | "awaiting_budget"
  | "awaiting_human"
  | "not_configured";

export interface ResearchPlan {
  research_topic: string;
  research_questions: string[];
  search_angles: string[];
  review_queries: string[];
  method_queries: string[];
  challenge_queries: string[];
  recent_queries: string[];
  foundational_queries: string[];
  inclusion_criteria: string[];
  exclusion_criteria: string[];
}

export interface EvidenceCardField {
  claim: string;
  evidence_span: string;
  evidence_source: "abstract";
  confidence: "high" | "medium" | "low";
}

export const CARD_FIELDS = [
  "research_problem",
  "method",
  "setting",
  "dataset",
  "evaluation",
  "limitations",
  "future_work",
] as const;

export type CardFieldName = (typeof CARD_FIELDS)[number];

export const CARD_FIELD_LABELS: Record<CardFieldName, string> = {
  research_problem: "研究问题",
  method: "方法",
  setting: "Agent 架构 / 场景",
  dataset: "数据集",
  evaluation: "评测指标",
  limitations: "局限",
  future_work: "未来工作",
};

export interface EvidenceCard extends Record<CardFieldName, EvidenceCardField> {
  paper_id: string;
  pipeline_id: string;
  title: string;
  doi: string | null;
  source_url: string;
  extraction_method: "llm" | "heuristic";
  abstract_hash: string;
  prompt_version: string;
  rejected_fields: Array<Record<string, string>>;
  grounded_fields: string[];
  from_cache: boolean;
  created_at: string;
}

export interface CounterSearchOutcome {
  status: CounterStatus;
  detection_key: string;
  queries: string[];
  sources: string[];
  requests_made: number;
  cache_hits: number;
  papers_retrieved: number;
  rejected_as_not_addressing_claim: number;
  prior_art: PriorArtItem[];
  errors: Array<Record<string, unknown>>;
  query_source: string;
  notice: string;
}

export interface ValidatedGap {
  candidate: CandidateGap;
  critique: GapCritique | null;
  counter: CounterSearchOutcome;
  validation: GapValidation;
  gate: GapGateResult;
  gap_id: string | null;
}

export interface CrossPaperSynthesis {
  already_solved: string[];
  main_method_routes: string[];
  consistent_findings: string[];
  conflicting_findings: string[];
  uncovered_scenarios: string[];
  shared_limitations: string[];
  uncovered_metrics: string[];
  repeatedly_mentioned_unresolved: string[];
  mature_but_uncombined: string[];
}

export interface PipelineStage {
  stage_id: StageId;
  index: number;
  title: string;
  title_zh: string;
  status: StageStatus;
  attempts: number;
  started_at: string | null;
  finished_at: string | null;
  outputs: Record<string, unknown>;
  error: string | null;
  notice: string;
  llm_calls: number;
  cache_hits: number;
}

export interface GapPipelineRun {
  pipeline_id: string;
  topic: string;
  run_id: string;
  workflow_id: string | null;
  status: PipelineStatus;
  current_stage: StageId;
  stages: PipelineStage[];
  paper_ids: string[];
  selected_paper_ids: string[];
  max_papers: number;
  max_gaps: number;
  run_counter_search: boolean;
  plan: ResearchPlan | null;
  synthesis: CrossPaperSynthesis | null;
  gaps: ValidatedGap[];
  llm_calls_used: number;
  llm_cache_hits: number;
  llm_budget: number;
  provider: string;
  model: string;
  notices: string[];
  created_at: string;
  updated_at: string;
}

export interface PipelineResponse {
  pipeline: GapPipelineRun;
  executed: StageId[];
  notice: string;
}

export interface PipelineDetail {
  pipeline: GapPipelineRun;
  evidence_cards: EvidenceCard[];
  gaps: ResearchGap[];
  llm_calls: LLMCallRecord[];
  llm_usage: LLMUsageSummary;
}

export interface LLMUsageSummary {
  configured: boolean;
  status: string;
  provider: string;
  model: string;
  max_calls: number;
  calls_used: number;
  cache_hits: number;
  role_budgets: Record<string, number>;
  role_usage: Record<string, number>;
  failed_calls: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  notice: string;
}

export interface LLMCallRecord {
  request_id: string;
  agent_role: string;
  provider: string;
  model: string;
  status: string;
  prompt_version: string;
  prompt_hash: string;
  response_hash: string;
  pipeline_id: string | null;
  paper_id: string | null;
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  error: string | null;
  created_at: string;
}

export const LLM_NOT_CONFIGURED = "LLM_NOT_CONFIGURED";

export const PIPELINE_STATUS_LABELS: Record<PipelineStatus, string> = {
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  awaiting_budget: "等待预算",
  awaiting_human: "等待人工",
  not_configured: LLM_NOT_CONFIGURED,
};

export const PIPELINE_STATUS_STYLES: Record<PipelineStatus, string> = {
  running: "bg-blue-900/50 text-blue-300 border-blue-700",
  completed: "bg-emerald-900/50 text-emerald-300 border-emerald-700",
  failed: "bg-red-900/40 text-red-300 border-red-700",
  awaiting_budget: "bg-orange-900/50 text-orange-300 border-orange-700",
  awaiting_human: "bg-amber-900/50 text-amber-300 border-amber-700",
  not_configured: "bg-slate-700/60 text-slate-300 border-slate-600",
};

export const STAGE_STATUS_STYLES: Record<StageStatus, string> = {
  pending: "bg-slate-700 text-slate-300",
  running: "bg-blue-900/50 text-blue-300",
  completed: "bg-emerald-900/50 text-emerald-300",
  failed: "bg-red-900/40 text-red-300",
  skipped: "bg-slate-700 text-slate-400",
};

export const ROLE_LABELS: Record<string, string> = {
  research_planner: "Research Planner",
  literature_analyst: "Literature Analyst",
  gap_analyst: "Gap Analyst",
  gap_critic: "Gap Critic",
  counter_query: "Counter-query Generator",
  candidate_proposer: "Skill Candidate Proposer",
};

export const CRITIC_SCORE_LABELS: Array<[keyof GapCritique, string]> = [
  ["evidence_grounding", "证据扎实度"],
  ["cross_paper_support", "跨论文支持"],
  ["specificity", "具体性"],
  ["testability", "可验证性"],
];

export const RISK_ORDER: RiskLabel[] = ["LOW", "MEDIUM", "HIGH"];