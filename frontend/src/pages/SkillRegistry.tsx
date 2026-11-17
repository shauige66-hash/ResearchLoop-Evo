import { useCallback, useEffect, useState } from "react";
import {
  getPromotionHistory,
  getSkillVersion,
  getSpec,
  listSkillVersions,
  listSpecs,
  promoteSkill,
  rollbackSkill,
} from "../api/client";
import type { ExperimentSpec, SkillVersion, SpecDetail } from "../types/experiment";
import type { SkillEvent, SkillVersionDetail } from "../types/evolution";
import {
  Badge,
  ErrorBanner,
  Notice,
  Panel,
  SKILL_STYLES,
  Stat,
  buttonClass,
  ghostClass,
  inputClass,
} from "../components/experiment/common";

const EVENT_LABELS: Record<string, string> = {
  seeded: "初始化",
  created: "人工创建",
  proposed: "提议器生成",
  promoted: "晋升",
  archived: "归档",
  rolled_back: "回滚",
  locked: "候选锁定",
  llm_call: "LLM 调用",
};

function StrategyView({ version }: { version: SkillVersion }) {
  const s = version.strategy;
  return (
    <div className="text-xs text-slate-300 space-y-1">
      <div>query_templates：{s.query_templates.map((t) => <code key={t} className="mr-2">{t}</code>)}</div>
      <div>keyword_expansion_rules：{s.keyword_expansion_rules.join("、") || "无"}</div>
      <div>source_priority：{s.source_priority.join(" → ")}</div>
      <div>
        domain_synonyms：
        {Object.keys(s.domain_synonyms).length === 0
          ? "无"
          : Object.entries(s.domain_synonyms).map(([k, v]) => (
              <code key={k} className="mr-2">{k} → {v.join("/")}</code>
            ))}
      </div>
      <div>
        search_filters：year [{s.search_filters.year_from ?? "—"}, {s.search_filters.year_to ?? "—"}]
        （只能收窄冻结窗口）
      </div>
      <div>
        retrieval_budget：top_k={s.retrieval_budget.top_k} · max_keywords={s.retrieval_budget.max_keywords} ·
        max_api_requests={s.retrieval_budget.max_api_requests}
      </div>
    </div>
  );
}

function EventRow({ event }: { event: SkillEvent }) {
  return (
    <div className="bg-slate-900/60 rounded p-2 text-xs space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <Badge className="bg-slate-700 text-slate-200">{EVENT_LABELS[event.event] ?? event.event}</Badge>
        {event.version_number !== undefined && (
          <span className="text-slate-300">v{event.version_number}</span>
        )}
        <span className="font-mono text-slate-500">{event.version_id}</span>
        <span className="text-slate-500">{event.created_at}</span>
      </div>
      {event.mutation_description && (
        <div className="text-slate-400">{event.mutation_description}</div>
      )}
      <details>
        <summary className="cursor-pointer text-slate-500">详情</summary>
        <pre className="mt-1 text-slate-300 overflow-auto">{JSON.stringify(event.detail, null, 2)}</pre>
      </details>
    </div>
  );
}

export default function SkillRegistry() {
  const [versions, setVersions] = useState<SkillVersion[]>([]);
  const [evolvable, setEvolvable] = useState<string[]>([]);
  const [immutable, setImmutable] = useState<string[]>([]);
  const [history, setHistory] = useState<SkillEvent[]>([]);
  const [detail, setDetail] = useState<SkillVersionDetail | null>(null);
  const [specs, setSpecs] = useState<ExperimentSpec[]>([]);
  const [specId, setSpecId] = useState("");
  const [specDetail, setSpecDetail] = useState<SpecDetail | null>(null);
  const [decidedBy, setDecidedBy] = useState("");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [registry, trail, specList] = await Promise.all([
      listSkillVersions(),
      getPromotionHistory(),
      listSpecs(),
    ]);
    setVersions(registry.versions);
    setEvolvable(registry.evolvable_components);
    setImmutable(registry.immutable_components);
    setHistory(trail.events);
    setSpecs(specList.specs);
    setSpecId((current) => current || specList.specs[0]?.spec_id || "");
  }, []);

  useEffect(() => {
    load().catch((e: Error) => setError(e.message));
  }, [load]);

  useEffect(() => {
    if (!specId) return;
    getSpec(specId).then(setSpecDetail).catch((e: Error) => setError(e.message));
  }, [specId]);

  async function guard(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const openVersion = (id: string) =>
    guard(async () => {
      setDetail(await getSkillVersion(id));
    });

  const doPromote = () =>
    guard(async () => {
      if (!specDetail) throw new Error("请先选择实验协议");
      const result = await promoteSkill({
        spec_id: specId,
        version_id: specDetail.spec.candidate_version_id,
        decided_by: decidedBy,
      });
      setMessage(`已晋升 v${result.version.version_number}。${result.notice}`);
      setDetail(null);
      await load();
    });

  const doRollback = (versionId: string) =>
    guard(async () => {
      const result = await rollbackSkill({
        version_id: versionId,
        decided_by: decidedBy,
        reason,
      });
      setMessage(`已回滚到 v${result.version.version_number}。${result.notice}`);
      setDetail(null);
      await load();
    });

  const active = versions.find((v) => v.status === "active");
  const candidates = versions.filter((v) => v.status === "candidate");
  const archived = versions.filter((v) => v.status === "archived");
  const gate = specDetail?.promotion_gate;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Skill Registry</h2>
        <p className="text-sm text-slate-400 mt-1">
          唯一可进化技能：literature_search_strategy。版本不可覆盖，历史 Run 保留自己的快照。
        </p>
      </div>

      <Notice>
        晋升必须通过独立评测门禁；没有人工确认的参考集合时不允许晋升。回滚是安全操作，
        它绕过门禁但不声称任何性能提升。
      </Notice>
      {error && <ErrorBanner message={error} />}
      {message && (
        <div className="p-3 bg-green-900/30 border border-green-700 rounded text-sm text-green-200">
          {message}
        </div>
      )}

      <Panel title="可进化边界" subtitle="候选只能改动左侧组件，右侧永远不可达。">
        <div className="grid md:grid-cols-2 gap-3 text-xs">
          <div className="bg-slate-900/60 rounded p-3">
            <div className="text-green-300 mb-1">可进化（{evolvable.length}）</div>
            <ul className="text-slate-300 space-y-0.5">
              {evolvable.map((c) => <li key={c}>· {c}</li>)}
            </ul>
          </div>
          <div className="bg-slate-900/60 rounded p-3">
            <div className="text-red-300 mb-1">不可变（{immutable.length}）</div>
            <ul className="text-slate-300 space-y-0.5">
              {immutable.map((c) => <li key={c}>· {c}</li>)}
            </ul>
          </div>
        </div>
      </Panel>

      <Panel
        title="版本总览"
        subtitle={`共 ${versions.length} 个版本：1 active / ${candidates.length} candidate / ${archived.length} archived`}
      >
        <div className="space-y-2">
          {versions.map((v) => (
            <div key={v.version_id} className="bg-slate-900/60 rounded p-3 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-slate-100">v{v.version_number}</span>
                <Badge className={SKILL_STYLES[v.status]}>{v.status}</Badge>
                <Badge className="bg-slate-700 text-slate-300">{v.created_by}</Badge>
                <span className="font-mono text-xs text-slate-500">{v.version_id}</span>
                {v.parent_version && (
                  <span className="text-xs text-slate-500">父版本 {v.parent_version}</span>
                )}
                <button className={ghostClass} onClick={() => openVersion(v.version_id)}>
                  查看快照与事件
                </button>
                {v.status === "archived" && (
                  <button
                    className={ghostClass}
                    disabled={busy || !decidedBy.trim()}
                    onClick={() => doRollback(v.version_id)}
                  >
                    回滚到此版本
                  </button>
                )}
              </div>
              <p className="text-sm text-slate-300">{v.mutation_description}</p>
              <StrategyView version={v} />
              {v.source_trials.length > 0 && (
                <div className="text-xs text-slate-500">来源试验：{v.source_trials.join("、")}</div>
              )}
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="晋升决策" subtitle="只有该 spec 的候选版本可以被晋升，且必须通过全部门禁。">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            Experiment Spec
            <select className={inputClass} value={specId} onChange={(e) => setSpecId(e.target.value)}>
              <option value="">— 请选择 —</option>
              {specs.map((s) => (
                <option key={s.spec_id} value={s.spec_id}>{s.spec_id}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            决策人（必填）
            <input
              className={inputClass}
              value={decidedBy}
              placeholder="你的名字"
              onChange={(e) => setDecidedBy(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            回滚理由
            <input
              className={inputClass}
              value={reason}
              placeholder="例如：validation 覆盖率回退"
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <button
            className={buttonClass}
            disabled={busy || !specDetail || !decidedBy.trim()}
            onClick={doPromote}
          >
            {busy ? "处理中…" : `晋升候选 ${specDetail?.spec.candidate_version_id ?? ""}`}
          </button>
        </div>

        {gate && (
          <div className="mt-3 space-y-2">
            <div className="grid grid-cols-2 gap-2">
              <Stat label="当前 Active" value={active ? `v${active.version_number}` : "—"} />
              <Stat
                label="门禁状态"
                value={gate.allowed ? "全部通过" : "未通过"}
                hint={gate.allowed ? "可以晋升" : `${gate.reasons.length} 条阻塞原因`}
              />
            </div>
            {!gate.allowed && (
              <div className="bg-red-900/20 border border-red-800 rounded p-3">
                <div className="text-sm text-red-300 mb-1">真实阻塞原因：</div>
                <ul className="text-xs text-red-200 space-y-0.5">
                  {gate.reasons.map((r) => <li key={r}>· {r}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}

      </Panel>

      {detail && (
        <Panel
          title={`版本快照 · v${detail.version.version_number}`}
          subtitle={`该版本被 ${detail.runs_using_version} 个真实 Run 使用；历史 Run 保留自己的快照。`}
          action={<button className={ghostClass} onClick={() => setDetail(null)}>关闭</button>}
        >
          <StrategyView version={detail.version} />
          <div className="mt-3 space-y-1">
            {detail.events.map((e) => <EventRow key={e.id} event={e} />)}
          </div>
        </Panel>
      )}

      <Panel title="变更与晋升历史" subtitle="按时间顺序的完整轨迹，包含被拒绝以外的所有真实事件。">
        {history.length === 0 ? (
          <p className="text-sm text-slate-400">暂无事件。</p>
        ) : (
          <div className="space-y-1">
            {history.map((e) => <EventRow key={e.id} event={e} />)}
          </div>
        )}
      </Panel>
    </div>
  );
}