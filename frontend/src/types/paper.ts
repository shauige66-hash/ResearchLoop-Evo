export interface FieldEvidence {
  value: string | null;
  evidence_source: "abstract" | "fulltext" | "manual" | "model_inference" | "none";
  evidence_span: string | null;
  source_url: string | null;
  confidence: "high" | "medium" | "low" | "unknown";
  updated_at: string | null;
}

export interface Paper {
  paper_id: string;
  title: string;
  authors: string[];
  publication_year: number | null;
  venue: string | null;
  doi: string | null;
  abstract: string | null;
  research_problem: FieldEvidence;
  method: FieldEvidence;
  dataset: FieldEvidence;
  evaluation_metrics: FieldEvidence;
  findings: FieldEvidence;
  limitations: FieldEvidence;
  future_work: FieldEvidence;
  source: "openalex" | "crossref" | "arxiv";
  source_url: string;
  oa_url: string | null;
  document_type: string | null;
  is_review: boolean;
  review_evidence: string | null;
  citation_count: number | null;
  language: string | null;
  relevance_score: number | null;
  evidence_status: string;
  missing_fields: string[];
  duplicate_of: string | null;
  merged_from: string[];
  retrieved_at: string;
  run_id: string | null;
}

export interface SearchMeta {
  retrieved_at: string;
  duration_ms: number;
  cache_hits: number;
  requests_made: number;
  sources_requested: string[];
  sources_failed: string[];
  keywords_used: Array<{ keyword: string; origin: "user" | "system_expanded" }>;
  notice: string;
}

export interface SourceError {
  source: string;
  keyword: string | null;
  status: number | null;
  detail: string;
}

export interface SearchResponse {
  run_id: string;
  project_id: string;
  topic: string;
  meta: SearchMeta;
  papers: Paper[];
  source_errors: SourceError[];
  stats: Record<string, number>;
}

export interface TopicInput {
  topic: string;
  field?: string;
  keywords?: string[];
  year_from?: number;
  year_to?: number;
  document_types?: string[];
  prefer_reviews?: boolean;
  sources?: string[];
  top_k?: number;
  expand_keywords?: boolean;
  refresh?: boolean;
}

export interface RunSummary {
  id: string;
  project_id: string;
  topic: string;
  created_at: string;
  finished_at: string | null;
  status: string;
  paper_count: number;
  sources: string[];
  failed_sources: string[];
}

export interface ReportSection {
  id: string;
  title: string;
  kind: "facts" | "author_claims" | "system_inference" | "mixed";
  paragraphs: string[];
  paper_ids: string[];
}

export interface ReportResponse {
  report_id: string;
  topic: string;
  generated_at: string;
  paper_count: number;
  sections: ReportSection[];
  markdown: string;
  caveats: string[];
}
