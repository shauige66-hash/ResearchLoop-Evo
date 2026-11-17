import type {
  MatrixFilters,
  MatrixResponse,
  Paper,
  ReportResponse,
  RunSummary,
  SearchResponse,
  TopicInput,
} from "../types/paper";
import type {
  GapListResponse,
  GapReview,
  GapStatus,
  ResearchGap,
} from "../types/gap";
import type {
  Arm,
  BenchmarkCase,
  BenchmarkCaseResponse,
  BenchmarkListResponse,
  CompareResponse,
  ExperimentRun,
  ExperimentSpec,
  ExperimentTemplate,
  ReferenceStatus,
  RunResponse,
  SearchStrategy,
  SkillVersion,
  SpecDetail,
  Split,
  VerifyResponse,
} from "../types/experiment";
import type {
  EvolutionRound,
  FailureTypeCatalog,
  RoundSummary,
  SkillEvent,
  SkillVersionDetail,
} from "../types/evolution";

const API_BASE = "/api";

function describeError(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => `${(d.loc || []).join(".")}: ${d.msg}`)
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    const obj = detail as Record<string, unknown>;
    const reasons = Array.isArray(obj.reasons)
      ? obj.reasons.filter((r): r is string => typeof r === "string")
      : [];
    if (typeof obj.message === "string") {
      return reasons.length > 0
        ? `${obj.message}\n${reasons.map((r) => `· ${r}`).join("\n")}`
        : obj.message;
    }
    return JSON.stringify(obj);
  }
  return `HTTP ${status}`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(describeError(error.detail, response.status));
  }
  return response.json();
}

export async function searchLiterature(topic: TopicInput): Promise<SearchResponse> {
  return request<SearchResponse>("/literature/search", {
    method: "POST",
    body: JSON.stringify(topic),
  });
}

export async function listPapers(params?: {
  project_id?: string;
  run_id?: string;
  year?: number;
  source?: string;
  is_review?: boolean;
  evidence_status?: string;
  query?: string;
  page?: number;
  page_size?: number;
}): Promise<{ papers: Paper[]; total: number; page: number; page_size: number }> {
  const searchParams = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      searchParams.append(key, String(value));
    }
  });
  return request(`/literature/papers?${searchParams.toString()}`);
}

export async function getPaper(paperId: string): Promise<Paper> {
  return request(`/literature/papers/${paperId}`);
}

export async function updatePaperField(
  paperId: string,
  field: string,
  patch: {
    value: string | null;
    evidence_source: string;
    evidence_span?: string;
    note?: string;
  }
): Promise<Paper> {
  return request(`/literature/papers/${paperId}/fields/${field}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function listRuns(): Promise<RunSummary[]> {
  return request("/literature/runs");
}

export async function generateMatrix(
  paperIds: string[],
  filters: MatrixFilters = {}
): Promise<MatrixResponse> {
  return request("/literature/matrix", {
    method: "POST",
    body: JSON.stringify({ paper_ids: paperIds, ...filters }),
  });
}

export function exportMatrixUrl(format: "csv" | "json", paperIds: string[]): string {
  return `${API_BASE}/literature/matrix/export?format=${format}&paper_ids=${paperIds.join(",")}`;
}

export async function generateReport(
  runId?: string,
  paperIds?: string[]
): Promise<ReportResponse> {
  return request("/literature/report", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, paper_ids: paperIds || [] }),
  });
}

export async function healthCheck(): Promise<{ status: string; timestamp: string; version: string }> {
  return request("/health");
}

export async function discoverGaps(payload: {
  run_id?: string;
  paper_ids?: string[];
  topic?: string;
  run_counter_search?: boolean;
  counter_top_k?: number;
}): Promise<GapListResponse> {
  return request("/gaps/discover", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listGaps(params?: {
  run_id?: string;
  status?: string;
  gap_type?: string;
}): Promise<GapListResponse> {
  const searchParams = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value) searchParams.append(key, value);
  });
  return request(`/gaps?${searchParams.toString()}`);
}

export async function getGap(
  gapId: string
): Promise<{ gap: ResearchGap; reviews: GapReview[] }> {
  return request(`/gaps/${gapId}`);
}

export async function reviewGap(
  gapId: string,
  payload: {
    status: GapStatus;
    human_note?: string;
    title?: string;
    description?: string;
    unresolved_question?: string;
  }
): Promise<ResearchGap> {
  return request(`/gaps/${gapId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function rerunCounterSearch(
  gapId: string,
  topK = 10
): Promise<ResearchGap> {
  return request(`/gaps/${gapId}/counter-search?top_k=${topK}`, { method: "POST" });
}

// ------------------------------------------------------------- experiment lab
export async function listTemplates(): Promise<{
  templates: ExperimentTemplate[];
  total: number;
}> {
  return request("/experiments/templates");
}

export async function listBenchmarkCases(params?: {
  split?: Split;
  reference_status?: ReferenceStatus;
}): Promise<BenchmarkListResponse> {
  const searchParams = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value) searchParams.append(key, value);
  });
  return request(`/experiments/benchmark/cases?${searchParams.toString()}`);
}

export async function createBenchmarkCase(payload: {
  topic: string;
  query: string;
  reference_dois?: string[];
  split?: Split;
  notes?: string;
  verify_references?: boolean;
}): Promise<BenchmarkCaseResponse> {
  return request("/experiments/benchmark/cases", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function addBenchmarkReferences(
  caseId: string,
  dois: string[]
): Promise<BenchmarkCaseResponse> {
  return request(`/experiments/benchmark/cases/${caseId}/references`, {
    method: "POST",
    body: JSON.stringify({ dois }),
  });
}

export async function confirmBenchmarkReferences(
  caseId: string,
  confirmedBy: string,
  dois?: string[]
): Promise<BenchmarkCaseResponse> {
  return request(`/experiments/benchmark/cases/${caseId}/confirm`, {
    method: "POST",
    body: JSON.stringify({ confirmed_by: confirmedBy, dois: dois || [] }),
  });
}

export async function assignSplits(): Promise<BenchmarkListResponse> {
  return request("/experiments/benchmark/assign-splits", { method: "POST" });
}

export async function designExperiment(payload: {
  case_ids: string[];
  baseline_version_id: string;
  candidate_version_id: string;
  gap_id?: string | null;
  sources?: string[];
  year_from?: number | null;
  year_to?: number | null;
  top_k?: number;
  max_api_requests?: number;
  use_cache?: boolean;
}): Promise<ExperimentSpec> {
  return request("/experiments/design", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listSpecs(): Promise<{ specs: ExperimentSpec[]; total: number }> {
  return request("/experiments/specs");
}

export async function getSpec(specId: string): Promise<SpecDetail> {
  return request(`/experiments/specs/${specId}`);
}

export async function lockCandidate(specId: string): Promise<ExperimentSpec> {
  return request(`/experiments/specs/${specId}/lock`, { method: "POST" });
}

export async function runExperiment(payload: {
  spec_id: string;
  split?: Split | null;
  arms?: Arm[];
}): Promise<RunResponse> {
  return request("/experiments/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listExperimentRuns(params?: {
  spec_id?: string;
  case_id?: string;
  arm?: Arm;
  split?: Split;
}): Promise<{ runs: ExperimentRun[]; total: number }> {
  const searchParams = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value) searchParams.append(key, value);
  });
  return request(`/experiments/runs?${searchParams.toString()}`);
}

export async function getExperimentRun(
  runId: string
): Promise<{ run: ExperimentRun; snapshot_available: boolean; case: BenchmarkCase | null }> {
  return request(`/experiments/runs/${runId}`);
}

export async function verifyExperiment(runId: string): Promise<VerifyResponse> {
  return request("/experiments/verify", {
    method: "POST",
    body: JSON.stringify({ run_id: runId }),
  });
}

export async function compareSpec(specId: string): Promise<CompareResponse> {
  return request(`/experiments/compare/${specId}`);
}

// ------------------------------------------------------------- skill registry
export async function listSkillVersions(): Promise<{
  skill_id: string;
  versions: SkillVersion[];
  total: number;
  evolvable_components: string[];
  immutable_components: string[];
}> {
  return request("/skills/versions");
}

export async function getActiveSkill(): Promise<{ version: SkillVersion }> {
  return request("/skills/active");
}

export async function createSkillVersion(payload: {
  strategy: SearchStrategy;
  mutation_description: string;
  source_trials?: string[];
  parent_version?: string | null;
}): Promise<SkillVersion> {
  return request("/skills/versions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function previewSkillQueries(payload: {
  version_id: string;
  topic: string;
  query: string;
}): Promise<{ version_id: string; queries: string[]; query_count: number; max_keywords: number }> {
  return request("/skills/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getSkillVersion(versionId: string): Promise<SkillVersionDetail> {
  return request(`/skills/versions/${versionId}`);
}

export async function listSkillEvents(versionId?: string): Promise<{
  events: SkillEvent[];
  total: number;
}> {
  const suffix = versionId ? `?version_id=${versionId}` : "";
  return request(`/skills/events${suffix}`);
}

export async function getPromotionHistory(): Promise<{
  skill_id: string;
  events: SkillEvent[];
  total: number;
}> {
  return request("/skills/history");
}

export async function evaluateSkill(payload: {
  spec_id: string;
  split?: Split | null;
}): Promise<RunResponse & { split: Split | null }> {
  return request("/skills/evaluate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function promoteSkill(payload: {
  spec_id: string;
  version_id: string;
  decided_by: string;
}): Promise<{ version: SkillVersion; events: SkillEvent[]; notice: string }> {
  return request("/skills/promote", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function rollbackSkill(payload: {
  version_id: string;
  decided_by: string;
  reason?: string;
}): Promise<{ version: SkillVersion; events: SkillEvent[]; notice: string }> {
  return request("/skills/rollback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ------------------------------------------------------------- evolution engine
export async function getFailureTypes(): Promise<FailureTypeCatalog> {
  return request("/evolve/failure-types");
}

export async function evolveSkills(payload: {
  spec_id: string;
  max_candidates?: number;
  use_llm?: boolean;
}): Promise<EvolutionRound> {
  return request("/evolve/skills", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listEvolutionRounds(specId?: string): Promise<{
  rounds: RoundSummary[];
  total: number;
}> {
  const suffix = specId ? `?spec_id=${specId}` : "";
  return request(`/evolve/rounds${suffix}`);
}

export async function getEvolutionRound(roundId: string): Promise<{ round: EvolutionRound }> {
  return request(`/evolve/rounds/${roundId}`);
}
