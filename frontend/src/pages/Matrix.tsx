import { useCallback, useEffect, useState } from "react";
import {
  exportMatrixUrl,
  generateMatrix,
  listPapers,
  listRuns,
  updatePaperField,
} from "../api/client";
import type {
  MatrixCell,
  MatrixColumn,
  MatrixFilters,
  MatrixResponse,
  Paper,
  RunSummary,
} from "../types/paper";

const MAX_SELECTED = 50;

const EVIDENCE_STYLES: Record<string, string> = {
  abstract: "bg-blue-900/40 text-blue-300 border-blue-700",
  fulltext: "bg-emerald-900/40 text-emerald-300 border-emerald-700",
  manual: "bg-purple-900/40 text-purple-300 border-purple-700",
  model_inference: "bg-amber-900/40 text-amber-300 border-amber-700",
  none: "bg-slate-700/60 text-slate-400 border-slate-600",
};

function CellView({
  cell,
  column,
  onSaved,
}: {
  cell: MatrixCell | undefined;
  column: MatrixColumn;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [showSpan, setShowSpan] = useState(false);
  const [value, setValue] = useState("");
  const [span, setSpan] = useState("");
  const [source, setSource] = useState<"manual" | "fulltext">("manual");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!cell) return <span className="text-slate-600">—</span>;

  if (column.kind !== "extracted") {
    return <span className="text-xs text-slate-300">{cell.text || "—"}</span>;
  }

  const evidence = cell.evidence;
  const grounded = evidence && evidence.evidence_status === "grounded" && evidence.value;

  async function save() {
    if (!cell) return;
    setSaving(true);
    setError(null);
    try {
      await updatePaperField(cell.paper_id, column.key, {
        value: value.trim() || null,
        evidence_source: value.trim() ? source : "none",
        evidence_span: value.trim() ? span.trim() || value.trim() : undefined,
      });
      setEditing(false);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <div className="space-y-1 min-w-[220px]">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          rows={3}
          placeholder="人工修正后的字段值（留空表示标记为 unknown）"
          className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs"
        />
        <textarea
          value={span}
          onChange={(e) => setSpan(e.target.value)}
          rows={2}
          placeholder="原文证据摘录 / verbatim evidence span"
          className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs"
        />
        <select
          value={source}
          onChange={(e) => setSource(e.target.value as "manual" | "fulltext")}
          className="bg-slate-900 border border-slate-600 rounded px-1 py-0.5 text-xs"
        >
          <option value="manual">manual（人工判断）</option>
          <option value="fulltext">fulltext（已读全文）</option>
        </select>
        <div className="flex gap-1">
          <button
            disabled={saving}
            onClick={save}
            className="px-2 py-0.5 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 rounded text-xs"
          >
            {saving ? "保存中…" : "保存"}
          </button>
          <button
            onClick={() => setEditing(false)}
            className="px-2 py-0.5 bg-slate-600 hover:bg-slate-500 rounded text-xs"
          >
            取消
          </button>
        </div>
        {error && <div className="text-xs text-red-300">{error}</div>}
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {grounded ? (
        <>
          <div className="text-xs text-slate-200">{evidence.value}</div>
          <div className="flex flex-wrap items-center gap-1">
            <span
              className={`px-1.5 py-0.5 rounded border text-[10px] ${
                EVIDENCE_STYLES[evidence.evidence_source] || EVIDENCE_STYLES.none
              }`}
            >
              {evidence.evidence_source} · {evidence.extraction_method}
            </span>
            {evidence.evidence_span && (
              <button
                onClick={() => setShowSpan(!showSpan)}
                className="text-[10px] text-blue-400 hover:text-blue-300"
              >
                {showSpan ? "隐藏原文" : "查看原文"}
              </button>
            )}
            <button
              onClick={() => {
                setValue(evidence.value || "");
                setSpan(evidence.evidence_span || "");
                setEditing(true);
              }}
              className="text-[10px] text-slate-400 hover:text-slate-200"
            >
              编辑
            </button>
          </div>
          {showSpan && evidence.evidence_span && (
            <blockquote className="border-l-2 border-blue-700 pl-2 text-[11px] text-slate-400 italic">
              “{evidence.evidence_span}”
            </blockquote>
          )}
        </>
      ) : (
        <div className="flex items-center gap-2">
          <span className="text-slate-600 text-xs">unknown</span>
          <button
            onClick={() => {
              setValue("");
              setSpan("");
              setEditing(true);
            }}
            className="text-[10px] text-slate-500 hover:text-slate-300"
          >
            补充
          </button>
        </div>
      )}
    </div>
  );
}

export default function Matrix() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null);
  const [filters, setFilters] = useState<MatrixFilters>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRuns()
      .then(setRuns)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load runs"));
    listPapers({ page: 1, page_size: 100 })
      .then((result) => setPapers(result.papers))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load papers"));
  }, []);

  const runMatrix = useCallback(
    async (ids: string[], activeFilters: MatrixFilters) => {
      if (ids.length === 0) {
        setError("请至少选择 1 篇论文。");
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const result = await generateMatrix(ids.slice(0, MAX_SELECTED), activeFilters);
        setMatrix(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to generate matrix");
      } finally {
        setLoading(false);
      }
    },
    []
  );

  function toggleSelection(paperId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(paperId)) next.delete(paperId);
      else next.add(paperId);
      return next;
    });
  }

  function selectRun(runId: string) {
    const ids = papers.filter((p) => p.run_id === runId).map((p) => p.paper_id);
    setSelectedIds(new Set(ids.slice(0, MAX_SELECTED)));
    setMatrix(null);
    setFilters({});
  }

  const columns = (matrix?.columns || []).filter(
    (c) => c.key !== "paper_id" && c.key !== "title"
  );
  const rows = matrix?.rows || [];
  const displayedIds = rows.map((r) => r.paper.paper_id);
  const methodClasses = matrix?.available_filters?.method_class || [];
  const yearRange = matrix?.available_filters?.year_range || [];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Literature Matrix / 文献对比矩阵</h2>
        <p className="text-sm text-slate-400 mt-1">
          研究问题、方法分类、智能体架构、记忆与技能机制、数据集、评测指标、结论与局限，全部可追溯到原文证据。
        </p>
      </div>

      {matrix?.extraction_mode && (
        <div className="p-3 bg-amber-900/20 border border-amber-700 rounded text-sm text-amber-200">
          <strong>Heuristic Mode</strong> — extraction_mode={matrix.extraction_mode}。
          抽取字段仅来自检索到的摘要，未阅读全文；“Method Class (system)” 是系统标签，不是作者主张。
        </div>
      )}

      <div className="bg-slate-800 rounded-lg p-4 space-y-3">
        <div className="flex flex-wrap gap-3 items-end">
          <label className="text-sm">
            <span className="block text-slate-400 mb-1">按检索批次选择</span>
            <select
              defaultValue=""
              onChange={(e) => e.target.value && selectRun(e.target.value)}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 min-w-[260px]"
            >
              <option value="">— 选择 run —</option>
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.topic} ({run.paper_count})
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={() => setSelectedIds(new Set(papers.slice(0, MAX_SELECTED).map((p) => p.paper_id)))}
            className="px-3 py-1 bg-slate-600 hover:bg-slate-500 rounded text-sm"
          >
            全选（前 {MAX_SELECTED} 篇）
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="px-3 py-1 bg-slate-600 hover:bg-slate-500 rounded text-sm"
          >
            清空
          </button>
          <span className="text-sm text-slate-400">
            已选 {selectedIds.size} / 上限 {MAX_SELECTED}
          </span>
        </div>

        <div className="space-y-2 max-h-56 overflow-auto border border-slate-700 rounded p-2">
          {papers.length === 0 && (
            <div className="text-sm text-slate-500 p-2">
              文献库为空。请先在 Literature Discovery 执行一次真实检索。
            </div>
          )}
          {papers.map((paper) => (
            <label
              key={paper.paper_id}
              className="flex items-center gap-3 p-1.5 hover:bg-slate-700 rounded cursor-pointer"
            >
              <input
                type="checkbox"
                checked={selectedIds.has(paper.paper_id)}
                onChange={() => toggleSelection(paper.paper_id)}
              />
              <div className="flex-1 min-w-0">
                <div className="text-sm truncate">{paper.title}</div>
                <div className="text-xs text-slate-400">
                  {paper.authors.slice(0, 2).join(", ")} · {paper.publication_year || "n.d."} ·{" "}
                  {paper.source} · {paper.method_class || "unclassified"}
                </div>
              </div>
            </label>
          ))}
        </div>

        <div className="flex flex-wrap gap-3 items-end text-sm border-t border-slate-700 pt-3">
          <label>
            <span className="block text-slate-400 mb-1">方法分类</span>
            <select
              value={filters.method_class || ""}
              onChange={(e) => setFilters({ ...filters, method_class: e.target.value || undefined })}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 min-w-[200px]"
            >
              <option value="">全部</option>
              {methodClasses.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="block text-slate-400 mb-1">数据集包含</span>
            <input
              value={filters.dataset || ""}
              onChange={(e) => setFilters({ ...filters, dataset: e.target.value || undefined })}
              placeholder="e.g. LoCoMo"
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 w-40"
            />
          </label>
          <label>
            <span className="block text-slate-400 mb-1">指标包含</span>
            <input
              value={filters.metric || ""}
              onChange={(e) => setFilters({ ...filters, metric: e.target.value || undefined })}
              placeholder="e.g. F1"
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 w-32"
            />
          </label>
          <label>
            <span className="block text-slate-400 mb-1">年份从</span>
            <input
              type="number"
              value={filters.year_from ?? ""}
              onChange={(e) =>
                setFilters({ ...filters, year_from: e.target.value ? Number(e.target.value) : undefined })
              }
              placeholder={yearRange[0] != null ? String(yearRange[0]) : "2023"}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 w-24"
            />
          </label>
          <label>
            <span className="block text-slate-400 mb-1">到</span>
            <input
              type="number"
              value={filters.year_to ?? ""}
              onChange={(e) =>
                setFilters({ ...filters, year_to: e.target.value ? Number(e.target.value) : undefined })
              }
              placeholder={yearRange[1] != null ? String(yearRange[1]) : "2026"}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 w-24"
            />
          </label>
          <button
            onClick={() => runMatrix(Array.from(selectedIds), filters)}
            disabled={loading || selectedIds.size === 0}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 disabled:cursor-not-allowed rounded font-medium"
          >
            {loading ? "生成中…" : `生成矩阵 (${selectedIds.size})`}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 bg-red-900/30 border border-red-700 rounded text-red-300 text-sm">{error}</div>
      )}

      {matrix && (
        <div className="bg-slate-800 rounded-lg p-4 space-y-4">
          <div className="flex flex-wrap justify-between items-center gap-2">
            <h3 className="text-lg font-semibold">
              对比矩阵 · {rows.length} 篇 × {columns.length} 个字段
            </h3>
            <div className="flex gap-2">
              <a
                href={exportMatrixUrl("csv", displayedIds)}
                className="px-3 py-1 bg-green-600 hover:bg-green-700 rounded text-sm"
                download="matrix.csv"
              >
                Export CSV
              </a>
              <a
                href={exportMatrixUrl("json", displayedIds)}
                className="px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-sm"
                download="matrix.json"
              >
                Export JSON
              </a>
            </div>
          </div>

          {Object.keys(matrix.filters_applied || {}).length > 0 && (
            <div className="text-xs text-slate-400">
              已应用筛选: {JSON.stringify(matrix.filters_applied)}
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="text-left p-2 font-medium sticky left-0 bg-slate-800 min-w-[140px]">
                    Field
                  </th>
                  {rows.map((row) => (
                    <th key={row.paper.paper_id} className="text-left p-2 font-medium min-w-[240px] align-top">
                      <a
                        href={row.paper.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-blue-400 hover:underline"
                      >
                        {row.paper.title}
                      </a>
                      <div className="text-xs text-slate-500 font-normal">
                        {row.paper.publication_year || "n.d."} · {row.paper.source}
                        {row.paper.doi ? ` · doi:${row.paper.doi}` : ""}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {columns.map((col) => (
                  <tr key={col.key} className="border-b border-slate-700/50 align-top">
                    <td className="p-2 font-medium text-slate-300 sticky left-0 bg-slate-800">
                      {col.label}
                      {col.kind === "system_label" && (
                        <span className="block text-[10px] text-amber-400 font-normal">system label</span>
                      )}
                    </td>
                    {rows.map((row) => (
                      <td key={row.paper.paper_id} className="p-2">
                        <CellView
                          cell={row.cells[col.key]}
                          column={col}
                          onSaved={() => runMatrix(Array.from(selectedIds), filters)}
                        />
                      </td>
                    ))}
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