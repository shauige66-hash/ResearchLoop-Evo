import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { StepId, WorkflowStep } from "../../types/workflow";
import { Badge, Stat, coverageText, SPLIT_STYLES } from "../experiment/common";
import { FAILURE_LABELS } from "../../types/evolution";

function Json({ value }: { value: unknown }) {
  return (
    <pre className="mt-1 text-xs text-slate-300 overflow-auto max-h-64">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="text-xs text-slate-300">
      <span className="text-slate-500">{label}：</span>
      {children}
    </div>
  );
}

function Bar({ value, max, tone }: { value: number; max: number; tone: string }) {
  const width = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="h-2 bg-slate-700 rounded overflow-hidden">
      <div className={`h-2 ${tone}`} style={{ width: `${width}%` }} />
    </div>
  );
}

function RunTable({ step }: { step: WorkflowStep }) {
  const runs = step.outputs.runs ?? [];
  if (runs.length === 0) return <p className="text-xs text-slate-400">没有执行记录。</p>;
  return (
    <table className="w-full text-xs text-slate-300">
      <thead className="text-slate-500">
        <tr>
          <th className="text-left py-1">case</th>
          <th className="text-left">split</th>
          <th className="text-left">arm</th>
          <th className="text-left">真实 query</th>
          <th className="text-right">请求</th>
          <th className="text-right">缓存</th>
          <th className="text-right">论文</th>
          <th className="text-right">ms</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r) => (
          <tr key={r.run_id} className="border-t border-slate-700">
            <td className="py-1 font-mono">{r.case_id}</td>
            <td><Badge className={SPLIT_STYLES[r.split]}>{r.split}</Badge></td>
            <td>{r.arm}</td>
            <td className="text-slate-400">{r.queries_used.join(" | ")}</td>
            <td className="text-right">{r.api_request_count}</td>
            <td className="text-right">{r.cache_hits}</td>
            <td className="text-right">{r.unique_paper_count}</td>
            <td className="text-right">{r.execution_time_ms}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function GateView({ gate }: { gate: { allowed: boolean; reasons: string[] } }) {
  return (
    <div className="space-y-1">
      <Badge className={gate.allowed ? "bg-green-900/50 text-green-300" : "bg-red-900/50 text-red-300"}>
        {gate.allowed ? "门禁全部通过" : `门禁未通过（${gate.reasons.length} 条）`}
      </Badge>
      {!gate.allowed && (
        <ul className="text-xs text-red-200 space-y-0.5">
          {gate.reasons.map((r) => <li key={r}>· {r}</li>)}
        </ul>
      )}
    </div>
  );
}

function ComparisonTable({ step }: { step: WorkflowStep }) {
  const comparisons = step.outputs.comparisons ?? [];
  if (comparisons.length === 0) return null;
  const maxRequests = Math.max(
    1,
    ...comparisons.flatMap((c) => [
      c.baseline?.api_request_count ?? 0,
      c.candidate?.api_request_count ?? 0,
    ]),
  );
  return (
    <div className="space-y-2">
      {comparisons.map((c) => (
        <div key={c.case_id} className="bg-slate-900/60 rounded p-2 space-y-1">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-mono text-slate-300">{c.case_id}</span>
            <Badge className={SPLIT_STYLES[c.split]}>{c.split}</Badge>
            <span className="text-slate-400">
              覆盖率 {coverageText(c.baseline?.evaluation?.coverage_at_k)} →{" "}
              {coverageText(c.candidate?.evaluation?.coverage_at_k)}
            </span>
            <span className="text-slate-400">
              请求比 {c.request_ratio === null ? "—" : `${c.request_ratio.toFixed(2)}×`}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="text-xs text-slate-500">baseline 请求</div>
              <Bar value={c.baseline?.api_request_count ?? 0} max={maxRequests} tone="bg-slate-400" />
            </div>
            <div>
              <div className="text-xs text-slate-500">candidate 请求</div>
              <Bar value={c.candidate?.api_request_count ?? 0} max={maxRequests} tone="bg-blue-400" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function Detail({ step }: { step: WorkflowStep }) {
  const o = step.outputs;
  switch (step.step_id as StepId) {
    case "search_planning":
      return (
        <div className="space-y-1">
          <Row label="关键词">
            {(o.keywords_used ?? []).map((k) => (
              <code key={k.keyword} className="mr-2">{k.keyword}（{k.origin}）</code>
            ))}
          </Row>
          <Row label="检索前请求上限估计">{o.planned_api_requests}</Row>
        </div>
      );
    case "literature_discovery":
      return (
        <div className="space-y-1">
          <div className="grid grid-cols-4 gap-2">
            <Stat label="保留论文" value={o.paper_count ?? 0} />
            <Stat label="真实请求" value={o.requests_made ?? 0} />
            <Stat label="缓存命中" value={o.cache_hits ?? 0} />
            <Stat label="耗时 ms" value={o.duration_ms ?? 0} />
          </div>
          {(o.sources_failed ?? []).length > 0 && (
            <Row label="失败来源">{(o.sources_failed ?? []).join("、")}</Row>
          )}
          <Link className="text-xs text-blue-400 underline" to="/library">
            在 Literature Library 查看这 {o.paper_count ?? 0} 篇 →
          </Link>
        </div>
      );
    case "paper_extraction":
      return (
        <div className="space-y-2">
          <div className="grid grid-cols-3 gap-2">
            <Stat label="抽取模式" value={o.extraction_mode ?? "—"} hint="未阅读全文" />
            <Stat label="有证据单元格" value={o.grounded_cells ?? 0} />
            <Stat label="unknown 单元格" value={o.unknown_cells ?? 0} />
          </div>
          <table className="w-full text-xs text-slate-300">
            <thead className="text-slate-500">
              <tr>
                <th className="text-left py-1">字段</th>
                <th className="text-right">grounded</th>
                <th className="text-right">unknown</th>
                <th className="text-left pl-2">证据原文示例</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(o.per_field ?? {}).map(([field, audit]) => (
                <tr key={field} className="border-t border-slate-700">
                  <td className="py-1 font-mono">{field}</td>
                  <td className="text-right text-green-300">{audit.grounded}</td>
                  <td className="text-right text-slate-500">{audit.unknown}</td>
                  <td className="pl-2 text-slate-400">{audit.example_span ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "literature_matrix":
      return (
        <div className="space-y-1">
          <Row label="行数">{o.row_count}</Row>
          <Row label="方法分布">
            {Object.entries(o.method_distribution ?? {}).map(([label, count]) => (
              <Badge key={label} className="bg-slate-700 text-slate-200 mr-1">{label} × {count}</Badge>
            ))}
          </Row>
          <Row label="年份范围">{(o.year_range ?? []).join(" – ")}</Row>
          <Link className="text-xs text-blue-400 underline" to="/matrix">打开完整矩阵与导出 →</Link>
        </div>
      );
    case "gap_discovery":
      return (
        <div className="space-y-1">
          {(o.gaps ?? []).map((g) => (
            <div key={g.gap_id} className="bg-slate-900/60 rounded p-2 text-xs space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <Badge className="bg-slate-700 text-slate-200">{g.gap_type}</Badge>
                <Badge className="bg-amber-900/50 text-amber-300">{g.confidence_label}</Badge>
                <span className="text-slate-200">{g.title}</span>
              </div>
              <div className="text-slate-500">
                支撑论文 {g.supporting_papers.length} 篇 · 状态 {g.status} ·{" "}
                <span className="font-mono">{g.gap_id}</span>
              </div>
            </div>
          ))}
          {(o.gaps ?? []).length === 0 && (
            <p className="text-xs text-slate-400">没有生成候选空白。</p>
          )}
        </div>
      );
    case "counter_evidence_search":
      return (
        <div className="space-y-1">
          {(o.per_gap ?? []).map((g) => (
            <div key={g.gap_id} className="bg-slate-900/60 rounded p-2 text-xs space-y-1">
              <div className="text-slate-300">query：<code>{g.query}</code></div>
              <div className="text-slate-400">
                反证 {g.counter_count} 篇 · 检索 {g.scope.papers_retrieved ?? 0} 篇 ·
                请求 {g.scope.requests_made ?? 0} · 置信度 {g.confidence_label}
              </div>
              <div className="text-slate-500">{g.confidence_rationale}</div>
            </div>
          ))}
        </div>
      );
    case "hypothesis":
      return (
        <div className="space-y-1 text-xs text-slate-300">
          <div>{o.hypothesis}</div>
          <Badge className="bg-amber-900/50 text-amber-300">{o.hypothesis_status}</Badge>
        </div>
      );
    case "experiment_spec":
      return (
        <div className="space-y-2">
          <div className="grid grid-cols-3 gap-2">
            <Stat label="Spec" value={<span className="font-mono text-xs">{o.spec_id}</span>} />
            <Stat label="请求上限" value={o.max_api_requests ?? 0} />
            <Stat label="候选版本" value={`v${o.candidate_version_number ?? "—"}`} />
          </div>
          <table className="w-full text-xs text-slate-300">
            <thead className="text-slate-500">
              <tr>
                <th className="text-left py-1">case</th>
                <th className="text-left">split</th>
                <th className="text-right">参考 DOI</th>
                <th className="text-right">已确认</th>
                <th className="text-left pl-2">状态</th>
              </tr>
            </thead>
            <tbody>
              {(o.cases ?? []).map((c) => (
                <tr key={c.case_id} className="border-t border-slate-700">
                  <td className="py-1 font-mono">{c.case_id}</td>
                  <td><Badge className={SPLIT_STYLES[c.split]}>{c.split}</Badge></td>
                  <td className="text-right">{c.reference_count}</td>
                  <td className="text-right">{c.confirmed_count}</td>
                  <td className="pl-2 text-amber-300">{c.reference_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Row label="种子变异">{o.mutation_description}</Row>
          {o.seed && (
            <Row label="规划 query">
              {o.seed.planned_queries.map((q) => <code key={q} className="mr-2">{q}</code>)}
            </Row>
          )}
          {(o.verification_errors ?? []).length > 0 && (
            <div className="text-xs text-red-300">
              DOI 核验失败：{o.verification_errors?.map((e) => `${e.doi}（${e.detail}）`).join("；")}
            </div>
          )}
          <p className="text-xs text-amber-200">{o.reference_provenance}</p>
        </div>
      );
    case "baseline_execution":
    case "candidate_execution":
      return (
        <div className="space-y-1">
          <RunTable step={step} />
          {(o.skipped_splits ?? []).length > 0 && (
            <Row label="跳过的 split">{(o.skipped_splits ?? []).join("；")}</Row>
          )}
        </div>
      );
    case "independent_evaluation":
      return (
        <div className="space-y-2">
          <table className="w-full text-xs text-slate-300">
            <thead className="text-slate-500">
              <tr>
                <th className="text-left py-1">run</th>
                <th className="text-left">arm</th>
                <th className="text-left">状态</th>
                <th className="text-right">Coverage@K</th>
                <th className="text-right">参考集</th>
                <th className="text-right">论文</th>
              </tr>
            </thead>
            <tbody>
              {(o.evaluations ?? []).map((e) => (
                <tr key={e.run_id} className="border-t border-slate-700">
                  <td className="py-1 font-mono">{e.run_id}</td>
                  <td>{e.arm}</td>
                  <td className={e.status === "computed" ? "text-green-300" : "text-amber-300"}>
                    {e.status}
                  </td>
                  <td className="text-right">{coverageText(e.coverage_at_k)}</td>
                  <td className="text-right">{e.reference_set_size}</td>
                  <td className="text-right">{e.unique_paper_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ComparisonTable step={step} />
          {o.promotion_gate && <GateView gate={o.promotion_gate} />}
        </div>
      );
    case "failure_diagnosis":
      return (
        <div className="space-y-1">
          {(o.diagnoses ?? []).map((d, i) => (
            <div key={`${d.run_id}-${d.failure_type}-${i}`} className="bg-slate-900/60 rounded p-2 text-xs space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <Badge className="bg-red-900/50 text-red-300">
                  {FAILURE_LABELS[d.failure_type] ?? d.failure_type}
                </Badge>
                <span className="font-mono text-slate-500">{d.run_id}</span>
                <span className="text-slate-500">{d.split}</span>
              </div>
              <div className="text-slate-300">{d.rationale}</div>
            </div>
          ))}
          {(o.diagnoses ?? []).length === 0 && (
            <p className="text-xs text-slate-400">没有诊断出失败。</p>
          )}
        </div>
      );
    case "skill_mutation":
      return (
        <div className="space-y-2">
          <div className="grid grid-cols-3 gap-2">
            <Stat label="基线请求" value={o.baseline_api_requests ?? 0} />
            <Stat label="可负担请求" value={o.affordable_api_requests ?? 0} />
            <Stat label="可负担 query" value={o.affordable_query_count ?? 0} />
          </div>
          {(o.proposals ?? []).map((p) => (
            <div key={p.version_id} className="bg-slate-900/60 rounded p-2 text-xs space-y-1">
              <div className="text-slate-200">{p.mutation_description}</div>
              <div className="text-slate-500">
                <span className="font-mono">{p.version_id}</span> · 来源试验 {p.source_trials.join("、") || "无"}
              </div>
              {p.changes.map((c) => (
                <div key={c.component} className="text-slate-400">
                  {c.component}：<code>{JSON.stringify(c.before)}</code> → <code>{JSON.stringify(c.after)}</code>
                </div>
              ))}
            </div>
          ))}
          {(o.skipped_mutations ?? []).map((s, i) => (
            <div key={i} className="text-xs text-slate-500">
              跳过 {String(s.mutation)}：{String(s.reason)}
            </div>
          ))}
          <Link className="text-xs text-blue-400 underline" to="/evolution">在 Evolution Lab 查看完整轨迹 →</Link>
        </div>
      );
    case "replay_evaluation":
      return (
        <div className="space-y-2">
          {(o.replays ?? []).map((r) => (
            <div key={r.spec_id} className="bg-slate-900/60 rounded p-2 space-y-1">
              <div className="text-xs text-slate-300">
                候选 <span className="font-mono">{r.candidate_version_id}</span> · 新协议{" "}
                <span className="font-mono">{r.spec_id}</span> · {r.runs.length} 次真实执行
              </div>
              <GateView gate={r.promotion_gate} />
            </div>
          ))}
          {(o.replays ?? []).length === 0 && (
            <p className="text-xs text-slate-400">本轮没有候选，因此没有回放。</p>
          )}
        </div>
      );
    case "promotion_decision":
      return (
        <div className="space-y-1 text-xs">
          <Badge className={
            o.outcome === "promoted" ? "bg-green-900/50 text-green-300"
              : o.outcome === "refused" ? "bg-red-900/50 text-red-300"
                : "bg-slate-700 text-slate-200"
          }>
            {o.outcome ?? "awaiting_human"}
          </Badge>
          <Row label="当前 Active">v{o.active_version_number ?? "—"}</Row>
          {(o.reasons ?? []).length > 0 && (
            <ul className="text-red-200 space-y-0.5">
              {(o.reasons ?? []).map((r) => <li key={r}>· {r}</li>)}
            </ul>
          )}
          {o.promotion_gate && <GateView gate={o.promotion_gate} />}
        </div>
      );
    default:
      return null;
  }
}

export default function StepDetail({ step }: { step: WorkflowStep }) {
  const hasOutput = Object.keys(step.outputs).length > 0;
  return (
    <div className="space-y-2">
      {step.notice && <p className="text-xs text-slate-400">{step.notice}</p>}
      {step.error && (
        <div className="p-2 bg-red-900/30 border border-red-700 rounded text-xs text-red-300 break-words">
          {step.error}
        </div>
      )}
      {hasOutput && <Detail step={step} />}
      {hasOutput && (
        <details>
          <summary className="cursor-pointer text-xs text-slate-500">原始输入 / 输出 JSON</summary>
          <div className="text-xs text-slate-500 mt-1">inputs</div>
          <Json value={step.inputs} />
          <div className="text-xs text-slate-500 mt-1">outputs</div>
          <Json value={step.outputs} />
        </details>
      )}
    </div>
  );
}