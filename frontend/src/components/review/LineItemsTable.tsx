"use client";

// Compact table of line items. Per-line issues are matched against
// field_path strings of the form ``line_items[N].<field>``; matching
// rows get a faint error/warning tint and a pill row underneath.

import { Fragment } from "react";

import type { LineItem, ValidationIssue } from "@/lib/api";
import { cn } from "@/lib/utils";

import { IssuePill } from "./IssuePill";

type Props = {
  lineItems: LineItem[];
  issues: ValidationIssue[];
  currency: string;
};

const LINE_ITEM_PATH = /^line_items\[(\d+)\]/;

function issuesForLine(lineNumber: number, issues: ValidationIssue[]): ValidationIssue[] {
  return issues.filter((issue) => {
    const match = issue.field_path.match(LINE_ITEM_PATH);
    return match !== null && Number(match[1]) === lineNumber;
  });
}

export function LineItemsTable({ lineItems, issues, currency }: Props) {
  if (lineItems.length === 0) {
    return (
      <div className="rounded-xl border border-slate-100 bg-white p-4 text-2xs text-slate-400">
        No line items extracted.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-100">
      <table className="w-full text-2xs">
        <thead className="bg-slate-50 text-slate-400">
          <tr>
            <Th align="left">#</Th>
            <Th align="left">Description</Th>
            <Th align="right">Qty</Th>
            <Th align="right">Unit price</Th>
            <Th align="right">Tax</Th>
            <Th align="right">Total</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {lineItems.map((line) => {
            const lineIssues = issuesForLine(line.line_number, issues);
            const hasError = lineIssues.some((i) => i.severity === "error");
            const hasWarning = lineIssues.some((i) => i.severity === "warning");
            return (
              <Fragment key={line.id}>
                <tr
                  className={cn(
                    hasError && "bg-error/5",
                    !hasError && hasWarning && "bg-warning/5",
                  )}
                >
                  <td className="px-3 py-2 text-slate-400">{line.line_number}</td>
                  <td className="px-3 py-2">{line.description || "—"}</td>
                  <td className="px-3 py-2 text-right font-mono">{line.quantity ?? "—"}</td>
                  <td className="px-3 py-2 text-right font-mono">
                    {fmt(line.unit_price_excl_tax, currency)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">
                    {fmt(line.tax_amount, currency)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">
                    {fmt(line.line_total_incl_tax, currency)}
                  </td>
                </tr>
                {lineIssues.length > 0 && (
                  <tr className={cn(hasError ? "bg-error/5" : "bg-warning/5")}>
                    <td className="px-3 py-2" />
                    <td colSpan={5} className="px-3 pb-2">
                      <div className="flex flex-wrap gap-1.5">
                        {lineIssues.map((issue) => (
                          <IssuePill
                            key={issue.code + issue.field_path}
                            issue={issue}
                            compact
                          />
                        ))}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Th({ children, align }: { children: React.ReactNode; align: "left" | "right" }) {
  return (
    <th
      className={cn(
        "px-3 py-2 font-medium uppercase tracking-wider",
        align === "right" ? "text-right" : "text-left",
      )}
    >
      {children}
    </th>
  );
}

function fmt(value: string | null, currency: string): string {
  if (value === null || value === "") return "—";
  return `${currency} ${value}`;
}
