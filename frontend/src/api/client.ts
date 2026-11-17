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
    if (typeof obj.message === "string") return obj.message;
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
