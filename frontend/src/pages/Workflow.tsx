import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  advanceWorkflow,
  approveWorkflowGap,
  decideWorkflowPromotion,
  getWorkflow,
  listSkillVersions,
  listWorkflows,
  startWorkflow,
} from "../api/client";
import type { SkillVersion } from "../types/experiment";
import type { StepId, WorkflowRun } from "../types/workflow";
import { STEP_LABELS, STEP_STYLES, WORKFLOW_STYLES } from "../types/workflow";
import {
  Badge,
  ErrorBanner,
  Notice,
  Panel,
  Stat,
  buttonClass,
  ghostClass,
  inputClass,
} from "../components/experiment/common";
import StepDetail from "../components/workflow/StepDetail";

export default function Workflow() {
  const [workflows, setWorkflows] = useState<WorkflowRun[]>([]);
  const [selected, setSelected] = useState<WorkflowRun | null>(null);
  const [versions, setVersions] = useState<SkillVersion[]>([]);
  const [topic, setTopic] = useState("");
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(12);
  const [decidedBy, setDecidedBy] = useState("");
  const [note, setNote] = useState("");
  const [rollbackTarget, setRollbackTarget] = useState("");
  const [rewindTo, setRewindTo] = useState<StepId | "">("");
  const [expanded, setExpanded] = useState<StepId | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async (keepId?: string) => {
    const listing = await listWorkflows();
    setWorkflows(listing.workflows);
    const id = keepId ?? selected?.workflow_id;
    if (id) {
      const detail = await getWorkflow(id);
      setSelected(detail.workflow);
    }
  }, [selected?.workflow_id]);

  useEffect(() => {
    listWorkflows()
      .then((listing) => {
        setWorkflows(listing.workflows);
        if (listing.workflows[0]) return getWorkflow(listing.workflows[0].workflow_id);
        return null;
      })
      .then((detail) => {
        if (detail) setSelected(detail.workflow);
      })
      .catch((e: Error) => setError(e.message));
    listSkillVersions().then((r) => setVersions(r.versions)).catch(() => undefined);
  }, []);

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

  const doStart = () =>
    guard(async () => {
      const result = await startWorkflow({
        topic,
        query: query || undefined,
        top_k: topK,
        sources: ["openalex", "crossref", "arxiv"],
      });
      setSelected(result.workflow);
      setExpanded("research_topic");
      setMessage(`已创建流程 ${result.workflow.workflow_id}，尚未执行任何步骤。`);
      await refresh(result.workflow.workflow_id);
    });

  const doAdvance = (maxSteps: number, fromStep?: StepId | null) =>
    guard(async () => {
      if (!selected) return;
      const result = await advanceWorkflow(selected.workflow_id, {
        max_steps: maxSteps,
        from_step: fromStep ?? undefined,
      });
      setSelected(result.workflow);
      const last = result.executed[result.executed.length - 1];
      if (last) setExpanded(last);
      setMessage(
        result.executed.length > 0
          ? `本次真实执行：${result.executed.map((s) => STEP_LABELS[s]).join(" → ")}`
          : "没有可执行的步骤。",
      );
      await refresh(result.workflow.workflow_id);
    });

  const doApprove = (gapId: string, decision: "accepted" | "rejected") =>
    guard(async () => {
      if (!selected) return;
      const result = await approveWorkflowGap(selected.workflow_id, {
        gap_id: gapId,
        decision,
        decided_by: decidedBy,
        human_note: note,
      });
      if (decision === "rejected") {
        setSelected(result.workflow);
        setMessage("已拒绝该空白，门禁保持关闭。");
        await refresh(result.workflow.workflow_id);
        return;
      }
      const advanced = await advanceWorkflow(selected.workflow_id, { max_steps: 1 });
      setSelected(advanced.workflow);
      setMessage(`已接受该空白，门禁关闭并执行了 ${advanced.executed.join("、")}。`);
      await refresh(advanced.workflow.workflow_id);
    });

  const doDecide = (decision: "promote" | "rollback" | "keep") =>
    guard(async () => {
      if (!selected) return;
      await decideWorkflowPromotion(selected.workflow_id, {
        decision,
        decided_by: decidedBy,
        version_id: decision === "rollback" ? rollbackTarget : undefined,
        reason: note,
      });
      const result = await advanceWorkflow(selected.workflow_id, { max_steps: 18 });
      setSelected(result.workflow);
      const outcome = result.workflow.steps.find((s) => s.step_id === "promotion_decision")?.outputs;
      setMessage(`决策已执行：${outcome?.outcome ?? "unknown"}`);
      await refresh(result.workflow.workflow_id);
    });

  const current = selected?.steps.find((s) => s.step_id === selected.current_step);
  const completed = selected?.steps.filter((s) => s.status === "completed" || s.status === "skipped").length ?? 0;
  const awaitingApproval = selected?.status === "awaiting_human" && selected.current_step === "human_approval";
  const awaitingDecision = selected?.status === "awaiting_human" && selected.current_step === "promotion_decision";
  const candidates = selected?.steps.find((s) => s.step_id === "gap_discovery")?.outputs.gaps ?? [];
  const archived = versions.filter((v) => v.status === "archived");

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Research Workflow</h2>
        <p className="text-sm text-slate-400 mt-1">
          18 步端到端流程：每一步都有真实数据输入与输出，状态逐步落盘，失败后可原地重试或回退到任意先前步骤。
        </p>
      </div>

      <Notice>
        执行是有界的：每次调用最多推进指定步数，遇到人工门禁或失败立即停止。
        Holdout 永远不会被流程自动打开，它仍是 Experiment Lab 中的一次性锁定检查。
      </Notice>
      {error && <ErrorBanner message={error} />}
      {message && (
        <div className="p-3 bg-green-900/30 border border-green-700 rounded text-sm text-green-200">
          {message}
        </div>
      )}

      <Panel title="启动新流程" subtitle="只创建状态，不自动执行；检索从第 3 步开始真实发生。">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            研究主题（必填）
            <input
              className={inputClass}
              value={topic}
              placeholder="例如：LLM agent skill library learning"
              onChange={(e) => setTopic(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            初始 query（默认同主题）
            <input className={inputClass} value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            Top-K
            <input
              className={inputClass}
              type="number"
              min={1}
              max={40}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
            />
          </label>
          <button className={buttonClass} disabled={busy || topic.trim().length < 3} onClick={doStart}>
            创建流程
          </button>
        </div>
      </Panel>

      <Panel title="流程列表" subtitle={`共 ${workflows.length} 个流程`}>
        {workflows.length === 0 ? (
          <p className="text-sm text-slate-400">暂无流程。</p>
        ) : (
          <div className="space-y-1">
            {workflows.map((w) => (
              <button
                key={w.workflow_id}
                className={`w-full text-left bg-slate-900/60 hover:bg-slate-900 rounded p-2 text-xs flex flex-wrap items-center gap-2 ${
                  selected?.workflow_id === w.workflow_id ? "ring-1 ring-blue-500" : ""
                }`}
                onClick={() =>
                  guard(async () => {
                    const detail = await getWorkflow(w.workflow_id);
                    setSelected(detail.workflow);
                    setExpanded(detail.workflow.current_step);
                  })
                }
              >
                <span className="font-mono text-slate-400">{w.workflow_id}</span>
                <span className="text-slate-200">{w.topic}</span>
                <Badge className={WORKFLOW_STYLES[w.status]}>{w.status}</Badge>
                <span className="text-slate-500">
                  {w.steps.filter((s) => s.status === "completed").length}/18 · {STEP_LABELS[w.current_step]}
                </span>
              </button>
            ))}
          </div>
        )}
      </Panel>

      {selected && (
        <>
          <Panel
            title="执行控制"
            subtitle={`当前步骤：${selected.current_step} · 已完成 ${completed}/18`}
            action={
              <Link className="text-xs text-blue-400 underline" to="/dossier">
                研究档案 →
              </Link>
            }
          >
            <div className="grid grid-cols-4 gap-2 mb-3">
              <Stat label="流程状态" value={<Badge className={WORKFLOW_STYLES[selected.status]}>{selected.status}</Badge>} />
              <Stat label="进度" value={`${Math.round((completed / 18) * 100)}%`} />
              <Stat label="文献 Run" value={<span className="font-mono text-xs">{selected.context.literature_run_id ?? "—"}</span>} />
              <Stat label="Spec" value={<span className="font-mono text-xs">{selected.context.spec_id ?? "—"}</span>} />
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <button className={buttonClass} disabled={busy || selected.status === "completed"} onClick={() => doAdvance(1)}>
                {busy ? "执行中…" : "执行下一步"}
              </button>
              <button className={ghostClass} disabled={busy || selected.status === "completed"} onClick={() => doAdvance(18)}>
                连续执行到人工门禁
              </button>
              {current?.status === "failed" && (
                <button className={ghostClass} disabled={busy} onClick={() => doAdvance(1, current.step_id)}>
                  重试失败步骤
                </button>
              )}
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                回退到步骤
                <select className={inputClass} value={rewindTo} onChange={(e) => setRewindTo(e.target.value as StepId)}>
                  <option value="">— 选择 —</option>
                  {selected.steps.map((s) => (
                    <option key={s.step_id} value={s.step_id}>{s.index}. {s.title_zh}</option>
                  ))}
                </select>
              </label>
              <button
                className={ghostClass}
                disabled={busy || !rewindTo}
                onClick={() => doAdvance(1, rewindTo as StepId)}
              >
                回退并重跑
              </button>
            </div>
            <p className="text-xs text-slate-500 mt-2">
              回退会清空该步骤及其后所有步骤的输出；若该流程已打开过 holdout，回退会被拒绝。
            </p>
          </Panel>

          {awaitingApproval && (
            <Panel title="人工确认门禁" subtitle="只有被接受的空白才会进入假设与实验设计。">
              <div className="flex flex-wrap items-end gap-3 mb-3">
                <label className="flex flex-col gap-1 text-xs text-slate-400">
                  决策人（必填）
                  <input className={inputClass} value={decidedBy} onChange={(e) => setDecidedBy(e.target.value)} />
                </label>
                <label className="flex flex-col gap-1 text-xs text-slate-400">
                  备注
                  <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} />
                </label>
              </div>
              <div className="space-y-1">
                {candidates.map((g) => (
                  <div key={g.gap_id} className="bg-slate-900/60 rounded p-2 text-xs flex flex-wrap items-center gap-2">
                    <Badge className="bg-slate-700 text-slate-200">{g.gap_type}</Badge>
                    <Badge className="bg-amber-900/50 text-amber-300">{g.confidence_label}</Badge>
                    <span className="text-slate-200 flex-1">{g.title}</span>
                    <span className="text-slate-500">支撑 {g.supporting_papers.length} 篇</span>
                    <button
                      className={buttonClass}
                      disabled={busy || !decidedBy.trim()}
                      onClick={() => doApprove(g.gap_id, "accepted")}
                    >
                      接受
                    </button>
                    <button
                      className={ghostClass}
                      disabled={busy || !decidedBy.trim()}
                      onClick={() => doApprove(g.gap_id, "rejected")}
                    >
                      拒绝
                    </button>
                  </div>
                ))}
                {candidates.length === 0 && (
                  <p className="text-xs text-slate-400">
                    本流程没有产生候选空白，无法继续；请调整主题后回退到文献检索重跑。
                  </p>
                )}
              </div>
            </Panel>
          )}

          {awaitingDecision && (
            <Panel title="晋升 / 回滚决策" subtitle="门禁由独立 Evaluator 计算；拒绝时 Active 版本保持不变。">
              {current?.outputs.promotion_gate && (
                <div className="mb-3">
                  <Badge
                    className={
                      current.outputs.promotion_gate.allowed
                        ? "bg-green-900/50 text-green-300"
                        : "bg-red-900/50 text-red-300"
                    }
                  >
                    {current.outputs.promotion_gate.allowed ? "门禁全部通过" : "门禁未通过"}
                  </Badge>
                  <ul className="text-xs text-red-200 space-y-0.5 mt-1">
                    {current.outputs.promotion_gate.reasons.map((r) => <li key={r}>· {r}</li>)}
                  </ul>
                </div>
              )}
              <div className="flex flex-wrap items-end gap-3">
                <label className="flex flex-col gap-1 text-xs text-slate-400">
                  决策人（必填）
                  <input className={inputClass} value={decidedBy} onChange={(e) => setDecidedBy(e.target.value)} />
                </label>
                <label className="flex flex-col gap-1 text-xs text-slate-400">
                  理由
                  <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} />
                </label>
                <label className="flex flex-col gap-1 text-xs text-slate-400">
                  回滚目标（archived）
                  <select className={inputClass} value={rollbackTarget} onChange={(e) => setRollbackTarget(e.target.value)}>
                    <option value="">— 无 —</option>
                    {archived.map((v) => (
                      <option key={v.version_id} value={v.version_id}>v{v.version_number} · {v.version_id}</option>
                    ))}
                  </select>
                </label>
                <button className={buttonClass} disabled={busy || !decidedBy.trim()} onClick={() => doDecide("promote")}>
                  尝试晋升候选
                </button>
                <button className={ghostClass} disabled={busy || !decidedBy.trim()} onClick={() => doDecide("keep")}>
                  保持现状
                </button>
                <button
                  className={ghostClass}
                  disabled={busy || !decidedBy.trim() || !rollbackTarget}
                  onClick={() => doDecide("rollback")}
                >
                  回滚
                </button>
              </div>
            </Panel>
          )}

          <Panel title="18 步执行轨迹" subtitle="点击任意步骤展开它的真实输入、输出与通知。">
            <div className="space-y-1">
              {selected.steps.map((s) => (
                <div key={s.step_id} className="bg-slate-900/60 rounded">
                  <button
                    className="w-full text-left p-2 flex flex-wrap items-center gap-2 text-xs"
                    onClick={() => setExpanded(expanded === s.step_id ? null : s.step_id)}
                  >
                    <span className="text-slate-500 w-6">{s.index}</span>
                    <span className="text-slate-200 w-28">{s.title_zh}</span>
                    <Badge className={STEP_STYLES[s.status]}>{s.status}</Badge>
                    {s.attempts > 1 && <span className="text-slate-500">尝试 {s.attempts} 次</span>}
                    {s.step_id === "human_approval" || s.step_id === "promotion_decision" ? (
                      <Badge className="bg-amber-900/40 text-amber-200">人工门禁</Badge>
                    ) : null}
                    <span className="text-slate-500 flex-1 truncate">{s.notice}</span>
                    <span className="text-slate-600">{expanded === s.step_id ? "收起" : "展开"}</span>
                  </button>
                  {expanded === s.step_id && (
                    <div className="px-3 pb-3">
                      <StepDetail step={s} />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}