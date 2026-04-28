"use client";

// Per-issue badge. Used in two places: inline next to a field on the
// review pane, and inside the line-items table cells. Tone derives from
// severity per the brand spec — error/warning/info map to the
// existing semantic tokens, so a future theme change updates everything.

import { AlertCircle, AlertTriangle, Info } from "lucide-react";

import type { ValidationIssue } from "@/lib/api";
import { cn } from "@/lib/utils";

const TONE = {
  error: {
    container: "bg-error/10 text-error",
    Icon: AlertCircle,
  },
  warning: {
    container: "bg-warning/10 text-warning",
    Icon: AlertTriangle,
  },
  info: {
    container: "bg-info/10 text-info",
    Icon: Info,
  },
} as const;

export function IssuePill({
  issue,
  compact = false,
}: {
  issue: ValidationIssue;
  compact?: boolean;
}) {
  const tone = TONE[issue.severity];
  const Icon = tone.Icon;
  return (
    <span
      role="note"
      aria-label={`${issue.severity}: ${issue.message}`}
      title={`${issue.code}: ${issue.message}`}
      className={cn(
        "inline-flex items-center gap-1 rounded-md font-medium",
        compact ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-1 text-2xs",
        tone.container,
      )}
    >
      <Icon className={compact ? "h-3 w-3" : "h-3.5 w-3.5"} />
      {!compact && <span className="truncate">{issue.message}</span>}
    </span>
  );
}
