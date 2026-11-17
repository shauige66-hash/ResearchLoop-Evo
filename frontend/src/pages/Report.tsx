import { useState } from "react";
import { listPapers, generateReport } from "../api/client";
import type { Paper, ReportResponse } from "../types/paper";

export default function Report() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useState(() => {
    loadPapers();
  });

  async function loadPapers() {
    try {
      const result = await listPapers({ page: 1, page_size: 100 });
      setPapers(result.papers);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load papers");
    }
  }

  function toggleSelection(paperId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(paperId)) {
        next.delete(paperId);
      } else {
        next.add(paperId);
      }
      return next;
    });
  }

  async function handleGenerateReport() {
    if (selectedIds.size === 0) {
      setError("Select at least 1 paper to generate a report");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await generateReport(undefined, Array.from(selectedIds));
      setReport(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate report");
    } finally {
      setLoading(false);
    }
  }

  const kindColors: Record<string, string> = {
    facts: "bg-blue-900/30 border-blue-700 text-blue-300",
    author_claims: "bg-green-900/30 border-green-700 text-green-300",
    system_inference: "bg-yellow-900/30 border-yellow-700 text-yellow-300",
    mixed: "bg-purple-900/30 border-purple-700 text-purple-300",
  };

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Research Report</h2>

      <div className="bg-slate-800 rounded-lg p-4">
        <h3 className="text-lg font-semibold mb-3">Select Papers</h3>
        <div className="space-y-2 max-h-64 overflow-auto">
          {papers.map((paper) => (
            <label key={paper.paper_id} className="flex items-center gap-3 p-2 hover:bg-slate-700 rounded cursor-pointer">
              <input
                type="checkbox"
                checked={selectedIds.has(paper.paper_id)}
                onChange={() => toggleSelection(paper.paper_id)}
                className="rounded"
              />
              <div className="flex-1">
                <div className="font-medium">{paper.title}</div>
                <div className="text-xs text-slate-400">
                  {paper.authors.slice(0, 2).join(", ")} • {paper.publication_year || "n.d."}
                </div>
              </div>
            </label>
          ))}
        </div>
        <button
          onClick={handleGenerateReport}
          disabled={loading || selectedIds.size === 0}
          className="mt-4 w-full py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 disabled:cursor-not-allowed rounded font-medium transition"
        >
          {loading ? "Generating..." : `Generate Report (${selectedIds.size} selected)`}
        </button>
      </div>

      {error && (
        <div className="p-3 bg-red-900/30 border border-red-700 rounded text-red-300">{error}</div>
      )}

      {report && (
        <div className="space-y-4">
          <div className="bg-slate-800 rounded-lg p-6">
            <h3 className="text-xl font-bold mb-2">{report.topic}</h3>
            <div className="text-sm text-slate-400 mb-4">
              Generated: {new Date(report.generated_at).toLocaleString()} • Papers: {report.paper_count}
            </div>

            <div className="space-y-6">
              {report.sections.map((section) => (
                <div key={section.id} className="border border-slate-700 rounded-lg p-4">
                  <div className="flex items-center gap-3 mb-3">
                    <h4 className="text-lg font-semibold">{section.title}</h4>
                    <span className={`text-xs px-2 py-0.5 rounded border ${kindColors[section.kind]}`}>
                      {section.kind.replace("_", " ")}
                    </span>
                  </div>
                  <div className="space-y-2">
                    {section.paragraphs.map((para, i) => (
                      <p key={i} className="text-sm text-slate-300">{para}</p>
                    ))}
                  </div>
                  {section.paper_ids.length > 0 && (
                    <div className="mt-3 text-xs text-slate-500">
                      Cited papers: {section.paper_ids.slice(0, 5).join(", ")}
                      {section.paper_ids.length > 5 && ` +${section.paper_ids.length - 5} more`}
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="mt-6 border-t border-slate-700 pt-4">
              <h4 className="font-semibold mb-2">Caveats</h4>
              <ul className="text-sm text-slate-400 space-y-1">
                {report.caveats.map((caveat, i) => (
                  <li key={i}>• {caveat}</li>
                ))}
              </ul>
            </div>
          </div>

          <div className="bg-slate-800 rounded-lg p-4">
            <h3 className="text-lg font-semibold mb-3">Markdown Export</h3>
            <textarea
              value={report.markdown}
              readOnly
              className="w-full h-64 bg-slate-900 border border-slate-700 rounded p-3 text-xs font-mono text-slate-300"
            />
            <button
              onClick={() => {
                const blob = new Blob([report.markdown], { type: "text/markdown" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "report.md";
                a.click();
                URL.revokeObjectURL(url);
              }}
              className="mt-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm"
            >
              Download Markdown
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
