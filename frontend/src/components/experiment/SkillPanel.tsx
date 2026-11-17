import { useState } from "react";
import { createSkillVersion, previewSkillQueries } from "../../api/client";
import type { BenchmarkCase, SearchStrategy, SkillVersion } from "../../types/experiment";
import {
  Badge,
  ErrorBanner,
  Panel,
  SKILL_STYLES,
  buttonClass,
  ghostClass,
  inputClass,
} from "./common";

const EXPANSION_RULES = [
  { key: "topic_terms", label: "主题词拆分" },
  { key: "query_terms", label: "问题词拆分" },
  { key: "domain_synonyms", label: "领域同义词扩展" },
] as const;

type RuleKey = (typeof EXPANSION_RULES)[number]["key"];

function parseSynonyms(text: string): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const line of text.split("\n")) {
    const [term, rest] = line.split(":");
    if (!term || !rest) continue;
    const synonyms = rest
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (synonyms.length) out[term.trim().toLowerCase()] = synonyms;
  }
  return out;
}

export default function SkillPanel({
  versions,
  evolvable,
  immutable,
  cases,
  onChanged,
}: {
  versions: SkillVersion[];
  evolvable: string[];
  immutable: string[];
  cases: BenchmarkCase[];
  onChanged: () => void;
}) {
  const active = versions.find((v) => v.status === "active");
  const [description, setDescription] = useState("");
  const [templates, setTemplates] = useState("{query}");
  const [rules, setRules] = useState<RuleKey[]>(["domain_synonyms"]);
  const [synonyms, setSynonyms] = useState("memory: episodic memory, long-term memory");
  const [maxKeywords, setMaxKeywords] = useState(2);
  const [parent, setParent] = useState("");
  const [trials, setTrials] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [previewVersion, setPreviewVersion] = useState("");
  const [previewCase, setPreviewCase] = useState("");
  const [preview, setPreview] = useState<string[] | null>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const strategy: SearchStrategy = {
        query_templates: templates
          .split("\n")
          .map((t) => t.trim())
          .filter(Boolean),
        domain_synonyms: rules.includes("domain_synonyms") ? parseSynonyms(synonyms) : {},
        keyword_expansion_rules: rules,
        source_priority: ["openalex", "crossref", "arxiv"],
        search_filters: {
          year_from: null,
          year_to: null,
          document_types: [],
          prefer_reviews: false,
        },
        retrieval_budget: { top_k: 20, max_keywords: maxKeywords, max_api_requests: 6 },
      };
      await createSkillVersion({
        strategy,
        mutation_description: description.trim(),
        source_trials: trials
          .split(/[\s,]+/)
          .map((t) => t.trim())
          .filter(Boolean),
        parent_version: parent || active?.version_id || null,
      });
      setDescription("");
      setTrials("");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建候选版本失败");
    } finally {
      setBusy(false);
    }
  }

  async function runPreview() {
    const target = cases.find((c) => c.case_id === previewCase) || cases[0];
    const versionId = previewVersion || active?.version_id;
    if (!target || !versionId) return;
    setBusy(true);
    setError(null);
    try {
      const result = await previewSkillQueries({
        version_id: versionId,
        topic: target.topic,
        query: target.query,
      });
      setPreview(result.queries);
    } catch (err) {
      setError(err instanceof Error ? err.message : "预览失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="Skill 版本（literature_search_strategy）"
      subtitle="版本不可覆盖。创建候选版本不会自动激活；晋升必须通过独立评测门。"
    >
      <div className="space-y-4">
        <div className="grid md:grid-cols-2 gap-2 text-xs">
          <div className="bg-slate-900/50 rounded p-2">
            <div className="text-slate-400 mb-1">可进化组件</div>
            <div className="text-slate-200">{evolvable.join(", ") || "—"}</div>
          </div>
          <div className="bg-slate-900/50 rounded p-2">
            <div className="text-slate-400 mb-1">候选不可修改</div>
            <div className="text-slate-200">{immutable.join(", ") || "—"}</div>
          </div>
        </div>

        <div className="space-y-2">
          {versions.map((v) => (
            <div key={v.version_id} className="bg-slate-900/50 border border-slate-700 rounded p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">v{v.version_number}</span>
                <Badge className={SKILL_STYLES[v.status]}>{v.status}</Badge>
                <Badge className="bg-slate-700 text-slate-300">{v.created_by}</Badge>
                <span className="text-xs text-slate-500 font-mono">{v.version_id}</span>
                {v.parent_version && (
                  <span className="text-xs text-slate-500">
                    parent: {versions.find((p) => p.version_id === v.parent_version)?.version_number ?? v.parent_version}
                  </span>
                )}
              </div>
              <div className="text-sm text-slate-300 mt-1">{v.mutation_description}</div>
              <div className="text-xs text-slate-400 mt-1 font-mono break-words">
                templates={JSON.stringify(v.strategy.query_templates)} · rules=
                {JSON.stringify(v.strategy.keyword_expansion_rules)} · max_keywords=
                {v.strategy.retrieval_budget.max_keywords}
              </div>
              {Object.keys(v.strategy.domain_synonyms).length > 0 && (
                <div className="text-xs text-slate-400 mt-1 font-mono break-words">
                  synonyms={JSON.stringify(v.strategy.domain_synonyms)}
                </div>
              )}
              {v.source_trials.length > 0 && (
                <div className="text-xs text-slate-500 mt-1">
                  来源试验：{v.source_trials.join(", ")}
                </div>
              )}
            </div>
          ))}
        </div>

        {error && <ErrorBanner message={error} />}

        <div className="bg-slate-900/50 border border-slate-700 rounded p-3 space-y-2">
          <div className="text-sm font-medium">新建候选版本（人工变异）</div>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="变异说明：为什么这样改，依据哪些失败轨迹"
            rows={2}
            className={`${inputClass} w-full`}
          />
          <div className="grid md:grid-cols-2 gap-2">
            <textarea
              value={templates}
              onChange={(e) => setTemplates(e.target.value)}
              placeholder="查询模板，每行一个，仅支持 {query} 与 {topic}"
              rows={2}
              className={`${inputClass} w-full font-mono`}
            />
            <textarea
              value={synonyms}
              onChange={(e) => setSynonyms(e.target.value)}
              placeholder="领域同义词，每行 term: synonym1, synonym2"
              rows={2}
              className={`${inputClass} w-full font-mono`}
            />
          </div>
          <div className="flex flex-wrap gap-3 items-center text-sm">
            {EXPANSION_RULES.map((rule) => (
              <label key={rule.key} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={rules.includes(rule.key)}
                  onChange={(e) =>
                    setRules((prev) =>
                      e.target.checked ? [...prev, rule.key] : prev.filter((r) => r !== rule.key)
                    )
                  }
                />
                {rule.label}
              </label>
            ))}
            <label className="flex items-center gap-1.5">
              max_keywords
              <input
                type="number"
                min={1}
                max={6}
                value={maxKeywords}
                onChange={(e) => setMaxKeywords(Number(e.target.value))}
                className={`${inputClass} w-20`}
              />
            </label>
          </div>
          <div className="grid md:grid-cols-2 gap-2">
            <select value={parent} onChange={(e) => setParent(e.target.value)} className={inputClass}>
              <option value="">父版本：当前 Active（{active ? `v${active.version_number}` : "无"}）</option>
              {versions.map((v) => (
                <option key={v.version_id} value={v.version_id}>
                  v{v.version_number} · {v.status}
                </option>
              ))}
            </select>
            <input
              value={trials}
              onChange={(e) => setTrials(e.target.value)}
              placeholder="来源试验 run_id（逗号分隔，可留空）"
              className={inputClass}
            />
          </div>
          <div className="text-xs text-slate-500">
            top_k 与 API 请求上限由冻结的 ExperimentSpec 决定，候选策略无法放宽。
          </div>
          <button
            onClick={create}
            disabled={busy || description.trim().length < 3}
            className={buttonClass}
          >
            {busy ? "处理中..." : "创建候选版本"}
          </button>
        </div>

        <div className="bg-slate-900/50 border border-slate-700 rounded p-3 space-y-2">
          <div className="text-sm font-medium">查询计划预览（确定性，不联网）</div>
          <div className="grid md:grid-cols-2 gap-2">
            <select
              value={previewVersion}
              onChange={(e) => setPreviewVersion(e.target.value)}
              className={inputClass}
            >
              <option value="">版本：当前 Active</option>
              {versions.map((v) => (
                <option key={v.version_id} value={v.version_id}>
                  v{v.version_number} · {v.status}
                </option>
              ))}
            </select>
            <select
              value={previewCase}
              onChange={(e) => setPreviewCase(e.target.value)}
              className={inputClass}
            >
              <option value="">案例：第一个</option>
              {cases.map((c) => (
                <option key={c.case_id} value={c.case_id}>
                  {c.topic}
                </option>
              ))}
            </select>
          </div>
          <button onClick={runPreview} disabled={busy || cases.length === 0} className={ghostClass}>
            生成查询计划
          </button>
          {preview && (
            <ol className="text-xs font-mono text-slate-300 space-y-1 list-decimal list-inside">
              {preview.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </Panel>
  );
}