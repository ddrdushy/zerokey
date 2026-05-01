"use client";

// One row of the structured-fields panel.
//
// Read mode (no ``onChange`` prop): label + static value + confidence
// dot + inline IssuePills.
// Edit mode (``onChange`` provided): the value becomes a text input the
// reviewer can correct in place. Saving is the parent's responsibility —
// FieldRow just emits ``onChange(name, newValue)`` whenever the input
// changes. The visual treatment ("dirty" border, confidence band, error
// pills) keeps working in both modes.
//
// Per UX_PRINCIPLES principle 7 ("uncertainty is signaled clearly") the
// confidence dot is always visible when ``confidence`` is provided. The
// dirty marker (a small Signal-tinted dot in the corner) replaces the
// confidence dot when the field has unsaved edits, so the reviewer's
// attention shifts from "how sure are we" to "you've changed this, save".

import type { ValidationIssue } from "@/lib/api";
import { cn } from "@/lib/utils";

import { IssuePill } from "./IssuePill";

type Kind = "text" | "date" | "decimal";

type ReadProps = {
  label: string;
  value: string | null | undefined;
  confidence?: number | null;
  issues?: ValidationIssue[];
  mono?: boolean;
};

type EditProps = ReadProps & {
  name: string;
  onChange: (name: string, value: string) => void;
  dirty?: boolean;
  kind?: Kind;
};

export function FieldRow(props: ReadProps | EditProps) {
  const { label, value, confidence, issues = [], mono = false } = props;
  const isEdit = "onChange" in props;
  const dirty = isEdit ? props.dirty === true : false;
  const hasError = issues.some((i) => i.severity === "error");
  const hasWarning = issues.some((i) => i.severity === "warning");
  const isMissing = !value;

  return (
    <div
      className={cn(
        "rounded-xl border bg-white px-4 py-3 transition-colors",
        dirty
          ? "border-signal/60 ring-1 ring-signal/20"
          : hasError
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
        {dirty ? <DirtyMarker /> : confidence != null ? <ConfidenceDot value={confidence} /> : null}
      </div>

      {isEdit ? (
        <input
          name={props.name}
          type={inputType((props as EditProps).kind)}
          value={value ?? ""}
          onChange={(event) => props.onChange(props.name, event.target.value)}
          aria-label={label}
          className={cn(
            "mt-1 w-full bg-transparent text-base outline-none focus:ring-0",
            mono && "font-mono text-sm",
            isMissing && !dirty && "text-slate-400",
            // Inputs in our design system have no chrome; the field card
            // is the visual container. Override the browser default to
            // match the read mode.
            "border-0 p-0 placeholder:text-slate-400",
          )}
          placeholder={isEdit ? `Enter ${label.toLowerCase()}` : undefined}
        />
      ) : (
        <div
          className={cn(
            "mt-1 text-base",
            mono && value && "font-mono text-sm",
            isMissing && "text-slate-400",
          )}
        >
          {value || <span aria-label="missing value">—</span>}
        </div>
      )}

      {issues.length > 0 && (
        <div className="mt-2 flex flex-col gap-1.5">
          {issues.map((issue) => (
            // When the user has edited the field, the existing issues
            // are stale — show them dimmed + struck-through with a
            // "revalidates on save" hint, so the user sees their fix
            // was acknowledged. Fresh issues come back after Save.
            <IssuePill key={issue.code + issue.field_path} issue={issue} stale={dirty} />
          ))}
          {dirty && (
            <span className="text-2xs text-slate-400">
              Issues above will revalidate on save.
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function inputType(kind?: Kind): string {
  if (kind === "date") return "date";
  // Decimal inputs use plain text so the user can paste "RM 1,234.56" and
  // we parse it server-side. The HTML number input is more trouble than
  // help for currency.
  return "text";
}

function DirtyMarker() {
  return (
    <span
      title="Unsaved change"
      aria-label="Unsaved change"
      className="flex items-center gap-1.5 text-2xs text-ink"
    >
      <span className="h-2 w-2 rounded-full bg-signal" aria-hidden="true" />
      Edited
    </span>
  );
}

function ConfidenceDot({ value }: { value: number }) {
  // Three-band threshold: high >= 0.8, medium >= 0.5, low otherwise.
  // The thresholds match the vision-escalation cutoff (0.5) so a
  // reviewer's mental model lines up with the engine's behaviour.
  const tone = value >= 0.8 ? "bg-success" : value >= 0.5 ? "bg-warning" : "bg-error";
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
