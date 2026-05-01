"use client";

// Sits at the top of the review pane. The summary line answers the
// question every reviewer asks first: "is this OK to submit?" Per
// UX_PRINCIPLES principle 4 ("errors are explained, not announced") the
// banner explains posture rather than just declaring numbers.

import { CheckCircle2, ShieldAlert, ShieldCheck } from "lucide-react";

import type { ValidationSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

export function ValidationBanner({
  summary,
  previewing = false,
}: {
  summary: ValidationSummary;
  /**
   * Slice 91 — true while a debounced ``/validate-preview/`` round-
   * trip is in flight. We add an unobtrusive "Validating…" badge so
   * the user knows the counts they see are about to refresh, without
   * flashing the whole banner.
   */
  previewing?: boolean;
}) {
  const total = summary.errors + summary.warnings + summary.infos;
  const tone = summary.has_blocking_errors ? "error" : summary.warnings > 0 ? "warning" : "ok";

  const Icon = tone === "error" ? ShieldAlert : tone === "warning" ? ShieldCheck : CheckCircle2;

  const headline =
    tone === "error"
      ? "This invoice is not ready to submit"
      : tone === "warning"
        ? "Ready to submit — with notes to review"
        : "Looks good to submit";

  const detail = describe(summary);

  return (
    <section
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3",
        tone === "error" && "border-error/30 bg-error/5",
        tone === "warning" && "border-warning/30 bg-warning/5",
        tone === "ok" && "border-success/30 bg-success/5",
      )}
    >
      <Icon
        className={cn(
          "mt-0.5 h-5 w-5 flex-shrink-0",
          tone === "error" && "text-error",
          tone === "warning" && "text-warning",
          tone === "ok" && "text-success",
        )}
      />
      <div className="flex-1">
        <div className="flex items-center gap-2 text-base font-semibold">
          {headline}
          {previewing && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-2xs font-medium uppercase tracking-wider text-slate-500">
              Validating…
            </span>
          )}
        </div>
        <div className="mt-0.5 text-2xs text-slate-600">
          {total === 0 ? "No issues found by pre-flight validation." : detail}
        </div>
      </div>
      <div className="flex flex-col items-end gap-1 text-2xs uppercase tracking-wider">
        {summary.errors > 0 && (
          <span className="font-medium text-error">
            {summary.errors} error{summary.errors > 1 && "s"}
          </span>
        )}
        {summary.warnings > 0 && (
          <span className="font-medium text-warning">
            {summary.warnings} warning{summary.warnings > 1 && "s"}
          </span>
        )}
        {summary.infos > 0 && (
          <span className="font-medium text-info">
            {summary.infos} note{summary.infos > 1 && "s"}
          </span>
        )}
      </div>
    </section>
  );
}

function describe(summary: ValidationSummary): string {
  const parts: string[] = [];
  if (summary.errors > 0) {
    parts.push(
      summary.errors === 1
        ? "1 error must be fixed before LHDN will accept this invoice."
        : `${summary.errors} errors must be fixed before LHDN will accept this invoice.`,
    );
  }
  if (summary.warnings > 0) {
    parts.push(
      summary.warnings === 1
        ? "1 warning is worth a second look but won't block submission."
        : `${summary.warnings} warnings are worth a second look but won't block submission.`,
    );
  }
  if (summary.infos > 0) {
    parts.push(
      summary.infos === 1
        ? "1 note flags a special-case rule (e.g. RM 10K threshold)."
        : `${summary.infos} notes flag special-case rules (e.g. RM 10K threshold).`,
    );
  }
  return parts.join(" ");
}
