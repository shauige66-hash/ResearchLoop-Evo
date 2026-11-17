import { useCallback, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  compareSpec,
  designExperiment,
  getSpec,
  listBenchmarkCases,
  listExperimentRuns,
  listGaps,
  listSkillVersions,
  listSpecs,
  listTemplates,
  lockCandidate,
  runExperiment,
  verifyExperiment,
} from "../api/client";
import BenchmarkPanel from "../components/experiment/BenchmarkPanel";
import SkillPanel from "../components/experiment/SkillPanel";
import {
  Badge,
  ErrorBanner,
  Notice,
  Panel,
  RUN_STYLES,
  SPLIT_STYLES,
  Stat,
  buttonClass,
  coverageText,
  ghostClass,
  inputClass,
} from "../components/experiment/common";
import type {
  Arm,
  BenchmarkListResponse,
  CompareResponse,
  ExperimentRun,
  ExperimentSpec,
  ExperimentTemplate,
  SkillVersion,
  SpecDetail,
  Split,
  VerifyResponse,
} from "../types/experiment";
import { RUN_STATUS_LABELS, SPLIT_LABELS } from "../types/experiment";
import type { ResearchGap } from "../types/gap";

const SOURCES = ["openalex", "crossref", "arxiv"] as const;

function RunRow({
  run,
  verified,
  onVerify,
  busy,
}: {
  run: ExperimentRun;
  verified?: VerifyResponse;
  onVerify: () => void;
  busy: boolean;
}) {
  const ev = run.evaluation;
  const report = verified?.evaluation || ev;
  return (
    <div className="bg-slate-900/50 border border-slate-700 rounded p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge className={run.arm === "baseline" ? "bg-slate-700 text-slate-200" : "bg-blue-900/50 text-blue-300"}>
          {run.arm}
        </Badge>
        <Badge className={RUN_STYLES[run.status]}>{RUN_STATUS_LABELS[run.status]}</Badge>
        <span className="text-xs text-slate-500 font-mono">{run.run_id}</span>
        <span className="text-xs text-slate-500">skill {run.skill_version_id}</span>
        <button onClick={onVerify} disabled={busy} className={`${ghostClass} ml-auto`}>
          独立复核
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        <Stat
          label="Reference Coverage@K"
          value={coverageText(report?.coverage_at_k)}
          hint={report?.status === "computed" ? `${report.reference_set_size} 条已确认参考` : "无已确认参考集"}
        />
        <Stat
          label="API Query Count"
          value={report?.api_query_count ?? run.api_request_count}
          hint={`缓存命中 ${report?.cache_hits ?? run.cache_hits}`}
        />
        <Stat label="Unique Paper Count" value={report?.unique_paper_count ?? run.unique_paper_count} />
        <Stat label="Execution Time" value={`${report?.execution_time_ms ?? run.execution_time_ms} ms`} />
        <Stat
          label="Missed References"
          value={report?.status === "computed" ? report.missed_references.length : "—"}
        />
      </div>

      <div className="text-xs text-slate-400">
        实际查询：
        <span className="font-mono text-slate-300">{JSON.stringify(run.queries_used)}</span>
      </div>

      {report?.status === "computed" && report.missed_references.length > 0 && (
        <div className="text-xs text-slate-400 font-mono break-words">
          未命中：{report.missed_references.join(", ")}
        </div>
      )}
      {report?.notice && <div className="text-xs text-amber-300/90">{report.notice}</div>}

      {run.source_errors.length > 0 && (
        <div className="text-xs text-red-300 space-y-1">
          {run.source_errors.map((e, i) => (
            <div key={i}>
              [{e.source}] status={e.status ?? "—"} {e.detail}
            </div>
          ))}
        </div>
      )}
      {run.error && <ErrorBanner message={run.error} />}

      {verified && (
        <div className="text-xs text-slate-400 border-t border-slate-700 pt-2">
          独立复核：从原始快照重算 · matches_stored=
          <span className={verified.matches_stored ? "text-green-300" : "text-amber-300"}>
            {String(verified.matches_stored)}
          </span>
          <div className="font-mono break-words text-slate-500">{verified.recomputed_from}</div>
          <div className="text-slate-500">
            dataset_fp={report?.dataset_fingerprint} · reference_fp=
            {report?.reference_fingerprint || "—"} · evaluator v{report?.evaluator_version}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ExperimentLab() {
  const [template, setTemplate] = useState<ExperimentTemplate | null>(null);
  const [listing, setListing] = useState<BenchmarkListResponse | null>(null);
  const [versions, setVersions] = useState<SkillVersion[]>([]);
  const [evolvable, setEvolvable] = useState<string[]>([]);
  const [immutable, setImmutable] = useState<string[]>([]);
  const [specs, setSpecs] = useState<ExperimentSpec[]>([]);
  const [gaps, setGaps] = useState<ResearchGap[]>([]);
  const [selectedSpec, setSelectedSpec] = useState("");
  const [detail, setDetail] = useState<SpecDetail | null>(null);
  const [comparison, setComparison] = useState<CompareResponse | null>(null);
  const [runs, setRuns] = useState<ExperimentRun[]>([]);
  const [verified, setVerified] = useState<Record<string, VerifyResponse>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [caseIds, setCaseIds] = useState<string[]>([]);
  const [baselineId, setBaselineId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [gapId, setGapId] = useState("");
  const [sources, setSources] = useState<string[]>([...SOURCES]);
  const [yearFrom, setYearFrom] = useState("2023");
  const [yearTo, setYearTo] = useState("2026");
  const [topK, setTopK] = useState(20);
  const [maxRequests, setMaxRequests] = useState(6);
  const [useCache, setUseCache] = useState(true);

  const loadBase = useCallback(async () => {
    const [templates, cases, registry, specList, gapList] = await Promise.all([
      listTemplates(),
      listBenchmarkCases(),
      listSkillVersions(),
      listSpecs(),
      listGaps({ status: "accepted" }),
    ]);
    setTemplate(templates.templates[0] || null);
    setListing(cases);
    setVersions(registry.versions);
    setEvolvable(registry.evolvable_components);
    setImmutable(registry.immutable_components);
    setSpecs(specList.specs);
    setGaps(gapList.gaps);
    const active = registry.versions.find((v) => v.status === "active");
    const candidate = registry.versions.find((v) => v.status === "candidate");
    setBaselineId((prev) => prev || active?.version_id || "");
    setCandidateId((prev) => prev || candidate?.version_id || "");
    setCaseIds((prev) => (prev.length ? prev : cases.cases.map((c) => c.case_id)));
    setSelectedSpec((prev) => prev || specList.specs[0]?.spec_id || "");
  }, []);

  const loadSpec = useCallback(async (specId: string) => {
    if (!specId) {
      setDetail(null);
      setComparison(null);
      setRuns([]);
      return;
    }
    const [specDetail, compare, runList] = await Promise.all([
      getSpec(specId),
      compareSpec(specId),
      listExperimentRuns({ spec_id: specId }),
    ]);
    setDetail(specDetail);
    setComparison(compare);
    setRuns(runList.runs);
  }, []);

  useEffect(() => {
    loadBase().catch((err) => setError(err instanceof Error ? err.message : "加载失败"));
  }, [loadBase]);

  useEffect(() => {
    loadSpec(selectedSpec).catch((err) => setError(err instanceof Error ? err.message : "加载实验失败"));
  }, [selectedSpec, loadSpec]);

  async function guard(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function reload() {
    await loadBase();
    await loadSpec(selectedSpec);
  }

  const spec = detail?.spec;
  const chartData = (comparison?.comparisons || []).flatMap((c) => {
    const topic = listing?.cases.find((x) => x.case_id === c.case_id)?.topic || c.case_id;
    const short = topic.length > 22 ? `${topic.slice(0, 22)}…` : topic;
    return (["baseline", "candidate"] as Arm[])
      .map((arm) => {
        const run = arm === "baseline" ? c.baseline : c.candidate;
        if (!run) return null;
        return {
          name: `${short} · ${arm}`,
          api_queries: run.api_request_count + run.cache_hits,
          unique_papers: run.unique_paper_count,
        };
      })
      .filter((x): x is { name: string; api_queries: number; unique_papers: number } => x !== null);
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Experiment Lab</h2>
        <p className="text-sm text-slate-400 mt-1">
          单一 Agent-Evolution 模板 · Baseline vs Candidate · 独立纯 Python Evaluator
        </p>
      </div>

      {template && (
        <Notice>
          <div className="font-semibold">待验证假设（{template.hypothesis_status}）</div>
          <p className="mt-1">{template.hypothesis}</p>
          <p className="mt-2 text-xs">{template.notice}</p>
          <p className="mt-1 text-xs">
            Evaluator v{template.evaluator_version} · 指标：
            {template.metrics.map((m) => m.label).join(" / ")}
          </p>
        </Notice>
      )}

      {error && <ErrorBanner message={error} />}

      <BenchmarkPanel listing={listing} onChanged={() => guard(reload)} />

      <SkillPanel
        versions={versions}
        evolvable={evolvable}
        immutable={immutable}
        cases={listing?.cases || []}
        onChanged={() => guard(reload)}
      />

      <Panel
        title="实验协议（冻结后两臂共用）"
        subtitle="候选策略只能改变查询计划，不能改变来源、时间范围、Top-K、请求上限或参考集。"
      >
        <div className="space-y-3">
          <div className="grid md:grid-cols-2 gap-2">
            <select value={baselineId} onChange={(e) => setBaselineId(e.target.value)} className={inputClass}>
              <option value="">Baseline 版本</option>
              {versions.map((v) => (
                <option key={v.version_id} value={v.version_id}>
                  v{v.version_number} · {v.status} · {v.version_id}
                </option>
              ))}
            </select>
            <select value={candidateId} onChange={(e) => setCandidateId(e.target.value)} className={inputClass}>
              <option value="">Candidate 版本</option>
              {versions.map((v) => (
                <option key={v.version_id} value={v.version_id}>
                  v{v.version_number} · {v.status} · {v.version_id}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-wrap gap-3 text-sm items-center">
            {SOURCES.map((s) => (
              <label key={s} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={sources.includes(s)}
                  onChange={(e) =>
                    setSources((prev) => (e.target.checked ? [...prev, s] : prev.filter((x) => x !== s)))
                  }
                />
                {s}
              </label>
            ))}
            <label className="flex items-center gap-1.5">
              年份
              <input value={yearFrom} onChange={(e) => setYearFrom(e.target.value)} className={`${inputClass} w-20`} />
              –
              <input value={yearTo} onChange={(e) => setYearTo(e.target.value)} className={`${inputClass} w-20`} />
            </label>
            <label className="flex items-center gap-1.5">
              top_k
              <input
                type="number"
                min={1}
                max={200}
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
                className={`${inputClass} w-20`}
              />
            </label>
            <label className="flex items-center gap-1.5">
              API 请求上限
              <input
                type="number"
                min={1}
                max={60}
                value={maxRequests}
                onChange={(e) => setMaxRequests(Number(e.target.value))}
                className={`${inputClass} w-20`}
              />
            </label>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={useCache} onChange={(e) => setUseCache(e.target.checked)} />
              使用缓存
            </label>
          </div>

          <select value={gapId} onChange={(e) => setGapId(e.target.value)} className={`${inputClass} w-full`}>
            <option value="">关联研究空白（可选，仅列出人工已接受的空白）</option>
            {gaps.map((g) => (
              <option key={g.gap_id} value={g.gap_id}>
                {g.title}
              </option>
            ))}
          </select>

          <div className="space-y-1 max-h-40 overflow-auto">
            {(listing?.cases || []).map((c) => (
              <label key={c.case_id} className="flex items-center gap-2 text-sm p-1.5 hover:bg-slate-700 rounded">
                <input
                  type="checkbox"
                  checked={caseIds.includes(c.case_id)}
                  onChange={(e) =>
                    setCaseIds((prev) =>
                      e.target.checked ? [...prev, c.case_id] : prev.filter((x) => x !== c.case_id)
                    )
                  }
                />
                <Badge className={SPLIT_STYLES[c.split]}>{c.split}</Badge>
                <span className="flex-1">{c.topic}</span>
                <span className="text-xs text-slate-500">
                  {c.references.filter((r) => r.confirmed_by).length}/{c.references.length} 已确认
                </span>
              </label>
            ))}
          </div>

          <button
            disabled={busy || caseIds.length === 0 || !baselineId || !candidateId || baselineId === candidateId || sources.length === 0}
            onClick={() =>
              guard(async () => {
                const created = await designExperiment({
                  case_ids: caseIds,
                  baseline_version_id: baselineId,
                  candidate_version_id: candidateId,
                  gap_id: gapId || null,
                  sources,
                  year_from: yearFrom ? Number(yearFrom) : null,
                  year_to: yearTo ? Number(yearTo) : null,
                  top_k: topK,
                  max_api_requests: maxRequests,
                  use_cache: useCache,
                });
                await loadBase();
                setSelectedSpec(created.spec_id);
              })
            }
            className={buttonClass}
          >
            {busy ? "处理中..." : "创建冻结实验协议"}
          </button>
        </div>
      </Panel>

      <Panel title="执行与独立评测" subtitle="Holdout 在候选锁定前关闭，且只能执行一次。">
        <div className="space-y-3">
          <select value={selectedSpec} onChange={(e) => setSelectedSpec(e.target.value)} className={`${inputClass} w-full`}>
            <option value="">选择实验协议</option>
            {specs.map((s) => (
              <option key={s.spec_id} value={s.spec_id}>
                {s.spec_id} · {s.case_ids.length} 案例 · {s.created_at.slice(0, 19)}
              </option>
            ))}
          </select>

          {spec && (
            <>
              <div className="text-xs text-slate-400 font-mono bg-slate-900/50 rounded p-2 break-words">
                sources={JSON.stringify(spec.sources)} · years={spec.year_from}–{spec.year_to} · top_k=
                {spec.top_k} · max_api_requests={spec.max_api_requests} · use_cache={String(spec.use_cache)} ·
                baseline={spec.baseline_version_id} · candidate={spec.candidate_version_id} · locked=
                {spec.candidate_locked_at || "未锁定"}
              </div>

              <div className="flex flex-wrap gap-2">
                {(["development", "validation"] as Split[]).map((split) => (
                  <button
                    key={split}
                    disabled={busy || !detail?.cases.some((c) => c.split === split)}
                    onClick={() =>
                      guard(async () => {
                        await runExperiment({ spec_id: spec.spec_id, split });
                        await loadSpec(spec.spec_id);
                      })
                    }
                    className={buttonClass}
                  >
                    运行 {SPLIT_LABELS[split]}（真实 API）
                  </button>
                ))}
                <button
                  disabled={busy || !!spec.candidate_locked_at}
                  onClick={() =>
                    guard(async () => {
                      await lockCandidate(spec.spec_id);
                      await loadSpec(spec.spec_id);
                    })
                  }
                  className={ghostClass}
                >
                  锁定候选版本
                </button>
                <button
                  disabled={busy || !spec.candidate_locked_at || !detail?.cases.some((c) => c.split === "holdout")}
                  onClick={() =>
                    guard(async () => {
                      await runExperiment({ spec_id: spec.spec_id, split: "holdout" });
                      await loadSpec(spec.spec_id);
                    })
                  }
                  className={ghostClass}
                >
                  运行 Holdout 终检（一次性）
                </button>
              </div>

              {comparison && (
                <div
                  className={`p-3 rounded border text-sm ${
                    comparison.promotion_gate.allowed
                      ? "bg-green-900/20 border-green-700 text-green-200"
                      : "bg-amber-900/20 border-amber-700 text-amber-200"
                  }`}
                >
                  <div className="font-semibold">
                    晋升门：{comparison.promotion_gate.allowed ? "全部规则通过" : "关闭（保留当前 Active Skill）"}
                  </div>
                  <ul className="mt-1 space-y-0.5 text-xs list-disc list-inside">
                    {comparison.promotion_gate.reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}

              {chartData.length > 0 && (
                <div className="bg-slate-900/50 rounded p-3">
                  <div className="text-sm font-medium mb-2">真实检索成本与召回规模（来自已存储的运行记录）</div>
                  <ResponsiveContainer width="100%" height={240}>
                    <BarChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="name" tick={{ fill: "#94a3b8", fontSize: 10 }} interval={0} angle={-12} textAnchor="end" height={60} />
                      <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} allowDecimals={false} />
                      <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155", fontSize: 12 }} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      <Bar dataKey="api_queries" name="API 查询数（含缓存命中）" fill="#3b82f6" />
                      <Bar dataKey="unique_papers" name="唯一论文数" fill="#22c55e" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              {(comparison?.comparisons || []).map((c) => (
                <div key={c.case_id} className="border border-slate-700 rounded p-3 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-sm">
                      {listing?.cases.find((x) => x.case_id === c.case_id)?.topic || c.case_id}
                    </span>
                    <Badge className={SPLIT_STYLES[c.split]}>{SPLIT_LABELS[c.split]}</Badge>
                    <span className="text-xs text-slate-400">
                      coverage_delta={c.coverage_delta === null ? "—（无已确认参考集）" : c.coverage_delta.toFixed(3)}
                      {" · "}request_ratio={c.request_ratio === null ? "—" : `${c.request_ratio.toFixed(2)}x`}
                    </span>
                  </div>
                  {(["baseline", "candidate"] as Arm[]).map((arm) => {
                    const run = arm === "baseline" ? c.baseline : c.candidate;
                    if (!run) return null;
                    return (
                      <RunRow
                        key={run.run_id}
                        run={run}
                        verified={verified[run.run_id]}
                        busy={busy}
                        onVerify={() =>
                          guard(async () => {
                            const result = await verifyExperiment(run.run_id);
                            setVerified((prev) => ({ ...prev, [run.run_id]: result }));
                            await loadSpec(spec.spec_id);
                          })
                        }
                      />
                    );
                  })}
                </div>
              ))}

              {runs.length === 0 && (
                <div className="text-sm text-slate-500 py-4 text-center">
                  尚未执行。选择 split 后运行两臂，所有指标来自真实检索与独立 Evaluator。
                </div>
              )}

              {runs.length > 0 && (
                <div className="text-xs text-slate-500">
                  历史运行 {runs.length} 条（含重复运行），每条都保留当时的 Skill Snapshot 与原始响应快照，可复核与对比。
                </div>
              )}
            </>
          )}
        </div>
      </Panel>
    </div>
  );
}