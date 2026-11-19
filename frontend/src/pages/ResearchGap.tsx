import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  discoverGaps,
  getGap,
  listGaps,
  listRuns,
  rerunCounterSearch,
  reviewGap,
} from "../api/client";
import type {
  ConfidenceLabel,
  GapReview,
  GapStatus,
  GapType,
  ResearchGap,
} from "../types/gap";
import {
  COUNTER_STATUS_LABELS,
  GAP_STATUS_LABELS,
  GAP_TYPE_LABELS,
  RISK_STYLES,
} from "../types/gap";
import type { RiskLabel } from "../types/gap";
import type { RunSummary } from "../types/paper";
import EvidenceChain from "../components/gap/EvidenceChain";
import PipelinePanel from "../components/gap/PipelinePanel";

const CONFIDENCE_STYLES: Record<ConfidenceLabel, string> = {
  High: "bg-emerald-900/50 text-emerald-300 border-emerald-700",
  Medium: "bg-amber-900/40 text-amber-300 border-amber-700",
  Low: "bg-slate-700/60 text-slate-300 border-slate-600",
};

const STATUS_STYLES: Record<GapStatus, string> = {
  needs_human_review: "bg-blue-900/40 text-blue-300 border-blue-700",
  accepted: "bg-emerald-900/50 text-emerald-300 border-emerald-700",
  rejected: "bg-red-900/40 text-red-300 border-red-700",
  edited: "bg-purple-900/40 text-purple-300 border-purple-700",
};

function Badge({ className, children }: { className: string; children: ReactNode }) {
  return (
    <span className={`px-2 py-0.5 rounded border text-xs font-medium ${className}`}>
      {children}
    </span>
  );
}

function PaperLink({
  title,
  url,
  doi,
}: {
  title: string;
  url: string;
  doi?: string | null;
}) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="text-blue-400 hover:text-blue-300 hover:underline"
    >
      {title}
      {doi && <span className="text-slate-500 text-xs ml-1">doi:{doi}</span>}
    </a>
  );
}

function GapCard({
  gap,
  busy,
  onReview,
  onCounterSearch,
}: {
  gap: ResearchGap;
  busy: boolean;
  onReview: (
    gapId: string,
    status: GapStatus,
    note: string,
    edits?: { title: string; description: string; unresolved_question: string }
  ) => void;
  onCounterSearch: (gapId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState(gap.human_note || "");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({
    title: gap.title,
    description: gap.description,
    unresolved_question: gap.unresolved_question,
  });
  const [reviews, setReviews] = useState<GapReview[]>([]);

  useEffect(() => {
    setNote(gap.human_note || "");
    setDraft({
      title: gap.title,
      description: gap.description,
      unresolved_question: gap.unresolved_question,
    });
  }, [gap]);

  async function loadReviews() {
    try {
      const detail = await getGap(gap.gap_id);
      setReviews(detail.reviews);
    } catch {
      setReviews([]);
    }
  }

  const scope = gap.counter_search_scope || {};

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge className="bg-slate-700 text-slate-200 border-slate-600">
          {GAP_TYPE_LABELS[gap.gap_type]}
        </Badge>
        <Badge className={CONFIDENCE_STYLES[gap.confidence_label]}>
          {gap.confidence_label} confidence
        </Badge>
        <Badge className={STATUS_STYLES[gap.status]}>{GAP_STATUS_LABELS[gap.status]}</Badge>
        <Badge
          className={
            gap.counter_status === "COUNTER_SEARCH_FAILED"
              ? "bg-red-900/40 text-red-300 border-red-700"
              : gap.counter_status === "COUNTER_EVIDENCE_FOUND"
                ? "bg-amber-900/40 text-amber-300 border-amber-700"
                : "bg-slate-700/60 text-slate-300 border-slate-600"
          }
        >
          {COUNTER_STATUS_LABELS[gap.counter_status] || gap.counter_status || "NOT_RUN"}
        </Badge>
        {gap.novelty_risk && (
          <Badge className={RISK_STYLES[(gap.novelty_risk as RiskLabel) || "MEDIUM"]}>
            novelty_risk: {gap.novelty_risk}
          </Badge>
        )}
        {gap.discovery_mode === "llm_pipeline" && (
          <Badge className="bg-purple-900/40 text-purple-300 border-purple-700">
            LLM 提出 · Python 验证
          </Badge>
        )}
        {gap.experimentability.testable_minimally ? (
          <Badge className="bg-emerald-900/40 text-emerald-300 border-emerald-700">
            可最小实验验证
          </Badge>
        ) : (
          <Badge className="bg-slate-700/60 text-slate-400 border-slate-600">
            超出最小实验预算
          </Badge>
        )}
        <span className="ml-auto text-xs text-slate-500">{gap.gap_id}</span>
      </div>

      <h3 className="text-lg font-semibold">{gap.title}</h3>
      <p className="text-sm text-slate-300">{gap.description}</p>

      <div className="text-xs text-slate-400 bg-slate-900/50 rounded p-2 space-y-1">
        <div>
          <strong className="text-slate-300">置信度依据 / rationale:</strong>{" "}
          {gap.confidence_rationale}
        </div>
        <div>
          <strong className="text-slate-300">检测键 / detection key:</strong>{" "}
          <code className="text-amber-300">{gap.detection_key || "—"}</code>
        </div>
        <div>
          <strong className="text-slate-300">待解问题:</strong> {gap.unresolved_question}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs">
        <div className="bg-slate-900/50 rounded p-2">
          <div className="text-slate-400">支持论文 / supporting</div>
          <div className="text-lg text-slate-100">{gap.supporting_papers.length}</div>
          <div className="text-slate-500">{gap.supporting_evidence.length} 条原文证据</div>
        </div>
        <div className="bg-slate-900/50 rounded p-2">
          <div className="text-slate-400">反证 / counter-evidence</div>
          <div className="text-lg text-slate-100">{gap.counter_evidence.length}</div>
          <div className="text-slate-500">
            检索 {scope.papers_retrieved ?? 0} 篇，{scope.rejected_as_not_addressing_claim ?? 0} 篇因未针对该论点被排除
          </div>
        </div>
        <div className="bg-slate-900/50 rounded p-2">
          <div className="text-slate-400">反证检索开销</div>
          <div className="text-lg text-slate-100">{scope.requests_made ?? 0} requests</div>
          <div className="text-slate-500">
            {(scope.sources || []).join(" + ")} · top_k={scope.top_k ?? "—"} · cache {scope.cache_hits ?? 0}
          </div>
        </div>
      </div>

      <button
        onClick={() => {
          const next = !open;
          setOpen(next);
          if (next) loadReviews();
        }}
        className="text-sm text-blue-400 hover:text-blue-300"
      >
        {open ? "收起证据链 / Hide evidence chain" : "展开完整证据链 / Show full evidence chain"}
      </button>

      {open && (
        <div className="space-y-4 border-t border-slate-700 pt-3">
          <EvidenceChain gap={gap} />

          <section>
            <h4 className="text-sm font-semibold mb-2">支持证据（原文摘录）</h4>
            <div className="space-y-2 max-h-64 overflow-auto">
              {gap.supporting_evidence.map((ev, i) => (
                <div key={`${ev.paper_id}-${ev.field}-${i}`} className="bg-slate-900/60 rounded p-2 text-xs">
                  <div className="flex flex-wrap gap-2 items-center mb-1">
                    <PaperLink title={ev.title} url={ev.source_url} doi={ev.doi} />
                    <span className="text-slate-500">
                      field={ev.field} · {ev.extraction_method}
                    </span>
                  </div>
                  <blockquote className="border-l-2 border-blue-700 pl-2 text-slate-300 italic">
                    “{ev.evidence_span}”
                  </blockquote>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h4 className="text-sm font-semibold mb-2">
              反证论文（已解决或已涉及该问题的真实检索结果）
            </h4>
            {gap.counter_evidence.length === 0 ? (
              <p className="text-xs text-amber-300 bg-amber-900/20 border border-amber-800 rounded p-2">
                {gap.scope_notice}
              </p>
            ) : (
              <div className="space-y-2 max-h-72 overflow-auto">
                {gap.counter_evidence.map((c) => (
                  <div key={c.paper_id} className="bg-slate-900/60 rounded p-2 text-xs">
                    <div className="flex flex-wrap gap-2 items-center mb-1">
                      <PaperLink title={c.title} url={c.source_url} doi={c.doi} />
                      <span className="text-slate-500">
                        {c.source} · {c.publication_year ?? "n.d."}
                      </span>
                      {c.matched_cue && (
                        <Badge className="bg-amber-900/40 text-amber-300 border-amber-700">
                          matched: {c.matched_cue}
                        </Badge>
                      )}
                    </div>
                    {c.evidence_span && (
                      <blockquote className="border-l-2 border-amber-700 pl-2 text-slate-300 italic mb-1">
                        “{c.evidence_span}”
                      </blockquote>
                    )}
                    <div className="text-slate-500">{c.why_relevant}</div>
                  </div>
                ))}
              </div>
            )}
            <div className="text-xs text-slate-500 mt-2">
              query: <code className="text-slate-400">{gap.counter_search_queries.join(" | ")}</code>
            </div>
            {gap.counter_search_errors.length > 0 && (
              <div className="mt-2 text-xs text-red-300 bg-red-900/20 border border-red-800 rounded p-2 space-y-1">
                <strong>反证检索真实错误 / counter-search errors:</strong>
                {gap.counter_search_errors.map((e, i) => (
                  <div key={i}>
                    {e.source} · HTTP {e.status ?? "n/a"} · {e.detail}
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <h4 className="text-sm font-semibold mb-2">最接近的相关工作</h4>
            <div className="space-y-1 text-xs">
              {gap.closest_related_work.map((w) => (
                <div key={w.paper_id} className="bg-slate-900/60 rounded p-2">
                  <PaperLink title={w.title} url={w.source_url} doi={w.doi} />
                  <div className="text-slate-500">{w.why_closest}</div>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h4 className="text-sm font-semibold mb-2">可行性判断 / experimentability</h4>
            <div className="text-xs bg-slate-900/60 rounded p-2 space-y-1">
              <div>{gap.experimentability.proposed_experiment}</div>
              {gap.experimentability.required_inputs.length > 0 && (
                <div className="text-slate-400">
                  需要输入: {gap.experimentability.required_inputs.join("; ")}
                </div>
              )}
              {gap.experimentability.blocking_reason && (
                <div className="text-amber-300">阻塞原因: {gap.experimentability.blocking_reason}</div>
              )}
            </div>
          </section>

          {reviews.length > 0 && (
            <section>
              <h4 className="text-sm font-semibold mb-2">人工评审历史</h4>
              <div className="space-y-1 text-xs text-slate-400">
                {reviews.map((r) => (
                  <div key={r.id}>
                    {r.reviewed_at} · {GAP_STATUS_LABELS[r.status]}
                    {r.human_note ? ` · ${r.human_note}` : ""}
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      )}

      <div className="border-t border-slate-700 pt-3 space-y-2">
        {editing ? (
          <div className="space-y-2">
            <input
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm"
            />
            <textarea
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              rows={3}
              className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm"
            />
            <input
              value={draft.unresolved_question}
              onChange={(e) => setDraft({ ...draft, unresolved_question: e.target.value })}
              className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm"
            />
          </div>
        ) : null}
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          placeholder="人工评审意见 / reviewer note"
          className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs"
        />
        <div className="flex flex-wrap gap-2">
          <button
            disabled={busy}
            onClick={() => onReview(gap.gap_id, "accepted", note)}
            className="px-3 py-1 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-600 rounded text-sm"
          >
            接受 / Accept
          </button>
          <button
            disabled={busy}
            onClick={() => onReview(gap.gap_id, "rejected", note)}
            className="px-3 py-1 bg-red-600 hover:bg-red-700 disabled:bg-slate-600 rounded text-sm"
          >
            拒绝 / Reject
          </button>
          {editing ? (
            <>
              <button
                disabled={busy}
                onClick={() => {
                  onReview(gap.gap_id, "edited", note, draft);
                  setEditing(false);
                }}
                className="px-3 py-1 bg-purple-600 hover:bg-purple-700 disabled:bg-slate-600 rounded text-sm"
              >
                保存编辑 / Save edit
              </button>
              <button
                onClick={() => setEditing(false)}
                className="px-3 py-1 bg-slate-600 hover:bg-slate-500 rounded text-sm"
              >
                取消
              </button>
            </>
          ) : (
            <button
              disabled={busy}
              onClick={() => setEditing(true)}
              className="px-3 py-1 bg-slate-600 hover:bg-slate-500 disabled:bg-slate-700 rounded text-sm"
            >
              编辑 / Edit
            </button>
          )}
          <button
            disabled={busy}
            onClick={() => onCounterSearch(gap.gap_id)}
            className="px-3 py-1 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 rounded text-sm"
          >
            重跑反证检索 / Re-run counter-search
          </button>
        </div>
        <p className="text-xs text-slate-500">
          只有人工接受（accepted）的空白才允许进入实验设计；系统不会自动晋升。
        </p>
      </div>
    </div>
  );
}

export default function ResearchGap() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runId, setRunId] = useState("");
  const [gaps, setGaps] = useState<ResearchGap[]>([]);
  const [notice, setNotice] = useState("");
  const [mode, setMode] = useState("");
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [withCounterSearch, setWithCounterSearch] = useState(true);

  useEffect(() => {
    listRuns()
      .then((result) => {
        setRuns(result);
        if (result.length > 0) setRunId(result[0].id);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load runs"));
  }, []);

  const reload = useCallback(async () => {
    const result = await listGaps({
      run_id: runId || undefined,
      status: statusFilter || undefined,
      gap_type: typeFilter || undefined,
    });
    setGaps(result.gaps);
    setNotice(result.notice);
    setMode(result.extraction_mode);
  }, [runId, statusFilter, typeFilter]);

  useEffect(() => {
    reload().catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load gaps")
    );
  }, [reload]);

  async function handleDiscover() {
    if (!runId) {
      setError("先在 Literature Discovery 完成一次真实检索，再选择该 run。");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await discoverGaps({
        run_id: runId,
        run_counter_search: withCounterSearch,
        counter_top_k: 10,
      });
      setMode(result.extraction_mode);
      setNotice(result.notice);
      if (result.total === 0) {
        setError("本次比较未发现满足证据门槛的候选空白（需要至少两篇论文的可比证据）。");
      }
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gap discovery failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleReview(
    gapId: string,
    status: GapStatus,
    note: string,
    edits?: { title: string; description: string; unresolved_question: string }
  ) {
    setBusyId(gapId);
    setError(null);
    try {
      await reviewGap(gapId, { status, human_note: note, ...(edits || {}) });
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Review failed");
    } finally {
      setBusyId(null);
    }
  }

  async function handleCounterSearch(gapId: string) {
    setBusyId(gapId);
    setError(null);
    try {
      await rerunCounterSearch(gapId, 10);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Counter-search failed");
    } finally {
      setBusyId(null);
    }
  }

  const accepted = gaps.filter((g) => g.status === "accepted").length;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Research Gap / 研究空白</h2>
        <p className="text-sm text-slate-400 mt-1">
          比较多篇论文的方法与实验范围，提出候选空白，并自动检索反证。所有候选默认待人工确认。
        </p>
      </div>

      {mode && (
        <div className="p-3 bg-amber-900/20 border border-amber-700 rounded text-sm text-amber-200">
          <strong>Heuristic Mode</strong> — Paper 字段抽取仍为规则启发式（extraction_mode={mode}），
          只使用检索到的摘要，未阅读全文。空白检测模式见每条候选的 discovery_mode；
          LLM 是否配置、调用预算与审计记录见下方 Pipeline 面板。
        </div>
      )}

      <div className="bg-slate-800 rounded-lg p-4 space-y-3">
        <div className="flex flex-wrap gap-3 items-end">
          <label className="text-sm">
            <span className="block text-slate-400 mb-1">检索批次 / run</span>
            <select
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 min-w-[280px]"
            >
              <option value="">— 选择一次真实检索 —</option>
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.topic} ({run.paper_count} papers)
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={withCounterSearch}
              onChange={(e) => setWithCounterSearch(e.target.checked)}
            />
            自动反证检索（OpenAlex + Crossref + arXiv）
          </label>
          <button
            onClick={handleDiscover}
            disabled={loading || !runId}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 disabled:cursor-not-allowed rounded font-medium"
          >
            {loading ? "正在检索反证…" : "发现候选空白 / Discover"}
          </button>
          <button
            onClick={() => reload().catch((err) => setError(String(err)))}
            className="px-3 py-2 bg-slate-600 hover:bg-slate-500 rounded text-sm"
          >
            刷新
          </button>
        </div>

        <div className="flex flex-wrap gap-3 items-end text-sm">
          <label>
            <span className="block text-slate-400 mb-1">状态</span>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1"
            >
              <option value="">全部</option>
              {(Object.keys(GAP_STATUS_LABELS) as GapStatus[]).map((s) => (
                <option key={s} value={s}>
                  {GAP_STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="block text-slate-400 mb-1">类型</span>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1"
            >
              <option value="">全部</option>
              {(Object.keys(GAP_TYPE_LABELS) as GapType[]).map((t) => (
                <option key={t} value={t}>
                  {GAP_TYPE_LABELS[t]}
                </option>
              ))}
            </select>
          </label>
          <div className="text-slate-400">
            {gaps.length} 条候选 · {accepted} 条已接受
          </div>
        </div>
      </div>

      <PipelinePanel
        runId={runId}
        topic={runs.find((run) => run.id === runId)?.topic || ""}
        onChanged={() => {
          reload().catch((err) => setError(String(err)));
        }}
      />

      {error && (
        <div className="p-3 bg-red-900/30 border border-red-700 rounded text-red-300 text-sm">
          {error}
        </div>
      )}

      {notice && (
        <div className="p-3 bg-slate-800/60 border border-slate-700 rounded text-xs text-slate-400">
          {notice}
        </div>
      )}

      {gaps.length === 0 && !loading && (
        <div className="bg-slate-800 rounded-lg p-6 text-center text-slate-400 text-sm">
          暂无候选空白。请先在 Literature Discovery 执行一次真实检索（至少 2 篇论文），再回到本页点击 Discover。
        </div>
      )}

      <div className="space-y-4">
        {gaps.map((gap) => (
          <GapCard
            key={gap.gap_id}
            gap={gap}
            busy={busyId === gap.gap_id}
            onReview={handleReview}
            onCounterSearch={handleCounterSearch}
          />
        ))}
      </div>
    </div>
  );
}