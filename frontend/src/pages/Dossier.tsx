import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { generateReport, getGap, getWorkflowDossier, listWorkflows } from "../api/client";
import EvidenceChain from "../components/gap/EvidenceChain";
import type { ResearchGap } from "../types/gap";
import type { ReportResponse } from "../types/paper";
import type { Dossier as DossierData, WorkflowRun } from "../types/workflow";
import {
  Badge,
  ErrorBanner,
  Notice,
  Panel,
  Stat,
  coverageText,
  ghostClass,
  inputClass,
  SPLIT_STYLES,
} from "../components/experiment/common";

const KIND_STYLES: Record<string, string> = {
  facts: "bg-blue-900/50 text-blue-300",
  author_claims: "bg-purple-900/50 text-purple-300",
  system_inference: "bg-amber-900/50 text-amber-300",
  mixed: "bg-slate-700 text-slate-300",
};

const KIND_LABELS: Record<string, string> = {
  facts: "事实",
  author_claims: "作者观点",
  system_inference: "系统推断",
  mixed: "混合",
};

const ACCEPTANCE: Record<string, { label: string; className: string; detail: string }> = {
  self_evolution_accepted: {
    label: "自进化已通过最终验收",
    className: "bg-green-900/30 border-green-700 text-green-200",
    detail: "候选通过了全部门禁并由人工确认晋升。",
  },
  awaiting_reference_set: {
    label: "等待人工确认参考集合",
    className: "bg-amber-900/20 border-amber-700 text-amber-200",
    detail:
      "参考 DOI 已通过 Crossref/OpenAlex 元数据核验，但没有人工确认，因此覆盖率为 null、晋升门禁关闭。" +
      "不能宣称自进化实验已通过最终验收。",
  },
  evolution_not_accepted: {
    label: "自进化未通过验收",
    className: "bg-red-900/20 border-red-700 text-red-200",
    detail: "参考集合已确认，但候选未满足全部晋升条件；Active 版本保持不变。",
  },
};

function ComparisonBars({ dossier }: { dossier: DossierData }) {
  const comparisons = dossier.experiment.comparisons;
  if (comparisons.length === 0) {
    return <p className="text-sm text-slate-400">该流程还没有可比较的实验运行。</p>;
  }
  const maxPapers = Math.max(
    1,
    ...comparisons.flatMap((c) => [
      c.baseline?.unique_paper_count ?? 0,
      c.candidate?.unique_paper_count ?? 0,
    ]),
  );
  const maxRequests = Math.max(
    1,
    ...comparisons.flatMap((c) => [
      (c.baseline?.api_request_count ?? 0) + (c.baseline?.cache_hits ?? 0),
      (c.candidate?.api_request_count ?? 0) + (c.candidate?.cache_hits ?? 0),
    ]),
  );
  return (
    <div className="space-y-3">
      {comparisons.map((c) => {
        const baseRequests = (c.baseline?.api_request_count ?? 0) + (c.baseline?.cache_hits ?? 0);
        const candRequests = (c.candidate?.api_request_count ?? 0) + (c.candidate?.cache_hits ?? 0);
        return (
          <div key={c.case_id} className="bg-slate-900/60 rounded p-3 space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="font-mono text-slate-300">{c.case_id}</span>
              <Badge className={SPLIT_STYLES[c.split]}>{c.split}</Badge>
              <Badge className={c.reference_status === "confirmed" ? "bg-green-900/50 text-green-300" : "bg-amber-900/50 text-amber-300"}>
                {c.reference_status}
              </Badge>
              <span className="text-slate-400">
                Coverage@K {coverageText(c.baseline?.evaluation?.coverage_at_k)} →{" "}
                {coverageText(c.candidate?.evaluation?.coverage_at_k)}
              </span>
              <span className="text-slate-400">
                Δ {c.coverage_delta === null ? "—" : c.coverage_delta.toFixed(3)}
              </span>
              <span className="text-slate-400">
                请求比 {c.request_ratio === null ? "—" : `${c.request_ratio.toFixed(2)}×`}
              </span>
            </div>
            <div className="grid md:grid-cols-2 gap-3 text-xs">
              <div className="space-y-1">
                <div className="text-slate-500">唯一论文数（baseline / candidate）</div>
                <div className="flex items-center gap-2">
                  <span className="w-8 text-right text-slate-300">{c.baseline?.unique_paper_count ?? 0}</span>
                  <div className="flex-1 h-2 bg-slate-700 rounded overflow-hidden">
                    <div
                      className="h-2 bg-slate-400"
                      style={{ width: `${Math.round(((c.baseline?.unique_paper_count ?? 0) / maxPapers) * 100)}%` }}
                    />
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-8 text-right text-slate-300">{c.candidate?.unique_paper_count ?? 0}</span>
                  <div className="flex-1 h-2 bg-slate-700 rounded overflow-hidden">
                    <div
                      className="h-2 bg-blue-400"
                      style={{ width: `${Math.round(((c.candidate?.unique_paper_count ?? 0) / maxPapers) * 100)}%` }}
                    />
                  </div>
                </div>
              </div>
              <div className="space-y-1">
                <div className="text-slate-500">总检索成本（请求 + 缓存命中）</div>
                <div className="flex items-center gap-2">
                  <span className="w-8 text-right text-slate-300">{baseRequests}</span>
                  <div className="flex-1 h-2 bg-slate-700 rounded overflow-hidden">
                    <div className="h-2 bg-slate-400" style={{ width: `${Math.round((baseRequests / maxRequests) * 100)}%` }} />
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-8 text-right text-slate-300">{candRequests}</span>
                  <div className="flex-1 h-2 bg-slate-700 rounded overflow-hidden">
                    <div className="h-2 bg-blue-400" style={{ width: `${Math.round((candRequests / maxRequests) * 100)}%` }} />
                  </div>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function GapChain({ gapId }: { gapId: string }) {
  const [gap, setGap] = useState<ResearchGap | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    setGap(null);
    setErr("");
    getGap(gapId)
      .then((result) => {
        if (alive) setGap(result.gap);
      })
      .catch((e: Error) => {
        if (alive) setErr(e.message);
      });
    return () => {
      alive = false;
    };
  }, [gapId]);

  if (err) return <ErrorBanner message={err} />;
  if (!gap) return <p className="text-xs text-slate-500">证据链加载中…</p>;
  return <EvidenceChain gap={gap} />;
}

export default function Dossier() {
  const [params, setParams] = useSearchParams();
  const [workflows, setWorkflows] = useState<WorkflowRun[]>([]);
  const [workflowId, setWorkflowId] = useState(params.get("workflow_id") ?? "");
  const [dossier, setDossier] = useState<DossierData | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [openChain, setOpenChain] = useState<string | null>(null);

  useEffect(() => {
    listWorkflows()
      .then((listing) => {
        setWorkflows(listing.workflows);
        const withDossier = listing.workflows.find((w) => w.context.dossier);
        const initial = params.get("workflow_id") || withDossier?.workflow_id || listing.workflows[0]?.workflow_id || "";
        setWorkflowId((current) => current || initial);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const load = useCallback(async (id: string) => {
    if (!id) return;
    setBusy(true);
    setError("");
    setDossier(null);
    setReport(null);
    try {
      const result = await getWorkflowDossier(id);
      setDossier(result.dossier);
      setParams({ workflow_id: id });
      const full = await generateReport(result.dossier.literature.run_id);
      setReport(full);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [setParams]);

  useEffect(() => {
    if (workflowId) load(workflowId);
  }, [workflowId, load]);

  const acceptance = dossier ? ACCEPTANCE[dossier.acceptance_status] : null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Research Dossier</h2>
        <p className="text-sm text-slate-400 mt-1">
          第 18 步产物：把一条流程真实跑出来的文献、空白、假设、实验、进化与版本决策汇总成一份可追溯档案。
        </p>
      </div>

      <Notice>
        档案中的每个数字都来自已存储的真实记录。没有人工确认参考集合时，验收状态原样写为
        awaiting_reference_set，不冒充通过。
      </Notice>
      {error && <ErrorBanner message={error} />}

      <Panel title="选择流程" subtitle="只有执行到第 18 步的流程才有档案。">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            Workflow
            <select className={inputClass} value={workflowId} onChange={(e) => setWorkflowId(e.target.value)}>
              <option value="">— 请选择 —</option>
              {workflows.map((w) => (
                <option key={w.workflow_id} value={w.workflow_id}>
                  {w.workflow_id} · {w.topic} {w.context.dossier ? "（有档案）" : ""}
                </option>
              ))}
            </select>
          </label>
          <button className={ghostClass} disabled={busy || !workflowId} onClick={() => load(workflowId)}>
            {busy ? "加载中…" : "重新加载"}
          </button>
          <Link className="text-xs text-blue-400 underline" to="/workflow">回到流程执行 →</Link>
        </div>
      </Panel>

      {dossier && acceptance && (
        <>
          <div className={`p-3 border rounded text-sm ${acceptance.className}`}>
            <div className="font-semibold">{acceptance.label}</div>
            <div className="text-xs mt-1">{acceptance.detail}</div>
          </div>

          <Panel title="总览" subtitle={`生成时间 ${dossier.generated_at}`}>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              <Stat label="主题" value={<span className="text-sm">{dossier.topic}</span>} />
              <Stat label="文献" value={dossier.literature.paper_count} hint={dossier.literature.extraction_mode} />
              <Stat label="候选空白" value={dossier.gaps.length} hint={`接受 ${dossier.accepted_gap_id ? 1 : 0}`} />
              <Stat label="实验运行" value={dossier.experiment.run_count} hint={`确认参考 case ${dossier.experiment.confirmed_reference_cases}`} />
              <Stat label="Active 版本" value={`v${dossier.skill.active_version_number ?? "—"}`} hint={`共 ${dossier.skill.total_versions} 个版本`} />
            </div>
          </Panel>

          <Panel title="研究假设" subtitle="待验证假设，不是已成立的结论。">
            <p className="text-sm text-slate-200">{dossier.hypothesis ?? "尚未形成假设。"}</p>
            <Badge className="bg-amber-900/50 text-amber-300 mt-2">{dossier.hypothesis_status}</Badge>
          </Panel>

          <Panel title="文献与报告" subtitle="事实、作者观点、系统推断分开标注。">
            <div className="flex flex-wrap gap-2 mb-3">
              {Object.entries(dossier.literature.section_kind_counts).map(([kind, count]) => (
                <Badge key={kind} className={KIND_STYLES[kind] ?? KIND_STYLES.mixed}>
                  {KIND_LABELS[kind] ?? kind} × {count}
                </Badge>
              ))}
            </div>
            {report ? (
              <div className="space-y-2">
                {report.sections.map((s) => (
                  <details key={s.id} className="bg-slate-900/60 rounded p-2">
                    <summary className="cursor-pointer text-sm text-slate-200 flex items-center gap-2">
                      <Badge className={KIND_STYLES[s.kind]}>{KIND_LABELS[s.kind]}</Badge>
                      {s.title}
                      <span className="text-xs text-slate-500">引用 {s.paper_ids.length} 篇</span>
                    </summary>
                    <div className="mt-2 space-y-1 text-xs text-slate-300">
                      {s.paragraphs.map((p, i) => <p key={i}>{p}</p>)}
                    </div>
                  </details>
                ))}
                {report.caveats.length > 0 && (
                  <ul className="text-xs text-amber-200 space-y-0.5">
                    {report.caveats.map((c) => <li key={c}>· {c}</li>)}
                  </ul>
                )}
              </div>
            ) : (
              <p className="text-sm text-slate-400">报告加载中或不可用。</p>
            )}
          </Panel>

          <Panel title="研究空白与反证" subtitle="反证只表示当前检索范围内的发现。">
            {dossier.gaps.length === 0 ? (
              <p className="text-sm text-slate-400">该流程没有产生候选空白。</p>
            ) : (
              <>
              <table className="w-full text-xs text-slate-300">
                <thead className="text-slate-500">
                  <tr>
                    <th className="text-left py-1">空白</th>
                    <th className="text-left">类型</th>
                    <th className="text-left">来源</th>
                    <th className="text-left">状态</th>
                    <th className="text-left">门禁</th>
                    <th className="text-left">置信度</th>
                    <th className="text-right">支撑论文</th>
                    <th className="text-right">反证</th>
                    <th className="text-right">证据链</th>
                  </tr>
                </thead>
                <tbody>
                  {dossier.gaps.map((g) => (
                    <tr key={g.gap_id} className="border-t border-slate-700">
                      <td className="py-1">{g.title}</td>
                      <td>{g.gap_type}</td>
                      <td className={g.discovery_mode === "llm_pipeline" ? "text-purple-300" : "text-slate-400"}>
                        {g.discovery_mode === "llm_pipeline" ? "LLM 管线" : "规则式"}
                      </td>
                      <td className={g.status === "accepted" ? "text-green-300" : "text-slate-400"}>{g.status}</td>
                      <td>{g.gate_status || "—"}</td>
                      <td>{g.confidence_label}</td>
                      <td className="text-right">{g.supporting_papers}</td>
                      <td className="text-right">{g.counter_evidence}</td>
                      <td className="text-right">
                        <button
                          type="button"
                          className={ghostClass}
                          onClick={() => setOpenChain((cur) => (cur === g.gap_id ? null : g.gap_id))}
                        >
                          {openChain === g.gap_id ? "收起" : "展开"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {openChain && (
                <div className="mt-3 border-t border-slate-700 pt-3">
                  <GapChain gapId={openChain} />
                </div>
              )}
              </>
            )}
            <Link className="text-xs text-blue-400 underline mt-2 inline-block" to="/gaps">
              在 Research Gap 页查看证据原文 →
            </Link>
          </Panel>

          <Panel title="实验对比" subtitle="条形长度按真实计算结果比例绘制；覆盖率为 null 时显示 —。">
            <ComparisonBars dossier={dossier} />
            {dossier.experiment.promotion_gate && (
              <div className="mt-3">
                <Badge className={dossier.experiment.promotion_gate.allowed ? "bg-green-900/50 text-green-300" : "bg-red-900/50 text-red-300"}>
                  {dossier.experiment.promotion_gate.allowed ? "门禁全部通过" : `门禁未通过（${dossier.experiment.promotion_gate.reasons.length} 条）`}
                </Badge>
                <ul className="text-xs text-red-200 space-y-0.5 mt-1">
                  {dossier.experiment.promotion_gate.reasons.map((r) => <li key={r}>· {r}</li>)}
                </ul>
              </div>
            )}
          </Panel>

          <Panel title="进化与版本决策" subtitle="候选数量、跳过原因与最终决定都来自真实记录。">
            <div className="grid grid-cols-3 gap-2 mb-3">
              <Stat label="进化轮次" value={<span className="font-mono text-xs">{dossier.evolution.round_id ?? "—"}</span>} />
              <Stat label="本轮候选" value={dossier.evolution.proposals} />
              <Stat label="回放协议" value={dossier.evolution.replay_spec_ids.length} />
            </div>
            {dossier.evolution.skipped_mutations.length > 0 && (
              <div className="text-xs text-slate-500 space-y-0.5 mb-2">
                {dossier.evolution.skipped_mutations.map((s, i) => (
                  <div key={i}>跳过 {String(s.mutation)}：{String(s.reason)}</div>
                ))}
              </div>
            )}
            {dossier.skill.promotion_outcome ? (
              <div className="bg-slate-900/60 rounded p-2 text-xs space-y-1">
                <div className="text-slate-200">
                  决定 {dossier.skill.promotion_outcome.decision} · 结果{" "}
                  <span className={dossier.skill.promotion_outcome.outcome === "promoted" ? "text-green-300" : "text-amber-300"}>
                    {dossier.skill.promotion_outcome.outcome}
                  </span>{" "}
                  · 决策人 {dossier.skill.promotion_outcome.decided_by}
                </div>
                <div className="text-slate-400">
                  当前 Active：v{dossier.skill.promotion_outcome.active_version_number ?? "—"}
                </div>
                {(dossier.skill.promotion_outcome.reasons ?? []).map((r) => (
                  <div key={r} className="text-red-200">· {r}</div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-400">尚未记录晋升 / 回滚决定。</p>
            )}
            <Link className="text-xs text-blue-400 underline mt-2 inline-block" to="/skills">
              在 Skill Registry 查看完整版本轨迹 →
            </Link>
          </Panel>

          <Panel
            title="LLM 链路与调用审计"
            subtitle="只展示真实落库的计量与 hash；不存 prompt 正文，也不展示任何 Key。"
          >
            {dossier.llm ? (
              <>
                <div className="grid grid-cols-3 gap-2 mb-3">
                  <Stat
                    label="Provider / 模型"
                    value={<span className="text-sm">{dossier.llm.configured ? `${dossier.llm.provider} / ${dossier.llm.model}` : "未配置"}</span>}
                    hint={dossier.llm.status}
                  />
                  <Stat label="真实调用" value={`${dossier.llm.calls_used} / ${dossier.llm.max_calls}`} hint={`失败 ${dossier.llm.failed_calls}`} />
                  <Stat label="缓存命中（免费）" value={dossier.llm.cache_hits} hint={`Evidence Card ${dossier.llm.evidence_cards}`} />
                </div>
                <div className="grid grid-cols-2 gap-2 mb-3">
                  <Stat
                    label="Token 用量"
                    value={dossier.llm.total_tokens === null ? "—" : dossier.llm.total_tokens}
                    hint={dossier.llm.total_tokens === null ? "provider 未返回 usage，不猜测" : "provider 返回值"}
                  />
                  <Stat
                    label="Gap Pipeline"
                    value={<span className="font-mono text-xs">{dossier.llm.gap_pipeline_id ?? "—"}</span>}
                    hint={dossier.llm.gap_pipeline_status}
                  />
                </div>
                {Object.keys(dossier.llm.stage_status).length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-2">
                    {Object.entries(dossier.llm.stage_status).map(([stage, status]) => (
                      <Badge key={stage} className="bg-slate-700 text-slate-300">
                        {stage}: {status}
                      </Badge>
                    ))}
                  </div>
                )}
                {Object.keys(dossier.llm.role_usage).length > 0 && (
                  <div className="text-xs text-slate-400 space-y-0.5 mb-2">
                    {Object.entries(dossier.llm.role_usage).map(([role, count]) => (
                      <div key={role}>· {role}: {count} 次</div>
                    ))}
                  </div>
                )}
                <p className="text-xs text-slate-500">{dossier.llm.notice}</p>
              </>
            ) : (
              <p className="text-xs text-slate-500">
                此档案生成于 LLM 审计字段加入之前，只记录了确定性结果，没有 LLM 计量可展示。
              </p>
            )}
            <Link className="text-xs text-blue-400 underline mt-2 inline-block" to="/gaps">
              在 Research Gap 页查看完整证据链与逐条调用审计 →
            </Link>
          </Panel>
        </>
      )}
    </div>
  );
}