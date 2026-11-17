import type {
  Paper,
  ReportResponse,
  SearchResponse,
  TopicInput,
} from "../types/paper";

const API_BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail?.message || error.detail || `HTTP ${response.status}`);
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

export async function generateMatrix(paperIds: string[]): Promise<any> {
  return request("/literature/matrix", {
    method: "POST",
    body: JSON.stringify({ paper_ids: paperIds }),
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
