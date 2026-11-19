import type { ReactNode } from "react";
import type { ResearchGap, RiskLabel } from "../../types/gap";
import { COUNTER_STATUS_LABELS, RISK_STYLES } from "../../types/gap";
import { CRITIC_SCORE_LABELS } from "../../types/gapPipeline";

const CHECK_LABELS: Record<string, string> = {
  supporting_papers_exist: "支持论文真实存在",
  min_supporting_papers: "支持论文数量达标",
  no_duplicate_paper_counting: "无重复计数（id / DOI）",
  evidence_spans_verbatim: "证据逐字命中原文",
  evidence_subset_of_supporting_papers: "证据属于支持论文",
  doi_present_and_wellformed: "DOI 格式可核验",
  counter_search_targets_the_claim: "反证检索针对该论点",
  counter_search_completed: "反证检索已完成",
  prior_art_collisions: "prior art 冲突数",
  novelty_risk_within_gate: "新颖性风险在门禁内",
  contradiction_risk_within_gate: "矛盾风险在门禁内",
  claim_is_specific: "论点足够具体",
  critic_evidence_grounding: "评审：证据扎实度",
  critic_cross_paper_support: "评审：跨论文支持",
  critic_specificity: "评审：具体性",
  critic_testability: "评审：可验证性",
  critic_does_not_reject: "评审未否决",
  critic_available: "评审已产出",
};

function Badge({ className, children }: { className: string; children: ReactNode }) {
  return (
    <span className={`px-2 py-0.5 rounded border text-xs font-medium ${className}`}>
      {children}
    </span>
  );
}

function RiskBadge({ label, prefix }: { label: string; prefix: string }) {
  const style = RISK_STYLES[(label as RiskLabel) || "MEDIUM"] || RISK_STYLES.MEDIUM;
  return (
    <Badge className={style}>
      {prefix}: {label || "—"}
    </Badge>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h4 className="text-sm font-semibold mb-2">{title}</h4>
      {children}
    </section>
  );
}

function List({ items }: { items: string[] }) {
  if (items.length === 0) return <span className="text-slate-500">—</span>;
  return (
    <ul className="list-disc pl-4 space-y-0.5">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

/** The full chain: LLM proposal → independent critic → Python checks → gate. */
export default function EvidenceChain({ gap }: { gap: ResearchGap }) {
  const candidate = gap.candidate || {};
  const critique = gap.critique || {};
  const validation = gap.validation || {};
  const gate = gap.gate || {};
  const checks = validation.checks || [];
  const hasChain =
    gap.discovery_mode === "llm_pipeline" || checks.length > 0 || Boolean(candidate.gap_claim);

  if (!hasChain) {
    return (
      <p className="text-xs text-slate-400 bg-slate-900/60 rounded p-2">
        该候选由确定性规则比较产生（discovery_mode=rule_based），没有 LLM 提出、评审或门禁记录。
        支持证据与反证检索结果仍按原文摘录展示。
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <Section title="① LLM 提出的候选（假设，不是结论）">
        <div className="text-xs bg-slate-900/60 rounded p-2 space-y-1">
          <div className="text-slate-200">{candidate.gap_claim || gap.description}</div>
          {candidate.unresolved_boundary && (
            <div className="text-slate-400">
              <strong className="text-slate-300">未解边界:</strong> {candidate.unresolved_boundary}
            </div>
          )}
          {candidate.already_solved && (
            <div className="text-slate-400">
              <strong className="text-slate-300">已被解决的部分:</strong> {candidate.already_solved}
            </div>
          )}
          {candidate.candidate_research_question && (
            <div className="text-slate-400">
              <strong className="text-slate-300">候选研究问题:</strong>{" "}
              {candidate.candidate_research_question}
            </div>
          )}
          {candidate.minimum_experiment && (
            <div className="text-slate-400">
              <strong className="text-slate-300">最小实验:</strong> {candidate.minimum_experiment}
            </div>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            <Badge className="bg-slate-700 text-slate-200 border-slate-600">
              proposer gap_type: {candidate.gap_type || "—"}
            </Badge>
            <RiskBadge label={candidate.novelty_risk || ""} prefix="提出者自评 novelty_risk" />
            <Badge className="bg-slate-700 text-slate-200 border-slate-600">
              discovery_mode: {gap.discovery_mode}
            </Badge>
            {gap.pipeline_id && (
              <span className="text-slate-500">pipeline: {gap.pipeline_id}</span>
            )}
          </div>
          {candidate.novelty_rationale && (
            <div className="text-slate-400">
              <strong className="text-slate-300">提出者自评依据:</strong>{" "}
              {candidate.novelty_rationale}
            </div>
          )}
          {(candidate.uncertainties || []).length > 0 && (
            <div className="text-slate-400">
              <strong className="text-slate-300">提出者声明的不确定性:</strong>
              <List items={candidate.uncertainties || []} />
            </div>
          )}
        </div>
      </Section>

      <Section title="② Gap Critic / Judge（0~5 整数分，看不到提出者的内部推理）">
        {Object.keys(critique).length === 0 ? (
          <p className="text-xs text-amber-300 bg-amber-900/20 border border-amber-800 rounded p-2">
            评审未产出：LLM 未配置、预算耗尽或该阶段失败。系统不会用假分数替代。
          </p>
        ) : (
          <div className="text-xs bg-slate-900/60 rounded p-2 space-y-2">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {CRITIC_SCORE_LABELS.map(([key, label]) => {
                const value = critique[key];
                const score = typeof value === "number" ? value : null;
                return (
                  <div key={key} className="bg-slate-800/70 rounded p-2">
                    <div className="text-slate-400">{label}</div>
                    <div className="text-lg text-slate-100">
                      {score === null ? "—" : `${score} / 5`}
                    </div>
                    <div className="h-1 bg-slate-700 rounded mt-1">
                      <div
                        className="h-1 bg-blue-500 rounded"
                        style={{ width: `${((score ?? 0) / 5) * 100}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="flex flex-wrap gap-2">
              <RiskBadge label={critique.novelty_risk || ""} prefix="评审 novelty_risk" />
              <RiskBadge
                label={critique.contradiction_risk || ""}
                prefix="评审 contradiction_risk"
              />
              <Badge className="bg-slate-700 text-slate-200 border-slate-600">
                recommended_action: {critique.recommended_action || "—"}
              </Badge>
              {critique.from_cache && (
                <Badge className="bg-slate-700 text-slate-400 border-slate-600">cache hit</Badge>
              )}
            </div>
            {critique.rationale && <div className="text-slate-300">{critique.rationale}</div>}
            <div className="text-slate-400">
              <strong className="text-slate-300">主要弱点:</strong>
              <List items={critique.major_weaknesses || []} />
            </div>
            <div className="text-slate-400">
              <strong className="text-slate-300">缺失证据:</strong>
              <List items={critique.missing_evidence || []} />
            </div>
          </div>
        )}
      </Section>

      <Section title="③ Python 独立验证（不依赖任何 LLM 意见）">
        {checks.length === 0 ? (
          <p className="text-xs text-slate-400 bg-slate-900/60 rounded p-2">
            验证未运行；没有 Python 检查结果时门禁不会给出 accepted。
          </p>
        ) : (
          <div className="space-y-2">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
              <div className="bg-slate-900/60 rounded p-2">
                <div className="text-slate-400">唯一支持论文</div>
                <div className="text-lg text-slate-100">
                  {validation.unique_supporting_papers ?? 0}
                </div>
              </div>
              <div className="bg-slate-900/60 rounded p-2">
                <div className="text-slate-400">唯一反证论文</div>
                <div className="text-lg text-slate-100">{validation.unique_counter_papers ?? 0}</div>
              </div>
              <div className="bg-slate-900/60 rounded p-2">
                <div className="text-slate-400">有效 / 无效证据引用</div>
                <div className="text-lg text-slate-100">
                  {validation.valid_evidence_refs ?? 0} /{" "}
                  {(validation.invalid_evidence_refs || []).length}
                </div>
              </div>
              <div className="bg-slate-900/60 rounded p-2">
                <div className="text-slate-400">prior art 冲突</div>
                <div className="text-lg text-slate-100">{validation.prior_art_collisions ?? 0}</div>
              </div>
            </div>
            <div className="bg-slate-900/60 rounded p-2 text-xs space-y-1 max-h-72 overflow-auto">
              {checks.map((check) => (
                <div key={check.name} className="flex gap-2 items-start">
                  <span
                    className={
                      check.passed ? "text-emerald-400" : "text-red-400"
                    }
                  >
                    {check.passed ? "PASS" : "FAIL"}
                  </span>
                  <span className="text-slate-300 min-w-[180px]">
                    {CHECK_LABELS[check.name] || check.name}
                  </span>
                  <span className="text-slate-500">{check.detail}</span>
                </div>
              ))}
            </div>
            {(validation.unverified_dois || []).length > 0 && (
              <div className="text-xs text-slate-400">
                未外部解析的 DOI: {validation.unverified_dois?.join(", ")}
              </div>
            )}
            {(validation.reasons || []).length > 0 && (
              <div className="text-xs text-amber-300">
                <List items={validation.reasons || []} />
              </div>
            )}
          </div>
        )}
      </Section>

      <Section title="④ 反证检索状态与 prior art">
        <div className="text-xs bg-slate-900/60 rounded p-2 space-y-2">
          <div className="flex flex-wrap gap-2 items-center">
            <Badge
              className={
                gap.counter_status === "COUNTER_SEARCH_FAILED"
                  ? "bg-red-900/40 text-red-300 border-red-700"
                  : gap.counter_status === "COUNTER_EVIDENCE_FOUND"
                    ? "bg-amber-900/40 text-amber-300 border-amber-700"
                    : "bg-slate-700/60 text-slate-300 border-slate-600"
              }
            >
              {COUNTER_STATUS_LABELS[gap.counter_status] || gap.counter_status}
            </Badge>
            {gap.novelty_risk && (
              <RiskBadge label={gap.novelty_risk} prefix="Python 判定 novelty_risk" />
            )}
          </div>
          {gap.counter_status === "COUNTER_SEARCH_FAILED" && (
            <p className="text-red-300">
              检索失败不等于没有反证；该候选不会因此被当作"已确认无 prior art"。
            </p>
          )}
          {(gap.prior_art || []).length > 0 && (
            <div className="space-y-1">
              <strong className="text-slate-300">potential_prior_art:</strong>
              {gap.prior_art.map((art) => (
                <div key={art.paper_id} className="bg-slate-800/70 rounded p-2">
                  <a
                    href={art.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-400 hover:text-blue-300 hover:underline"
                  >
                    {art.title}
                  </a>
                  <span className="text-slate-500 ml-1">
                    {art.source} · {art.publication_year ?? "n.d."}
                    {art.doi ? ` · doi:${art.doi}` : ""}
                  </span>
                  {art.evidence_span && (
                    <blockquote className="border-l-2 border-amber-700 pl-2 text-slate-300 italic my-1">
                      “{art.evidence_span}”
                    </blockquote>
                  )}
                  <div className="text-slate-500">{art.why_relevant}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Section>

      <Section title="⑤ 系统门禁判定（不是创新性的数学证明）">
        {Object.keys(gate).length === 0 ? (
          <p className="text-xs text-slate-400 bg-slate-900/60 rounded p-2">门禁未运行。</p>
        ) : (
          <div className="text-xs bg-slate-900/60 rounded p-2 space-y-1">
            <div className="flex flex-wrap gap-2">
              <Badge className="bg-slate-700 text-slate-200 border-slate-600">
                gate status: {gate.status || "—"}
              </Badge>
              <Badge className="bg-slate-700 text-slate-200 border-slate-600">
                python_passed: {String(gate.python_passed ?? false)}
              </Badge>
              <Badge className="bg-slate-700 text-slate-200 border-slate-600">
                critic_rejected: {String(gate.critic_rejected ?? false)}
              </Badge>
            </div>
            {(gate.reasons || []).length > 0 && (
              <div className="text-slate-400">
                <List items={gate.reasons || []} />
              </div>
            )}
            {gate.notice && <div className="text-amber-300">{gate.notice}</div>}
            {gate.thresholds && Object.keys(gate.thresholds).length > 0 && (
              <div className="text-slate-500">
                阈值 / thresholds:{" "}
                {Object.entries(gate.thresholds)
                  .map(([key, value]) => `${key}=${String(value)}`)
                  .join(" · ")}
              </div>
            )}
          </div>
        )}
      </Section>
    </div>
  );
}