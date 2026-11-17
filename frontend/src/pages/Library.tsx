import { useEffect, useState } from "react";
import { listPapers } from "../api/client";
import type { Paper } from "../types/paper";
import { EXTRACTED_FIELDS } from "../types/paper";

export default function Library() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [reviewFilter, setReviewFilter] = useState<boolean | null>(null);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);

  useEffect(() => {
    loadPapers();
  }, [page, query, sourceFilter, reviewFilter]);

  async function loadPapers() {
    setLoading(true);
    setError(null);
    try {
      const result = await listPapers({
        page,
        page_size: 20,
        query: query || undefined,
        source: sourceFilter || undefined,
        is_review: reviewFilter === null ? undefined : reviewFilter,
      });
      setPapers(result.papers);
      setTotal(result.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load papers");
    } finally {
      setLoading(false);
    }
  }

  const totalPages = Math.ceil(total / 20);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Literature Library</h2>

      <div className="bg-slate-800 rounded-lg p-4 flex gap-4 items-center">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search papers..."
          className="flex-1 px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white placeholder-slate-400"
        />
        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          className="px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white"
        >
          <option value="">All Sources</option>
          <option value="openalex">OpenAlex</option>
          <option value="crossref">Crossref</option>
          <option value="arxiv">arXiv</option>
        </select>
        <select
          value={reviewFilter === null ? "" : reviewFilter ? "true" : "false"}
          onChange={(e) => setReviewFilter(e.target.value === "" ? null : e.target.value === "true")}
          className="px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white"
        >
          <option value="">All Types</option>
          <option value="true">Reviews Only</option>
          <option value="false">Non-Reviews Only</option>
        </select>
      </div>

      {error && (
        <div className="p-3 bg-red-900/30 border border-red-700 rounded text-red-300">{error}</div>
      )}

      {loading ? (
        <div className="text-center py-12">Loading...</div>
      ) : papers.length === 0 ? (
        <div className="text-center py-12 text-slate-500">
          No papers found. Try adjusting your filters or start a new search.
        </div>
      ) : (
        <>
          <div className="space-y-2">
            {papers.map((paper) => (
              <div
                key={paper.paper_id}
                onClick={() => setSelectedPaper(paper)}
                className="bg-slate-800 border border-slate-700 rounded-lg p-4 cursor-pointer hover:border-blue-500 transition"
              >
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="font-medium text-lg">{paper.title}</div>
                    <div className="text-sm text-slate-400 mt-1">
                      {paper.authors.slice(0, 3).join(", ")} {paper.authors.length > 3 ? "et al." : ""} •{" "}
                      {paper.publication_year || "n.d."} • {paper.venue || "unknown venue"}
                    </div>
                    <div className="flex gap-2 mt-2">
                      <span className="text-xs px-2 py-0.5 bg-blue-900/50 text-blue-300 rounded">
                        {paper.source}
                      </span>
                      {paper.is_review && (
                        <span className="text-xs px-2 py-0.5 bg-green-900/50 text-green-300 rounded">
                          Review
                        </span>
                      )}
                      <span className="text-xs px-2 py-0.5 bg-slate-700 text-slate-300 rounded">
                        {paper.evidence_status}
                      </span>
                      {paper.method_class && (
                        <span className="text-xs px-2 py-0.5 bg-amber-900/40 text-amber-300 rounded">
                          {paper.method_class} (system)
                        </span>
                      )}
                      {paper.citation_count !== null && (
                        <span className="text-xs px-2 py-0.5 bg-slate-700 text-slate-300 rounded">
                          {paper.citation_count} citations
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="flex justify-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:cursor-not-allowed rounded"
            >
              Previous
            </button>
            <span className="px-4 py-2 text-slate-400">
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:cursor-not-allowed rounded"
            >
              Next
            </button>
          </div>
        </>
      )}

      {selectedPaper && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" onClick={() => setSelectedPaper(null)}>
          <div className="bg-slate-800 rounded-lg max-w-3xl w-full max-h-[80vh] overflow-auto p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-xl font-bold">{selectedPaper.title}</h3>
              <button onClick={() => setSelectedPaper(null)} className="text-slate-400 hover:text-white">
                ✕
              </button>
            </div>
            <div className="space-y-3 text-sm">
              <div>
                <strong>Authors:</strong> {selectedPaper.authors.join(", ")}
              </div>
              <div>
                <strong>Year:</strong> {selectedPaper.publication_year || "Unknown"}
              </div>
              <div>
                <strong>Venue:</strong> {selectedPaper.venue || "Unknown"}
              </div>
              <div>
                <strong>DOI:</strong>{" "}
                {selectedPaper.doi ? (
                  <a href={`https://doi.org/${selectedPaper.doi}`} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">
                    {selectedPaper.doi}
                  </a>
                ) : (
                  "N/A"
                )}
              </div>
              <div>
                <strong>Source:</strong>{" "}
                <a href={selectedPaper.source_url} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">
                  {selectedPaper.source}
                </a>
              </div>
              {selectedPaper.abstract && (
                <div>
                  <strong>Abstract:</strong>
                  <p className="mt-1 text-slate-300">{selectedPaper.abstract}</p>
                </div>
              )}
              <div className="border-t border-slate-700 pt-3">
                <strong>Extracted Fields (Heuristic Mode · abstract only):</strong>
                <div className="mt-2 space-y-2">
                  {EXTRACTED_FIELDS.map((field) => {
                    const evidence = selectedPaper[field];
                    const grounded = evidence.evidence_status === "grounded";
                    return (
                      <div key={field} className="bg-slate-900/50 p-2 rounded">
                        <div className="font-medium text-slate-200">
                          {field.replace(/_/g, " ")}
                          {!grounded && (
                            <span className="ml-2 text-xs text-slate-500">unknown</span>
                          )}
                        </div>
                        {grounded ? (
                          <>
                            <div className="text-xs text-slate-300 mt-1">{evidence.value}</div>
                            {evidence.evidence_span && (
                              <blockquote className="border-l-2 border-blue-700 pl-2 mt-1 text-xs text-slate-400 italic">
                                “{evidence.evidence_span}”
                              </blockquote>
                            )}
                            <div className="text-xs text-slate-500 mt-1">
                              {evidence.evidence_source} · {evidence.extraction_method} ·{" "}
                              {evidence.confidence}
                            </div>
                          </>
                        ) : (
                          <div className="text-xs text-slate-500 mt-1">
                            检索到的材料中未发现该字段的证据。
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
