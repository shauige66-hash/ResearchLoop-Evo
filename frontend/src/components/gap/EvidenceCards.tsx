import { useState } from "react";
import type { EvidenceCard } from "../../types/gapPipeline";
import { CARD_FIELDS, CARD_FIELD_LABELS } from "../../types/gapPipeline";

/** Abstract-only evidence cards: every span must exist verbatim in the abstract. */
export default function EvidenceCards({ cards }: { cards: EvidenceCard[] }) {
  const [openId, setOpenId] = useState<string | null>(null);

  if (cards.length === 0) {
    return (
      <p className="text-xs text-slate-400">
        暂无 Evidence Card。未配置 LLM 时不会生成卡片，也不会伪造。
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-500">
        evidence_source 一律为 abstract：系统只拿到摘要，不声称阅读全文。
        未通过逐字校验的字段被丢弃并记录在 rejected_fields。
      </p>
      {cards.map((card) => {
        const open = openId === card.paper_id;
        return (
          <div key={card.paper_id} className="bg-slate-900/60 rounded p-2 text-xs">
            <button
              onClick={() => setOpenId(open ? null : card.paper_id)}
              className="w-full text-left flex flex-wrap gap-2 items-center"
            >
              <span className="text-blue-400">{card.title || card.paper_id}</span>
              <span className="text-slate-500">{card.paper_id}</span>
              <span className="text-emerald-400">{card.grounded_fields.length} grounded</span>
              {card.rejected_fields.length > 0 && (
                <span className="text-red-400">{card.rejected_fields.length} rejected</span>
              )}
              {card.from_cache && <span className="text-slate-500">cache hit（未重复付费）</span>}
              <span className="ml-auto text-slate-500">{open ? "收起" : "展开"}</span>
            </button>
            {open && (
              <div className="mt-2 space-y-1 border-t border-slate-700 pt-2">
                <div className="text-slate-500">
                  prompt_version={card.prompt_version} · extraction_method={card.extraction_method}
                  {card.doi ? ` · doi:${card.doi}` : ""}
                </div>
                {CARD_FIELDS.map((name) => {
                  const field = card[name];
                  const filled = Boolean(field.claim && field.evidence_span);
                  return (
                    <div key={name} className="bg-slate-800/70 rounded p-2">
                      <div className="flex flex-wrap gap-2 items-center">
                        <strong className="text-slate-300">{CARD_FIELD_LABELS[name]}</strong>
                        <span className="text-slate-500">{name}</span>
                        {filled ? (
                          <span className="text-emerald-400">
                            grounded · {field.evidence_source} · {field.confidence}
                          </span>
                        ) : (
                          <span className="text-slate-500">unknown（不猜测）</span>
                        )}
                      </div>
                      {filled && (
                        <>
                          <div className="text-slate-300 mt-1">{field.claim}</div>
                          <blockquote className="border-l-2 border-blue-700 pl-2 text-slate-400 italic mt-1">
                            “{field.evidence_span}”
                          </blockquote>
                        </>
                      )}
                    </div>
                  );
                })}
                {card.rejected_fields.length > 0 && (
                  <div className="text-red-300 bg-red-900/20 border border-red-800 rounded p-2 space-y-1">
                    <strong>被拒绝的字段（原文中找不到该 span）:</strong>
                    {card.rejected_fields.map((rejected, i) => (
                      <div key={i}>
                        {rejected.field}: {rejected.reason || rejected.evidence_span || "—"}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}