import { useState } from "react";
import {
  addBenchmarkReferences,
  assignSplits,
  confirmBenchmarkReferences,
  createBenchmarkCase,
} from "../../api/client";
import type { BenchmarkCase, BenchmarkListResponse } from "../../types/experiment";
import { SPLIT_LABELS } from "../../types/experiment";
import {
  Badge,
  ErrorBanner,
  Notice,
  Panel,
  REFERENCE_STYLES,
  SPLIT_STYLES,
  Stat,
  buttonClass,
  ghostClass,
  inputClass,
  referenceStatusOf,
} from "./common";

function splitDois(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map((d) => d.trim())
    .filter(Boolean);
}

function CaseCard({
  caseItem,
  onChanged,
}: {
  caseItem: BenchmarkCase;
  onChanged: () => void;
}) {
  const [newDois, setNewDois] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verificationErrors, setVerificationErrors] = useState<{ doi: string; detail: string }[]>([]);
  const status = referenceStatusOf(caseItem.references);

  async function act(fn: () => Promise<{ verification_errors?: { doi: string; detail: string }[] }>) {
    setBusy(true);
    setError(null);
    try {
      const result = await fn();
      setVerificationErrors(result.verification_errors || []);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-3 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{caseItem.topic}</span>
        <Badge className={SPLIT_STYLES[caseItem.split]}>{SPLIT_LABELS[caseItem.split]}</Badge>
        <Badge className={REFERENCE_STYLES[status]}>
          {status === "confirmed" ? "参考集已人工确认" : "awaiting_reference_set"}
        </Badge>
        <span className="text-xs text-slate-500">{caseItem.case_id}</span>
      </div>
      <div className="text-sm text-slate-400">
        检索问题：<span className="text-slate-200">{caseItem.query}</span>
      </div>
      {caseItem.notes && <div className="text-xs text-slate-500">{caseItem.notes}</div>}

      <div className="space-y-1">
        {caseItem.references.length === 0 && (
          <div className="text-xs text-slate-500">
            尚无参考 DOI。没有人工确认的参考集时，只报告真实成本指标，不计算覆盖率。
          </div>
        )}
        {caseItem.references.map((ref) => (
          <div key={ref.doi} className="text-xs bg-slate-800/70 rounded p-2">
            <div className="flex flex-wrap items-center gap-2">
              <a
                href={`https://doi.org/${ref.doi}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-400 hover:underline font-mono"
              >
                {ref.doi}
              </a>
              <Badge className="bg-slate-700 text-slate-300">核验：{ref.verified_via}</Badge>
              {ref.confirmed_by ? (
                <Badge className="bg-green-900/50 text-green-300">
                  确认人：{ref.confirmed_by}
                </Badge>
              ) : (
                <Badge className="bg-amber-900/50 text-amber-300">未确认</Badge>
              )}
            </div>
            {ref.title && <div className="text-slate-400 mt-1">{ref.title}</div>}
          </div>
        ))}
      </div>

      {verificationErrors.length > 0 && (
        <div className="text-xs text-red-300 space-y-1">
          {verificationErrors.map((e) => (
            <div key={e.doi}>
              DOI 核验失败 {e.doi}：{e.detail}
            </div>
          ))}
        </div>
      )}
      {error && <ErrorBanner message={error} />}

      <div className="flex flex-wrap gap-2 items-center">
        <input
          value={newDois}
          onChange={(e) => setNewDois(e.target.value)}
          placeholder="追加真实 DOI（逗号或换行分隔）"
          className={`${inputClass} flex-1 min-w-52`}
        />
        <button
          disabled={busy || splitDois(newDois).length === 0}
          onClick={() =>
            act(async () => {
              const result = await addBenchmarkReferences(caseItem.case_id, splitDois(newDois));
              setNewDois("");
              return result;
            })
          }
          className={ghostClass}
        >
          核验并追加
        </button>
      </div>
      <div className="flex flex-wrap gap-2 items-center">
        <input
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
          placeholder="确认人姓名（人工承担参考集责任）"
          className={`${inputClass} flex-1 min-w-52`}
        />
        <button
          disabled={busy || !reviewer.trim() || caseItem.references.length === 0}
          onClick={() =>
            act(async () => {
              const result = await confirmBenchmarkReferences(
                caseItem.case_id,
                reviewer.trim()
              );
              setReviewer("");
              return result;
            })
          }
          className={buttonClass}
        >
          确认全部已核验参考
        </button>
      </div>
    </div>
  );
}

export default function BenchmarkPanel({
  listing,
  onChanged,
}: {
  listing: BenchmarkListResponse | null;
  onChanged: () => void;
}) {
  const [topic, setTopic] = useState("");
  const [query, setQuery] = useState("");
  const [dois, setDois] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ doi: string; detail: string }[]>([]);

  async function createCase() {
    setBusy(true);
    setError(null);
    try {
      const result = await createBenchmarkCase({
        topic: topic.trim(),
        query: query.trim(),
        reference_dois: splitDois(dois),
        notes: notes.trim(),
        verify_references: true,
      });
      setCreated(result.verification_errors);
      setTopic("");
      setQuery("");
      setDois("");
      setNotes("");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function reassign() {
    setBusy(true);
    setError(null);
    try {
      await assignSplits();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "划分失败");
    } finally {
      setBusy(false);
    }
  }

  const cases = listing?.cases || [];

  return (
    <Panel
      title="Benchmark 数据集"
      subtitle="参考 DOI 必须真实存在（Crossref / OpenAlex 核验），并由人工确认后才成为 Ground Truth。"
      action={
        <button onClick={reassign} disabled={busy || cases.length === 0} className={ghostClass}>
          按主题重新划分 split
        </button>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <Stat label="案例总数" value={listing?.total ?? 0} />
          <Stat label="已确认参考集" value={listing?.confirmed_cases ?? 0} />
          <Stat label="等待确认" value={listing?.awaiting_cases ?? 0} />
          <Stat
            label="Split 分布"
            value={
              <span className="text-sm">
                {Object.entries(listing?.split_counts || {})
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(" / ") || "—"}
              </span>
            }
          />
        </div>

        <Notice>{listing?.notice || "同一主题的全部案例必须落在同一 split，避免验证集泄漏。"}</Notice>
        {error && <ErrorBanner message={error} />}
        {created.length > 0 && (
          <div className="text-xs text-red-300 space-y-1">
            {created.map((e) => (
              <div key={e.doi}>
                DOI 核验失败 {e.doi}：{e.detail}
              </div>
            ))}
          </div>
        )}

        <div className="bg-slate-900/50 border border-slate-700 rounded p-3 space-y-2">
          <div className="text-sm font-medium">新增 Benchmark 案例</div>
          <div className="grid md:grid-cols-2 gap-2">
            <input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="研究主题（英文，用于分组划分 split）"
              className={inputClass}
            />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Baseline 使用的原始检索问题"
              className={inputClass}
            />
          </div>
          <textarea
            value={dois}
            onChange={(e) => setDois(e.target.value)}
            placeholder="参考 DOI（可留空，稍后追加）。每行一个或逗号分隔。"
            rows={2}
            className={`${inputClass} w-full font-mono`}
          />
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="备注：参考集来源与选择依据"
            className={`${inputClass} w-full`}
          />
          <button
            onClick={createCase}
            disabled={busy || topic.trim().length < 3 || query.trim().length < 3}
            className={buttonClass}
          >
            {busy ? "处理中..." : "创建案例（真实 DOI 核验）"}
          </button>
        </div>

        <div className="space-y-2">
          {cases.length === 0 && (
            <div className="text-sm text-slate-500 py-4 text-center">
              还没有 Benchmark 案例。请先创建案例并核验真实 DOI。
            </div>
          )}
          {cases.map((c) => (
            <CaseCard key={c.case_id} caseItem={c} onChanged={onChanged} />
          ))}
        </div>
      </div>
    </Panel>
  );
}