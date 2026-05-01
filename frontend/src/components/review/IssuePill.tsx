"use client";

// Per-issue badge. Used in two places: inline next to a field on the
// review pane, and inside the line-items table cells. Tone derives from
// severity per the brand spec — error/warning/info map to the
// existing semantic tokens, so a future theme change updates everything.

import Link from "next/link";
import { AlertCircle, AlertTriangle, HelpCircle, Info } from "lucide-react";

import type { ValidationIssue } from "@/lib/api";
import { getHelpArticle } from "@/lib/help-articles";
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
  stale = false,
}: {
  issue: ValidationIssue;
  compact?: boolean;
  /**
   * The user has edited the field this issue is attached to but
   * hasn't saved yet — the issue is likely no longer accurate.
   * Render dimmed + struck-through with a "will revalidate on save"
   * affordance so the user gets immediate feedback that their edit
   * was acknowledged, without us pretending to know the new state.
   */
  stale?: boolean;
}) {
  const tone = TONE[issue.severity];
  const Icon = tone.Icon;
  // Slice 93 — when we have a long-form article for this code, render
  // a "?" link to /dashboard/help#<code>. The user gets the inline
  // message AND a path to the why + how-to-fix. Compact pills (line-
  // items table cells) skip the link to keep the cell tight; the
  // expanded panel above them carries the same article link.
  const article = getHelpArticle(issue.code);
  return (
    <span
      role="note"
      aria-label={`${issue.severity}: ${issue.message}${stale ? " (revalidating on save)" : ""}`}
      title={`${issue.code}: ${issue.message}`}
      className={cn(
        "inline-flex max-w-full items-start gap-1 rounded-md font-medium",
        compact ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-1 text-2xs",
        tone.container,
        stale && "opacity-50",
      )}
    >
      <Icon
        className={cn(compact ? "h-3 w-3" : "h-3.5 w-3.5", "mt-px shrink-0")}
        aria-hidden="true"
      />
      {!compact && (
        // No truncate: validation messages are intentionally written
        // to fit one line when the layout is wide, but we'd rather
        // wrap on a narrow viewport than hide the actionable detail.
        <span className={cn("whitespace-normal break-words", stale && "line-through")}>
          {issue.message}
        </span>
      )}
      {!compact && article && (
        <Link
          href={`/dashboard/help#${article.code}`}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Help: ${article.title}`}
          className="ml-1 inline-flex shrink-0 items-center hover:opacity-70"
          onClick={(e) => e.stopPropagation()}
        >
          <HelpCircle className="h-3 w-3" />
        </Link>
      )}
    </span>
  );
}
