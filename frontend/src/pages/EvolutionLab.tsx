import { useCallback, useEffect, useState } from "react";
import {
  evolveSkills,
  getEvolutionRound,
  getFailureTypes,
  listEvolutionRounds,
  listSpecs,
  previewSkillQueries,
} from "../api/client";
import type { ExperimentSpec } from "../types/experiment";
import type {
  CandidateProposal,
  EvolutionRound,
  FailureType,
  FailureTypeCatalog,
  RoundSummary,
  TrialExperience,
} from "../types/evolution";
import { FAILURE_LABELS, FAILURE_STYLES } from "../types/evolution";
import {
  Badge,
  ErrorBanner,
  Notice,
  Panel,
  SPLIT_STYLES,
  Stat,
  buttonClass,
  coverageText,
  ghostClass,
  inputClass,
} from "../components/experiment/common";

function ExperienceRow({ exp }: { exp: TrialExperience }) {
  const total = exp.api_request_count + exp.cache_hits;
  return (
    <div className="bg-slate-900/60 rounded p-3 text-xs space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge className={SPLIT_STYLES[exp.split]}>{exp.split}</Badge>
        <Badge className="bg-slate-700 text-slate-200">{exp.arm}</Badge>
        <span className="text-slate-400 font-mono">{exp.run_id}</span>
        {!exp.snapshot_available && (
          <Badge className="bg-red-900/50 text-red-300">快照缺失</Badge>
        )}
      </div>
      <div className="text-slate-300">{exp.topic}</div>
      <div className="text-slate-400">
        实际查询：{exp.queries_used.map((q) => <code key={q} className="mr-2 text-slate-200">{q}</code>)}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        <Stat label="唯一论文" value={exp.unique_paper_count} hint={`top_k=${exp.top_k}`} />
        <Stat label="API 查询（含缓存）" value={total} hint={`网络 ${exp.api_request_count} / 缓存 ${exp.cache_hits}`} />
        <Stat label="覆盖率" value={coverageText(exp.coverage_at_k)} />
        <Stat label="漏检参考" value={exp.missed_references.length} />
        <Stat label="耗时" value={`${exp.execution_time_ms} ms`} />
      </div>
      <div className="flex flex-wrap gap-2">
        {exp.source_tallies.map((t) => (
          <Badge
            key={t.source}
            className={t.paper_count === 0 ? "bg-red-900/40 text-red-300" : "bg-slate-700 text-slate-200"}
          >
            {t.source}: {t.paper_count}
          </Badge>
        ))}
      </div>
      {exp.source_errors.length > 0 && (
        <div className="text-red-300">
          真实来源错误：{JSON.stringify(exp.source_errors)}
        </div>
      )}
      {exp.split !== "development" && (
        <div className="text-slate-500">
          非 development 试验：参考标题与年份不参与变异，避免泄漏。
        </div>
      )}
    </div>
  );
}

function ProposalCard({
  proposal,
  onPreview,
  preview,
}: {
  proposal: CandidateProposal;
  onPreview: () => void;
  preview: string[] | null;
}) {
  return (
    <div className="bg-slate-900/60 rounded p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge className="bg-amber-900/50 text-amber-300">v{proposal.version_number} 候选</Badge>
        <span className="font-mono text-xs text-slate-400">{proposal.version_id}</span>
        <span className="text-xs text-slate-500">父版本 {proposal.parent_version}</span>
      </div>
      <p className="text-sm text-slate-200">{proposal.mutation_description}</p>
      <div className="text-xs text-slate-400">证据来源：{proposal.grounding}</div>
      <div className="flex flex-wrap gap-1">
        {proposal.addressed_failures.length === 0 ? (
          <span className="text-xs text-slate-500">未对应任何已诊断失败（基于词汇证据提出）</span>
        ) : (
          proposal.addressed_failures.map((f) => (
            <Badge key={f} className={FAILURE_STYLES[f]}>{FAILURE_LABELS[f]}</Badge>
          ))
        )}
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Stat label="预计查询数" value={proposal.projected_query_count} />
        <Stat label="预计 API 请求" value={proposal.projected_api_requests} />
        <Stat
          label="预计成本比"
          value={proposal.projected_request_ratio === null ? "—" : `${proposal.projected_request_ratio.toFixed(2)}x`}
          hint="上限 1.50x"
        />
      </div>
      <div className="text-xs text-slate-400 space-y-1">
        <div>改动组件：{proposal.changes.map((c) => c.component).join("、") || "无"}</div>
        {proposal.changes.map((c) => (
          <details key={c.component} className="bg-slate-800/60 rounded p-2">
            <summary className="cursor-pointer text-slate-300">{c.component}</summary>
            <div className="mt-1 text-red-300">before: {JSON.stringify(c.before)}</div>
            <div className="text-green-300">after: {JSON.stringify(c.after)}</div>
          </details>
        ))}
        <div>来源试验：{proposal.source_trials.join("、") || "无"}</div>
      </div>
      <div className="flex items-center gap-2">
        <button className={ghostClass} onClick={onPreview}>预览查询计划</button>
        {preview && (
          <span className="text-xs text-slate-300">
            {preview.map((q) => <code key={q} className="mr-2">{q}</code>)}
          </span>
        )}
      </div>
    </div>
  );
}

export default function EvolutionLab() {
  const [specs, setSpecs] = useState<ExperimentSpec[]>([]);
  const [specId, setSpecId] = useState("");
  const [catalog, setCatalog] = useState<FailureTypeCatalog | null>(null);
  const [rounds, setRounds] = useState<RoundSummary[]>([]);
  const [round, setRound] = useState<EvolutionRound | null>(null);
  const [maxCandidates, setMaxCandidates] = useState(3);
  const [useLlm, setUseLlm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [previews, setPreviews] = useState<Record<string, string[]>>({});

  const loadBase = useCallback(async () => {
    const [specList, types] = await Promise.all([listSpecs(), getFailureTypes()]);
    setSpecs(specList.specs);
    setCatalog(types);
    setSpecId((current) => current || specList.specs[0]?.spec_id || "");
  }, []);

  const loadRounds = useCallback(async (id: string) => {
    if (!id) return;
    const listing = await listEvolutionRounds(id);
    setRounds(listing.rounds);
    if (listing.rounds.length > 0) {
      const detail = await getEvolutionRound(listing.rounds[0].round_id);
      setRound(detail.round);
    } else {
      setRound(null);
    }
  }, []);

  useEffect(() => {
    loadBase().catch((e: Error) => setError(e.message));
  }, [loadBase]);

  useEffect(() => {
    loadRounds(specId).catch((e: Error) => setError(e.message));
  }, [specId, loadRounds]);

  async function guard(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const runRound = () =>
    guard(async () => {
      const created = await evolveSkills({
        spec_id: specId,
        max_candidates: maxCandidates,
        use_llm: useLlm,
      });
      setRound(created);
      setPreviews({});
      await loadRounds(specId);
      setRound(created);
    });

  const openRound = (id: string) =>
    guard(async () => {
      const detail = await getEvolutionRound(id);
      setRound(detail.round);
      setPreviews({});
    });

  const preview = (proposal: CandidateProposal) =>
    guard(async () => {
      const exp = round?.experiences.find((e) => e.split === "development");
      if (!exp) throw new Error("本轮没有 development 试验可用于预览");
      const result = await previewSkillQueries({
        version_id: proposal.version_id,
        topic: exp.topic,
        query: exp.query,
      });
      setPreviews((prev) => ({ ...prev, [proposal.version_id]: result.queries }));
    });

  const spec = specs.find((s) => s.spec_id === specId);
  const devCount = round?.experiences.filter((e) => e.split === "development").length ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Evolution Lab</h2>
        <p className="text-sm text-slate-400 mt-1">
          从真实执行的试验中收集经验、诊断失败、提出候选策略。候选不会自动生效。
        </p>
      </div>

      {catalog && <Notice>{catalog.notice}</Notice>}
      {error && <ErrorBanner message={error} />}

      <Panel
        title="1 · 选择实验协议"
        subtitle="进化只针对该 spec 的候选版本，且只使用 development 试验作为变异依据。"
      >
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            Experiment Spec
            <select className={inputClass} value={specId} onChange={(e) => setSpecId(e.target.value)}>
              <option value="">— 请选择 —</option>
              {specs.map((s) => (
                <option key={s.spec_id} value={s.spec_id}>
                  {s.spec_id}（{s.case_ids.length} 案例）
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            本轮候选上限
            <select
              className={inputClass}
              value={maxCandidates}
              onChange={(e) => setMaxCandidates(Number(e.target.value))}
            >
              {[1, 2, 3].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-400">
            <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
            尝试 LLM 提议器（需服务端配置，限额 1 次调用）
          </label>
          <button className={buttonClass} disabled={!specId || busy} onClick={runRound}>
            {busy ? "执行中…" : "运行一轮进化"}
          </button>
        </div>
        {spec && (
          <div className="mt-3 text-xs text-slate-400">
            基线 {spec.baseline_version_id} · 候选 {spec.candidate_version_id} · 来源{" "}
            {spec.sources.join("/")} · top_k={spec.top_k} · 请求上限 {spec.max_api_requests} ·
            锁定 {spec.candidate_locked_at ?? "未锁定"}
          </div>
        )}
        {catalog && (
          <div className="mt-3 flex flex-wrap gap-1">
            {catalog.failure_types.map((f) => (
              <Badge key={f.key} className={FAILURE_STYLES[f.key as FailureType]}>
                {FAILURE_LABELS[f.key as FailureType]} / {f.label}
              </Badge>
            ))}
          </div>
        )}
      </Panel>

      {rounds.length > 0 && (
        <Panel title="2 · 进化轮次历史" subtitle="每轮都是不可变记录，可回看当时的经验与诊断。">
          <div className="space-y-1">
            {rounds.map((r) => (
              <button
                key={r.round_id}
                onClick={() => openRound(r.round_id)}
                className={`w-full text-left px-3 py-2 rounded text-xs flex flex-wrap gap-3 items-center ${
                  round?.round_id === r.round_id ? "bg-blue-900/40" : "bg-slate-900/60 hover:bg-slate-700"
                }`}
              >
                <span className="font-mono text-slate-300">{r.round_id}</span>
                <Badge className="bg-slate-700 text-slate-200">{r.proposer_mode}</Badge>
                <span className="text-slate-400">经验 {r.experience_count}</span>
                <span className="text-slate-400">诊断 {r.diagnosis_count}</span>
                <span className="text-slate-400">候选 {r.proposal_count}</span>
                <span className="text-slate-500">{r.created_at}</span>
              </button>
            ))}
          </div>
        </Panel>
      )}

      {round && (
        <>
          <Panel
            title="3 · 预算推导"
            subtitle="候选的查询数由实测基线成本 × 1.5 上限推出，不是拍脑袋设定。"
          >
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <Stat label="实测基线请求数" value={round.baseline_api_requests} hint="含缓存命中" />
              <Stat label="可负担请求数" value={round.affordable_api_requests} hint="min(基线×1.5, spec 上限)" />
              <Stat label="可负担查询数" value={round.affordable_query_count} />
              <Stat label="development 试验" value={devCount} hint={`共 ${round.experiences.length} 条经验`} />
            </div>
            <div className="mt-3 text-xs text-slate-400">
              提议器：{round.proposer_mode}
              {round.llm_skip_reason && <span className="ml-2 text-amber-300">{round.llm_skip_reason}</span>}
            </div>
            <Notice>{round.notice}</Notice>
          </Panel>

          <Panel
            title="4 · 失败诊断"
            subtitle="每条诊断都附带触发它的真实数字；没有信号就不产生诊断。"
          >
            {round.diagnoses.length === 0 ? (
              <p className="text-sm text-slate-400">
                本轮没有可诊断的失败。这不代表策略最优，只代表现有信号未触发任何规则。
              </p>
            ) : (
              <div className="space-y-2">
                {round.diagnoses.map((d, i) => (
                  <div key={`${d.run_id}-${d.failure_type}-${i}`} className="bg-slate-900/60 rounded p-3 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge className={FAILURE_STYLES[d.failure_type]}>{FAILURE_LABELS[d.failure_type]}</Badge>
                      <Badge className={SPLIT_STYLES[d.split]}>{d.split}</Badge>
                      <span className="font-mono text-xs text-slate-400">{d.run_id}</span>
                    </div>
                    <p className="text-sm text-slate-200">{d.rationale}</p>
                    <div className="text-xs text-slate-400">建议改动：{d.suggested_component}</div>
                    <details className="text-xs">
                      <summary className="cursor-pointer text-slate-400">证据数据</summary>
                      <pre className="mt-1 text-slate-300 overflow-auto">{JSON.stringify(d.evidence, null, 2)}</pre>
                    </details>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          {round.skipped_mutations.length > 0 && (
            <Panel title="5 · 被拒绝的变异" subtitle="缺少证据或需要改动冻结协议时，系统拒绝编造变异。">
              <div className="space-y-2">
                {round.skipped_mutations.map((s) => (
                  <div key={s.mutation} className="bg-slate-900/60 rounded p-3 text-sm">
                    <div className="text-slate-200 font-mono text-xs">{s.mutation}</div>
                    <div className="text-amber-200 mt-1">{s.reason}</div>
                  </div>
                ))}
              </div>
            </Panel>
          )}

          <Panel
            title="6 · 候选策略"
            subtitle={`本轮产生 ${round.proposals.length} 个候选，全部停留在 candidate 状态。`}
          >
            {round.proposals.length === 0 ? (
              <p className="text-sm text-slate-400">本轮没有产生候选，原因见上方"被拒绝的变异"。</p>
            ) : (
              <div className="space-y-3">
                {round.proposals.map((p) => (
                  <ProposalCard
                    key={p.version_id}
                    proposal={p}
                    preview={previews[p.version_id] ?? null}
                    onPreview={() => preview(p)}
                  />
                ))}
              </div>
            )}
          </Panel>

          <Panel title="7 · 本轮真实经验" subtitle="全部来自已落库的 ExperimentRun 与其原始快照。">
            <div className="space-y-2">
              {round.experiences.map((e) => <ExperienceRow key={e.run_id} exp={e} />)}
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}