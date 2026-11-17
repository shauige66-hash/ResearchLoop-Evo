import type { ReactNode } from "react";
import type { ReferenceStatus, RunStatus, SkillStatus, Split } from "../../types/experiment";

export const SPLIT_STYLES: Record<Split, string> = {
  development: "bg-blue-900/50 text-blue-300",
  validation: "bg-purple-900/50 text-purple-300",
  holdout: "bg-rose-900/50 text-rose-300",
};

export const SKILL_STYLES: Record<SkillStatus, string> = {
  active: "bg-green-900/50 text-green-300",
  candidate: "bg-amber-900/50 text-amber-300",
  archived: "bg-slate-700 text-slate-300",
  rejected: "bg-red-900/50 text-red-300",
};

export const RUN_STYLES: Record<RunStatus, string> = {
  pending: "bg-slate-700 text-slate-300",
  running: "bg-blue-900/50 text-blue-300",
  completed: "bg-green-900/50 text-green-300",
  failed: "bg-red-900/50 text-red-300",
  awaiting_reference_set: "bg-amber-900/50 text-amber-300",
};

export const REFERENCE_STYLES: Record<ReferenceStatus, string> = {
  confirmed: "bg-green-900/50 text-green-300",
  awaiting_reference_set: "bg-amber-900/50 text-amber-300",
};

export function Badge({ className, children }: { className: string; children: ReactNode }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded whitespace-nowrap ${className}`}>{children}</span>
  );
}

export function Panel({
  title,
  subtitle,
  children,
  action,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <div className="flex items-start justify-between gap-4 mb-3">
        <div>
          <h3 className="text-lg font-semibold">{title}</h3>
          {subtitle && <p className="text-xs text-slate-400 mt-1">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="p-3 bg-red-900/30 border border-red-700 rounded text-sm text-red-300 break-words whitespace-pre-line">
      {message}
    </div>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="p-3 bg-amber-900/20 border border-amber-700 rounded text-sm text-amber-200">
      {children}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="bg-slate-900/60 rounded p-2">
      <div className="text-xs text-slate-400">{label}</div>
      <div className="text-lg font-semibold text-slate-100">{value}</div>
      {hint && <div className="text-xs text-slate-500 mt-0.5">{hint}</div>}
    </div>
  );
}

export const inputClass =
  "px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white placeholder-slate-400 text-sm";
export const buttonClass =
  "px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 disabled:cursor-not-allowed rounded text-sm transition";
export const ghostClass =
  "px-3 py-1.5 bg-slate-600 hover:bg-slate-500 disabled:bg-slate-700 disabled:cursor-not-allowed rounded text-sm transition";

export function coverageText(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

export function referenceStatusOf(refs: { confirmed_by: string | null }[]): ReferenceStatus {
  return refs.some((r) => r.confirmed_by) ? "confirmed" : "awaiting_reference_set";
}