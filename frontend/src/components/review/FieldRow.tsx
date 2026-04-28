"use client";

// One row of the structured-fields panel. The visual hierarchy answers
// three questions in this order:
//
//   1. What field is this?            (label)
//   2. What value did we extract?     (value)
//   3. How sure are we / what's wrong?(confidence dot + inline issue pills)
//
// Per UX_PRINCIPLES principle 7 ("uncertainty is signaled clearly") the
// confidence dot is always visible when we have a per-field score. We
// don't hide low confidence behind a tooltip — the reviewer needs to see
// at a glance which fields warrant a second look.

import type { ValidationIssue } from "@/lib/api";
import { cn } from "@/lib/utils";

import { IssuePill } from "./IssuePill";

type Props = {
  label: string;
  value: string | null | undefined;
  confidence?: number | null;
  issues?: ValidationIssue[];
  // Mono font for numeric / TIN fields. The default is the body font.
  mono?: boolean;
};

export function FieldRow({ label, value, confidence, issues = [], mono = false }: Props) {
  const hasError = issues.some((i) => i.severity === "error");
  const hasWarning = issues.some((i) => i.severity === "warning");
  const isMissing = !value;

  return (
    <div
      className={cn(
        "rounded-xl border bg-white px-4 py-3 transition-colors",
        hasError
          ? "border-error/40 ring-1 ring-error/10"
          : hasWarning
            ? "border-warning/40"
            : "border-slate-100",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-2xs font-medium uppercase tracking-wider text-slate-400">
          {label}
        </span>
        {confidence != null && <ConfidenceDot value={confidence} />}
      </div>
      <div
        className={cn(
          "mt-1 text-base",
          mono && value && "font-mono text-sm",
          isMissing && "text-slate-400",
        )}
      >
        {value || <span aria-label="missing value">—</span>}
      </div>
      {issues.length > 0 && (
        <div className="mt-2 flex flex-col gap-1.5">
          {issues.map((issue) => (
            <IssuePill key={issue.code + issue.field_path} issue={issue} />
          ))}
        </div>
      )}
    </div>
  );
}

function ConfidenceDot({ value }: { value: number }) {
  // Three-band threshold: high >= 0.8, medium >= 0.5, low otherwise.
  // The thresholds match the vision-escalation cutoff (0.5) so a
  // reviewer's mental model lines up with the engine's behaviour.
  const tone =
    value >= 0.8 ? "bg-success" : value >= 0.5 ? "bg-warning" : "bg-error";
  const pct = Math.round(value * 100);
  return (
    <span
      title={`Extraction confidence: ${pct}%`}
      className="flex items-center gap-1.5 text-2xs text-slate-400"
    >
      <span className={cn("h-2 w-2 rounded-full", tone)} aria-hidden="true" />
      {pct}%
    </span>
  );
}
