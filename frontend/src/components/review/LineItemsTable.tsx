"use client";

// Line items table.
//
// Read mode (no ``onChangeCell`` prop): static cells with per-line issue
// rows shown underneath any line that carries findings.
// Edit mode (``onChangeCell`` provided): every cell renders as a chrome-
// less input that looks like text until clicked. The page owns the draft
// state keyed by (line_number, field) and submits the changes alongside
// the header draft when the user saves.
//
// Visual conventions inherited from FieldRow:
//   - Cells with unsaved edits get a Signal-tinted ring.
//   - Tinted issue row underneath (error -> error/5, warning -> warning/5)
//     unchanged from read mode.

import { Fragment } from "react";

import type { LineItem, ValidationIssue } from "@/lib/api";
import { cn } from "@/lib/utils";

import { IssuePill } from "./IssuePill";

export type LineDraft = Record<string, string>;

type ReadProps = {
  lineItems: LineItem[];
  issues: ValidationIssue[];
  currency: string;
};

type EditProps = ReadProps & {
  drafts: Record<number, LineDraft>; // keyed by line_number
  onChangeCell: (lineNumber: number, field: string, value: string) => void;
};

const LINE_ITEM_PATH = /^line_items\[(\d+)\]/;

function issuesForLine(lineNumber: number, issues: ValidationIssue[]): ValidationIssue[] {
  return issues.filter((issue) => {
    const match = issue.field_path.match(LINE_ITEM_PATH);
    return match !== null && Number(match[1]) === lineNumber;
  });
}

export function LineItemsTable(props: ReadProps | EditProps) {
  const { lineItems, issues, currency } = props;
  const isEdit = "onChangeCell" in props;

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
            const lineDraft = isEdit ? props.drafts[line.line_number] ?? {} : {};

            const cellValue = (field: keyof LineItem): string => {
              if (field in lineDraft) return lineDraft[field as string] ?? "";
              const raw = line[field];
              if (raw === null || raw === undefined) return "";
              return String(raw);
            };
            const cellDirty = (field: string) => field in lineDraft;

            return (
              <Fragment key={line.id}>
                <tr
                  className={cn(
                    hasError && "bg-error/5",
                    !hasError && hasWarning && "bg-warning/5",
                  )}
                >
                  <td className="px-3 py-2 text-slate-400">{line.line_number}</td>
                  <Cell
                    isEdit={isEdit}
                    field="description"
                    align="left"
                    value={cellValue("description")}
                    dirty={cellDirty("description")}
                    onChange={
                      isEdit
                        ? (v) => props.onChangeCell(line.line_number, "description", v)
                        : undefined
                    }
                  />
                  <Cell
                    isEdit={isEdit}
                    field="quantity"
                    align="right"
                    mono
                    value={cellValue("quantity")}
                    dirty={cellDirty("quantity")}
                    placeholder="—"
                    onChange={
                      isEdit
                        ? (v) => props.onChangeCell(line.line_number, "quantity", v)
                        : undefined
                    }
                  />
                  <Cell
                    isEdit={isEdit}
                    field="unit_price_excl_tax"
                    align="right"
                    mono
                    value={cellValue("unit_price_excl_tax")}
                    dirty={cellDirty("unit_price_excl_tax")}
                    prefix={isEdit ? undefined : currency}
                    placeholder="—"
                    onChange={
                      isEdit
                        ? (v) =>
                            props.onChangeCell(
                              line.line_number,
                              "unit_price_excl_tax",
                              v,
                            )
                        : undefined
                    }
                  />
                  <Cell
                    isEdit={isEdit}
                    field="tax_amount"
                    align="right"
                    mono
                    value={cellValue("tax_amount")}
                    dirty={cellDirty("tax_amount")}
                    prefix={isEdit ? undefined : currency}
                    placeholder="—"
                    onChange={
                      isEdit
                        ? (v) =>
                            props.onChangeCell(line.line_number, "tax_amount", v)
                        : undefined
                    }
                  />
                  <Cell
                    isEdit={isEdit}
                    field="line_total_incl_tax"
                    align="right"
                    mono
                    value={cellValue("line_total_incl_tax")}
                    dirty={cellDirty("line_total_incl_tax")}
                    prefix={isEdit ? undefined : currency}
                    placeholder="—"
                    onChange={
                      isEdit
                        ? (v) =>
                            props.onChangeCell(
                              line.line_number,
                              "line_total_incl_tax",
                              v,
                            )
                        : undefined
                    }
                  />
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

type CellProps = {
  isEdit: boolean;
  field: string;
  align: "left" | "right";
  value: string;
  dirty: boolean;
  prefix?: string;
  placeholder?: string;
  mono?: boolean;
  onChange?: (value: string) => void;
};

function Cell({ isEdit, align, value, dirty, prefix, placeholder, mono, onChange }: CellProps) {
  const tdClass = cn(
    "px-3 py-2 transition-colors",
    align === "right" ? "text-right" : "text-left",
    mono && "font-mono",
    dirty && "ring-1 ring-signal/30 bg-signal/5 rounded",
  );

  if (!isEdit) {
    if (!value) {
      return (
        <td className={cn(tdClass, "text-slate-400")}>{placeholder ?? "—"}</td>
      );
    }
    return (
      <td className={tdClass}>
        {prefix ? `${prefix} ${value}` : value}
      </td>
    );
  }

  return (
    <td className={tdClass}>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange?.(e.target.value)}
        className={cn(
          "w-full bg-transparent outline-none focus:ring-0 border-0 p-0",
          align === "right" ? "text-right" : "text-left",
          mono && "font-mono",
          !value && "text-slate-400",
        )}
      />
    </td>
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
