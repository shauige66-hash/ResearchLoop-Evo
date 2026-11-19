import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  advanceGapPipeline,
  getGapPipeline,
  getLLMStatus,
  listGapPipelines,
  startGapPipeline,
} from "../../api/client";
import type {
  GapPipelineRun,
  LLMUsageSummary,
  PipelineDetail,
} from "../../types/gapPipeline";
import {
  LLM_NOT_CONFIGURED,
  PIPELINE_STATUS_LABELS,
  PIPELINE_STATUS_STYLES,
  ROLE_LABELS,
  STAGE_STATUS_STYLES,
} from "../../types/gapPipeline";
import EvidenceCards from "./EvidenceCards";

function Badge({ className, children }: { className: string; children: ReactNode }) {
  return (
    <span className={`px-2 py-0.5 rounded border text-xs font-medium ${className}`}>
      {children}
    </span>
  );
}

function UsageBar({ usage }: { usage: LLMUsageSummary }) {
  const pct = usage.max_calls > 0 ? (usage.calls_used / usage.max_calls) * 100 : 0;
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-2 items-center text-xs">
        <Badge
          className={
            usage.configured
              ? "bg-emerald-900/40 text-emerald-300 border-emerald-700"
              : "bg-slate-700/60 text-slate-300 border-slate-600"
          }
        >
          {usage.configured ? `${usage.provider} / ${usage.model}` : LLM_NOT_CONFIGURED}
        </Badge>
        <span className="text-slate-300">
          LLM 调用 {usage.calls_used} / {usage.max_calls}
        </span>
        <span className="text-slate-500">cache hits {usage.cache_hits}（免费）</span>
        <span className="text-slate-500">failed {usage.failed_calls}</span>
        <span className="text-slate-500">
          tokens {usage.total_tokens === null ? "未返回" : usage.total_tokens}
        </span>
      </div>
      <div className="h-1.5 bg-slate-700 rounded">
        <div
          className={`h-1.5 rounded ${pct >= 100 ? "bg-red-500" : "bg-blue-500"}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <div className="text-xs text-slate-500 flex flex-wrap gap-2">
        {Object.entries(usage.role_usage).map(([role, used]) => (
          <span key={role}>
            {ROLE_LABELS[role] || role}: {used}
            {usage.role_budgets[role] !== undefined ? ` / ${usage.role_budgets[role]}` : ""}
          </span>
        ))}
      </div>
      {!usage.configured && (
        <p className="text-xs text-amber-300 bg-amber-900/20 border border-amber-800 rounded p-2">
          {usage.notice}
        </p>
      )}
    </div>
  );
}

function StageList({ pipeline }: { pipeline: GapPipelineRun }) {
  return (
    <div className="space-y-1">
      {pipeline.stages.map((stage) => (
        <div key={stage.stage_id} className="bg-slate-900/60 rounded p-2 text-xs">
          <div className="flex flex-wrap gap-2 items-center">
            <span className="text-slate-500">{stage.index}</span>
            <strong className="text-slate-200">{stage.title_zh}</strong>
            <span className="text-slate-500">{stage.title}</span>
            <span className={`px-2 py-0.5 rounded ${STAGE_STATUS_STYLES[stage.status]}`}>
              {stage.status}
            </span>
            {stage.attempts > 0 && (
              <span className="text-slate-500">attempts {stage.attempts}</span>
            )}
          </div>
          {stage.notice && <div className="text-slate-400 mt-1">{stage.notice}</div>}
          {stage.error && <div className="text-red-300 mt-1">{stage.error}</div>}
        </div>
      ))}
    </div>
  );
}

export default function PipelinePanel({
  runId,
  topic,
  onChanged,
}: {
  runId: string;
  topic: string;
  onChanged: () => void;
}) {
  const [usage, setUsage] = useState<LLMUsageSummary | null>(null);
  const [pipelines, setPipelines] = useState<GapPipelineRun[]>([]);
  const [detail, setDetail] = useState<PipelineDetail | null>(null);
  const [maxPapers, setMaxPapers] = useState(25);
  const [maxGaps, setMaxGaps] = useState(5);
  const [counterSearch, setCounterSearch] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCards, setShowCards] = useState(false);
  const [showAudit, setShowAudit] = useState(false);

  const refresh = useCallback(async () => {
    const [status, list] = await Promise.all([getLLMStatus(), listGapPipelines()]);
    setUsage(status);
    setPipelines(list.pipelines);
    return list.pipelines;
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [refresh]);

  const loadDetail = useCallback(async (pipelineId: string) => {
    setDetail(await getGapPipeline(pipelineId));
  }, []);

  async function handleStart() {
    if (!runId) {
      setError("先选择一次真实检索 run：pipeline 只分析已检索到的论文。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await startGapPipeline({
        topic: topic || "research gap",
        run_id: runId,
        max_papers: maxPapers,
        max_gaps: maxGaps,
        run_counter_search: counterSearch,
      });
      await refresh();
      await loadDetail(result.pipeline.pipeline_id);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "pipeline start failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleAdvance(pipelineId: string) {
    setBusy(true);
    setError(null);
    try {
      await advanceGapPipeline(pipelineId);
      await refresh();
      await loadDetail(pipelineId);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "pipeline advance failed");
    } finally {
      setBusy(false);
    }
  }

  const pipeline = detail?.pipeline;
  const plan = pipeline?.plan;

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-lg font-semibold">多智能体 Gap Pipeline</h3>
        <span className="text-xs text-slate-500">
          LLM 提出候选，Python 与真实检索负责验证；每个阶段的产物都落盘，可恢复。
        </span>
      </div>

      {usage && <UsageBar usage={usage} />}

      <div className="flex flex-wrap gap-3 items-end text-sm">
        <label>
          <span className="block text-slate-400 mb-1 text-xs">首轮论文上限 (2~30)</span>
          <input
            type="number"
            min={2}
            max={30}
            value={maxPapers}
            onChange={(e) => setMaxPapers(Number(e.target.value))}
            className="bg-slate-900 border border-slate-600 rounded px-2 py-1 w-24"
          />
        </label>
        <label>
          <span className="block text-slate-400 mb-1 text-xs">候选上限 (1~8)</span>
          <input
            type="number"
            min={1}
            max={8}
            value={maxGaps}
            onChange={(e) => setMaxGaps(Number(e.target.value))}
            className="bg-slate-900 border border-slate-600 rounded px-2 py-1 w-24"
          />
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-300">
          <input
            type="checkbox"
            checked={counterSearch}
            onChange={(e) => setCounterSearch(e.target.checked)}
          />
          运行反证检索
        </label>
        <button
          onClick={handleStart}
          disabled={busy || !runId}
          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 rounded text-sm"
        >
          {busy ? "运行中…" : "启动 / Start pipeline"}
        </button>
        {pipelines.length > 0 && (
          <label className="text-xs">
            <span className="block text-slate-400 mb-1">已有 pipeline</span>
            <select
              value={pipeline?.pipeline_id || ""}
              onChange={(e) =>
                loadDetail(e.target.value).catch((err) => setError(String(err)))
              }
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 min-w-[260px]"
            >
              <option value="">— 选择 —</option>
              {pipelines.map((item) => (
                <option key={item.pipeline_id} value={item.pipeline_id}>
                  {item.pipeline_id} · {item.topic} · {item.status}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {error && (
        <div className="p-2 bg-red-900/30 border border-red-700 rounded text-red-300 text-xs">
          {error}
        </div>
      )}

      {pipeline && (
        <div className="space-y-3 border-t border-slate-700 pt-3">
          <div className="flex flex-wrap gap-2 items-center text-xs">
            <Badge className={PIPELINE_STATUS_STYLES[pipeline.status]}>
              {PIPELINE_STATUS_LABELS[pipeline.status]}
            </Badge>
            <span className="text-slate-400">{pipeline.pipeline_id}</span>
            <span className="text-slate-500">
              provider={pipeline.provider} · model={pipeline.model || "—"}
            </span>
            <span className="text-slate-500">
              选中 {pipeline.selected_paper_ids.length} / {pipeline.paper_ids.length} 篇
            </span>
            <span className="text-slate-500">
              calls {pipeline.llm_calls_used}/{pipeline.llm_budget} · cache{" "}
              {pipeline.llm_cache_hits}
            </span>
            <button
              onClick={() => handleAdvance(pipeline.pipeline_id)}
              disabled={busy || pipeline.status === "completed"}
              className="ml-auto px-3 py-1 bg-slate-600 hover:bg-slate-500 disabled:bg-slate-700 rounded"
            >
              继续 / Resume
            </button>
          </div>

          {pipeline.status === "awaiting_budget" && (
            <p className="text-xs text-orange-300 bg-orange-900/20 border border-orange-800 rounded p-2">
              预算已用尽，运行停在此处。已完成的阶段与证据全部保留；提高 RLE_LLM_MAX_CALLS
              后点击 Resume，不会重复付费。
            </p>
          )}

          <StageList pipeline={pipeline} />

          {plan && (
            <div className="text-xs bg-slate-900/60 rounded p-2 space-y-1">
              <strong className="text-slate-300">Research Planner 输出</strong>
              <div className="text-slate-400">
                研究问题: {plan.research_questions.join(" | ") || "—"}
              </div>
              <div className="text-slate-500">
                survey: {plan.review_queries.join("; ")} · foundational:{" "}
                {plan.foundational_queries.join("; ")} · recent: {plan.recent_queries.join("; ")}
              </div>
              <div className="text-slate-500">
                methods: {plan.method_queries.join("; ")} · challenges:{" "}
                {plan.challenge_queries.join("; ")}
              </div>
              <div className="text-slate-500">
                纳入: {plan.inclusion_criteria.join("; ") || "—"} · 排除:{" "}
                {plan.exclusion_criteria.join("; ") || "—"}
              </div>
            </div>
          )}

          {pipeline.synthesis && (
            <div className="text-xs bg-slate-900/60 rounded p-2 space-y-1">
              <strong className="text-slate-300">跨论文综合（Gap Analyst）</strong>
              <div className="text-slate-400">
                已解决: {pipeline.synthesis.already_solved.join("; ") || "—"}
              </div>
              <div className="text-slate-400">
                共同局限: {pipeline.synthesis.shared_limitations.join("; ") || "—"}
              </div>
              <div className="text-slate-400">
                冲突结论: {pipeline.synthesis.conflicting_findings.join("; ") || "—"}
              </div>
              <div className="text-slate-400">
                未覆盖场景: {pipeline.synthesis.uncovered_scenarios.join("; ") || "—"} · 未覆盖指标:{" "}
                {pipeline.synthesis.uncovered_metrics.join("; ") || "—"}
              </div>
            </div>
          )}

          {pipeline.notices.length > 0 && (
            <div className="text-xs text-slate-500 space-y-0.5">
              {pipeline.notices.map((notice, i) => (
                <div key={i}>{notice}</div>
              ))}
            </div>
          )}

          <div className="flex flex-wrap gap-2 text-xs">
            <button
              onClick={() => setShowCards(!showCards)}
              className="px-2 py-1 bg-slate-700 hover:bg-slate-600 rounded"
            >
              {showCards ? "隐藏 Evidence Cards" : `Evidence Cards (${detail?.evidence_cards.length ?? 0})`}
            </button>
            <button
              onClick={() => setShowAudit(!showAudit)}
              className="px-2 py-1 bg-slate-700 hover:bg-slate-600 rounded"
            >
              {showAudit ? "隐藏 LLM 审计" : `LLM 审计 (${detail?.llm_calls.length ?? 0})`}
            </button>
          </div>

          {showCards && <EvidenceCards cards={detail?.evidence_cards || []} />}

          {showAudit && (
            <div className="text-xs bg-slate-900/60 rounded p-2 space-y-1 max-h-72 overflow-auto">
              <p className="text-slate-500">
                只记录 hash 与计量，不保存 prompt 正文，也不保存 API Key。
              </p>
              {(detail?.llm_calls || []).map((call) => (
                <div key={call.request_id} className="border-t border-slate-800 pt-1">
                  <span className="text-slate-300">
                    {ROLE_LABELS[call.agent_role] || call.agent_role}
                  </span>{" "}
                  <span className={call.status === "success" ? "text-emerald-400" : "text-amber-300"}>
                    {call.status}
                  </span>{" "}
                  <span className="text-slate-500">
                    {call.model} · {call.latency_ms ?? "—"}ms · tokens{" "}
                    {call.total_tokens ?? "未返回"} · {call.created_at}
                  </span>
                  <div className="text-slate-600">
                    prompt#{call.prompt_hash.slice(0, 12)} response#
                    {call.response_hash ? call.response_hash.slice(0, 12) : "—"}
                    {call.paper_id ? ` · ${call.paper_id}` : ""}
                  </div>
                  {call.error && <div className="text-red-300">{call.error}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}