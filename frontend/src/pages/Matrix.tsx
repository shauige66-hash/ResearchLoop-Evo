import { useState } from "react";
import { listPapers, generateMatrix, exportMatrixUrl } from "../api/client";
import type { Paper } from "../types/paper";

export default function Matrix() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [matrix, setMatrix] = useState<any>(null);
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

  async function handleGenerateMatrix() {
    if (selectedIds.size < 2) {
      setError("Select at least 2 papers to generate a matrix");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await generateMatrix(Array.from(selectedIds));
      setMatrix(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate matrix");
    } finally {
      setLoading(false);
    }
  }

  const columns = matrix?.columns || [];
  const rows = matrix?.rows || [];

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Literature Matrix</h2>

      <div className="bg-slate-800 rounded-lg p-4">
        <h3 className="text-lg font-semibold mb-3">Select Papers (minimum 2)</h3>
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
          onClick={handleGenerateMatrix}
          disabled={loading || selectedIds.size < 2}
          className="mt-4 w-full py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 disabled:cursor-not-allowed rounded font-medium transition"
        >
          {loading ? "Generating..." : `Generate Matrix (${selectedIds.size} selected)`}
        </button>
      </div>

      {error && (
        <div className="p-3 bg-red-900/30 border border-red-700 rounded text-red-300">{error}</div>
      )}

      {matrix && (
        <div className="bg-slate-800 rounded-lg p-4 space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-lg font-semibold">Comparison Matrix</h3>
            <div className="flex gap-2">
              <a
                href={exportMatrixUrl("csv", Array.from(selectedIds))}
                className="px-3 py-1 bg-green-600 hover:bg-green-700 rounded text-sm"
                download="matrix.csv"
              >
                Export CSV
              </a>
              <a
                href={exportMatrixUrl("json", Array.from(selectedIds))}
                className="px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-sm"
                download="matrix.json"
              >
                Export JSON
              </a>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="text-left p-2 font-medium">Field</th>
                  {rows.map((row: any) => (
                    <th key={row.paper.paper_id} className="text-left p-2 font-medium min-w-[200px]">
                      {row.paper.title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {columns.slice(2).map((col: any) => (
                  <tr key={col.key} className="border-b border-slate-700/50">
                    <td className="p-2 font-medium text-slate-300">{col.label}</td>
                    {rows.map((row: any) => {
                      const cell = row.cells[col.key];
                      const evidence = cell?.evidence;
                      return (
                        <td key={row.paper.paper_id} className="p-2 align-top">
                          {evidence?.value ? (
                            <div>
                              <div className="text-xs">{evidence.value}</div>
                              <div className="text-xs text-slate-500 mt-1">
                                [{evidence.evidence_source}]
                              </div>
                            </div>
                          ) : (
                            <span className="text-slate-600">—</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="text-xs text-slate-400 bg-slate-900/50 p-3 rounded">
            <strong>Notice:</strong> {matrix.notice}
          </div>
        </div>
      )}
    </div>
  );
}
