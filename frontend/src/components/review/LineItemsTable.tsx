"use client";

// Line items table.
//
// Read mode (no ``onChangeCell`` prop): static cells with per-line issue
// rows shown underneath any line that carries findings.
// Edit mode: every cell renders as a chrome-less input that looks like
// text until clicked. Three kinds of structural change ride alongside
// cell edits:
//   - Mark for removal: a Trash button on each existing row.
//     Removed rows render struck-through with a dashed muted
//     background until saved; "Undo" replaces the Trash button.
//   - Add a new line: a "+ Add line" button under the table prepends
//     a draft row with a Trash to discard.
//   - Edit cells (existing or pending-add): the standard cell-input
//     pattern from the previous slice, unchanged.
//
// The page composes the saved invoice's lines + any pending adds into
// the rendered list; the same draft store backs every kind of edit so
// "save" is one PATCH that bundles everything together.

import { Fragment } from "react";
import { Plus, RotateCcw, Trash2 } from "lucide-react";

import type { LineItem, ValidationIssue } from "@/lib/api";
import { cn } from "@/lib/utils";

import { IssuePill } from "./IssuePill";

export type LineDraft = Record<string, string>;

// A line-shaped object that may be a saved row OR a pending add.
// Pending adds get negative line_numbers so the rendered key is
// unique without colliding with any real number.
export type RenderedLine = LineItem & { _isAdd?: boolean };

type ReadProps = {
  lineItems: LineItem[];
  issues: ValidationIssue[];
  currency: string;
};

type EditProps = ReadProps & {
  drafts: Record<number, LineDraft>;
  pendingAdds: PendingAdd[];
  removed: number[];
  onChangeCell: (lineNumber: number, field: string, value: string) => void;
  onChangePendingAdd: (pendingNumber: number, field: string, value: string) => void;
  onAddLine: () => void;
  onRemoveLine: (lineNumber: number) => void;
  onUndoRemove: (lineNumber: number) => void;
  onDiscardPendingAdd: (pendingNumber: number) => void;
};

export type PendingAdd = {
  // Negative number used as the React key + the cell-input draft key.
  // Collisions with real line_numbers are impossible (real numbers
  // start at 1).
  pendingNumber: number;
  fields: LineDraft;
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

  if (!isEdit && lineItems.length === 0) {
    return (
      <div className="rounded-xl border border-slate-100 bg-white p-4 text-2xs text-slate-400">
        No line items extracted.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto rounded-xl border border-slate-100">
        <table className="w-full text-2xs">
          <thead className="bg-slate-50 text-slate-400">
            <tr>
              <Th align="left">#</Th>
              <Th align="left">Description</Th>
              <Th align="right">Qty</Th>
              <Th align="right">Unit price</Th>
              <Th align="right">Tax</Th>
              <Th align="right">Total</Th>
              {isEdit && <Th align="right">{""}</Th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {lineItems.length === 0 && !isEdit && (
              <tr>
                <td colSpan={6} className="px-3 py-3 text-slate-400">
                  No line items extracted.
                </td>
              </tr>
            )}

            {lineItems.map((line) => {
              const lineIssues = issuesForLine(line.line_number, issues);
              const hasError = lineIssues.some((i) => i.severity === "error");
              const hasWarning = lineIssues.some((i) => i.severity === "warning");
              const lineDraft = isEdit ? (props.drafts[line.line_number] ?? {}) : {};
              const markedForRemoval = isEdit && props.removed.includes(line.line_number);

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
                      markedForRemoval && "bg-error/5 line-through opacity-60",
                    )}
                  >
                    <td className="px-3 py-2 text-slate-400">{line.line_number}</td>
                    <Cell
                      isEdit={isEdit && !markedForRemoval}
                      align="left"
                      value={cellValue("description")}
                      dirty={cellDirty("description")}
                      onChange={
                        isEdit && !markedForRemoval
                          ? (v) => props.onChangeCell(line.line_number, "description", v)
                          : undefined
                      }
                    />
                    <Cell
                      isEdit={isEdit && !markedForRemoval}
                      align="right"
                      mono
                      value={cellValue("quantity")}
                      dirty={cellDirty("quantity")}
                      placeholder="—"
                      onChange={
                        isEdit && !markedForRemoval
                          ? (v) => props.onChangeCell(line.line_number, "quantity", v)
                          : undefined
                      }
                    />
                    <Cell
                      isEdit={isEdit && !markedForRemoval}
                      align="right"
                      mono
                      value={cellValue("unit_price_excl_tax")}
                      dirty={cellDirty("unit_price_excl_tax")}
                      prefix={isEdit ? undefined : currency}
                      placeholder="—"
                      onChange={
                        isEdit && !markedForRemoval
                          ? (v) => props.onChangeCell(line.line_number, "unit_price_excl_tax", v)
                          : undefined
                      }
                    />
                    <Cell
                      isEdit={isEdit && !markedForRemoval}
                      align="right"
                      mono
                      value={cellValue("tax_amount")}
                      dirty={cellDirty("tax_amount")}
                      prefix={isEdit ? undefined : currency}
                      placeholder="—"
                      onChange={
                        isEdit && !markedForRemoval
                          ? (v) => props.onChangeCell(line.line_number, "tax_amount", v)
                          : undefined
                      }
                    />
                    <Cell
                      isEdit={isEdit && !markedForRemoval}
                      align="right"
                      mono
                      value={cellValue("line_total_incl_tax")}
                      dirty={cellDirty("line_total_incl_tax")}
                      prefix={isEdit ? undefined : currency}
                      placeholder="—"
                      onChange={
                        isEdit && !markedForRemoval
                          ? (v) => props.onChangeCell(line.line_number, "line_total_incl_tax", v)
                          : undefined
                      }
                    />
                    {isEdit && (
                      <td className="px-3 py-2 text-right">
                        {markedForRemoval ? (
                          <button
                            type="button"
                            onClick={() => props.onUndoRemove(line.line_number)}
                            aria-label={`Undo remove of line ${line.line_number}`}
                            className="inline-flex items-center gap-1 text-2xs text-slate-500 hover:text-ink"
                          >
                            <RotateCcw className="h-3 w-3" />
                            Undo
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => props.onRemoveLine(line.line_number)}
                            aria-label={`Remove line ${line.line_number}`}
                            className="inline-flex items-center gap-1 text-2xs text-slate-400 hover:text-error"
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                  {!markedForRemoval && lineIssues.length > 0 && (
                    <tr className={cn(hasError ? "bg-error/5" : "bg-warning/5")}>
                      <td className="px-3 py-2" />
                      <td colSpan={isEdit ? 6 : 5} className="px-3 pb-2">
                        <div className="flex flex-wrap gap-1.5">
                          {lineIssues.map((issue) => (
                            <IssuePill key={issue.code + issue.field_path} issue={issue} compact />
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}

            {isEdit &&
              props.pendingAdds.map((pending) => (
                <PendingAddRow
                  key={pending.pendingNumber}
                  pending={pending}
                  onChange={(field, value) =>
                    props.onChangePendingAdd(pending.pendingNumber, field, value)
                  }
                  onDiscard={() => props.onDiscardPendingAdd(pending.pendingNumber)}
                />
              ))}
          </tbody>
        </table>
      </div>

      {isEdit && (
        <div>
          <button
            type="button"
            onClick={props.onAddLine}
            className="inline-flex items-center gap-1.5 text-2xs font-medium text-ink underline-offset-4 hover:underline"
          >
            <Plus className="h-3.5 w-3.5" />
            Add line
          </button>
        </div>
      )}
    </div>
  );
}

function PendingAddRow({
  pending,
  onChange,
  onDiscard,
}: {
  pending: PendingAdd;
  onChange: (field: string, value: string) => void;
  onDiscard: () => void;
}) {
  const v = (field: string) => pending.fields[field] ?? "";
  return (
    <tr className="bg-signal/5 ring-1 ring-signal/20">
      <td className="px-3 py-2 text-2xs text-signal">+ new</td>
      <Cell
        isEdit={true}
        align="left"
        value={v("description")}
        dirty={true}
        placeholder="Describe the new line"
        onChange={(value) => onChange("description", value)}
      />
      <Cell
        isEdit={true}
        align="right"
        mono
        value={v("quantity")}
        dirty={!!v("quantity")}
        placeholder="0"
        onChange={(value) => onChange("quantity", value)}
      />
      <Cell
        isEdit={true}
        align="right"
        mono
        value={v("unit_price_excl_tax")}
        dirty={!!v("unit_price_excl_tax")}
        placeholder="0.00"
        onChange={(value) => onChange("unit_price_excl_tax", value)}
      />
      <Cell
        isEdit={true}
        align="right"
        mono
        value={v("tax_amount")}
        dirty={!!v("tax_amount")}
        placeholder="0.00"
        onChange={(value) => onChange("tax_amount", value)}
      />
      <Cell
        isEdit={true}
        align="right"
        mono
        value={v("line_total_incl_tax")}
        dirty={!!v("line_total_incl_tax")}
        placeholder="0.00"
        onChange={(value) => onChange("line_total_incl_tax", value)}
      />
      <td className="px-3 py-2 text-right">
        <button
          type="button"
          onClick={onDiscard}
          aria-label="Discard pending line"
          className="inline-flex items-center gap-1 text-2xs text-slate-400 hover:text-error"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </td>
    </tr>
  );
}

type CellProps = {
  isEdit: boolean;
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
      return <td className={cn(tdClass, "text-slate-400")}>{placeholder ?? "—"}</td>;
    }
    return <td className={tdClass}>{prefix ? `${prefix} ${value}` : value}</td>;
  }

  return (
    <td className={tdClass}>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange?.(e.target.value)}
        className={cn(
          "w-full border-0 bg-transparent p-0 outline-none focus:ring-0",
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
