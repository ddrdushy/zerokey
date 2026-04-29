"use client";

// Side-by-side invoice review screen.
//
// Layout: source document on the left, structured fields + validation
// findings on the right. Stacks on mobile (< lg). The right pane's
// header and party + totals fields are EDITABLE — corrections submit
// through the PATCH endpoint, which re-runs enrichment + validation
// and returns the updated invoice with fresh issues.
//
// The "Save corrections" action (UX_PRINCIPLES principle 2: one primary
// action per screen) only appears when the local draft has at least
// one pending change. The submit-and-sign primary action will replace
// it once the signing service lands.
//
// Polling continues while the job is non-terminal so a freshly-uploaded
// invoice transitions from "received -> ready_for_review" without a
// manual refresh.

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import {
  api,
  ApiError,
  type IngestionJob,
  type Invoice,
  type ValidationIssue,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { AppShell } from "@/components/shell/AppShell";
import { DocumentPreview } from "@/components/review/DocumentPreview";
import { FieldRow } from "@/components/review/FieldRow";
import { IssuePill } from "@/components/review/IssuePill";
import {
  LineItemsTable,
  type LineDraft,
  type PendingAdd,
} from "@/components/review/LineItemsTable";
import { ValidationBanner } from "@/components/review/ValidationBanner";
import { LhdnPanel } from "@/components/review/LhdnPanel";

const TERMINAL = new Set(["validated", "rejected", "cancelled", "error", "ready_for_review"]);

// Editable header field set — must match backend EDITABLE_HEADER_FIELDS.
// We keep the type narrow so an accidental typo in the page's onChange
// flow gets caught at compile time.
type EditableField =
  | "invoice_number"
  | "issue_date"
  | "due_date"
  | "currency_code"
  | "supplier_legal_name"
  | "supplier_tin"
  | "supplier_address"
  | "supplier_msic_code"
  | "supplier_id_type"
  | "supplier_id_value"
  | "buyer_legal_name"
  | "buyer_tin"
  | "buyer_address"
  | "buyer_msic_code"
  | "buyer_country_code"
  | "buyer_id_type"
  | "buyer_id_value"
  | "subtotal"
  | "total_tax"
  | "grand_total";

type Draft = Partial<Record<EditableField, string>>;
// Line-item drafts: keyed by line_number -> { fieldName: newValue }.
type LineDrafts = Record<number, LineDraft>;

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [job, setJob] = useState<IngestionJob | null>(null);
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [lineDrafts, setLineDrafts] = useState<LineDrafts>({});
  const [pendingAdds, setPendingAdds] = useState<PendingAdd[]>([]);
  const [removedNumbers, setRemovedNumbers] = useState<number[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function load() {
      try {
        const data = await api.getJob(params.id);
        if (cancelled) return;
        setJob(data);
        setLoading(false);
        if (data.status === "ready_for_review" || TERMINAL.has(data.status)) {
          api
            .getInvoiceForJob(params.id)
            .then((inv) => !cancelled && setInvoice(inv))
            .catch(() => {});
        }
        if (!TERMINAL.has(data.status)) {
          timer = setTimeout(load, 2000);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/sign-in");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load job.");
        setLoading(false);
      }
    }
    load();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [params.id, router]);

  function onChangeField(name: string, value: string) {
    setSaveError(null);
    setDraft((prev) => ({ ...prev, [name as EditableField]: value }));
  }

  function onChangeLineCell(lineNumber: number, field: string, value: string) {
    setSaveError(null);
    setLineDrafts((prev) => ({
      ...prev,
      [lineNumber]: { ...(prev[lineNumber] ?? {}), [field]: value },
    }));
  }

  function onChangePendingAdd(
    pendingNumber: number,
    field: string,
    value: string,
  ) {
    setSaveError(null);
    setPendingAdds((prev) =>
      prev.map((p) =>
        p.pendingNumber === pendingNumber
          ? { ...p, fields: { ...p.fields, [field]: value } }
          : p,
      ),
    );
  }

  function onAddLine() {
    setSaveError(null);
    // Negative numbers as keys; collisions with real line_numbers are
    // impossible since real numbers start at 1. Each click decrements.
    setPendingAdds((prev) => {
      const nextPending =
        prev.length === 0
          ? -1
          : Math.min(...prev.map((p) => p.pendingNumber)) - 1;
      return [...prev, { pendingNumber: nextPending, fields: {} }];
    });
  }

  function onRemoveLine(lineNumber: number) {
    setSaveError(null);
    setRemovedNumbers((prev) =>
      prev.includes(lineNumber) ? prev : [...prev, lineNumber],
    );
  }

  function onUndoRemove(lineNumber: number) {
    setSaveError(null);
    setRemovedNumbers((prev) => prev.filter((n) => n !== lineNumber));
  }

  function onDiscardPendingAdd(pendingNumber: number) {
    setSaveError(null);
    setPendingAdds((prev) =>
      prev.filter((p) => p.pendingNumber !== pendingNumber),
    );
  }

  async function onSave() {
    if (!invoice) return;
    setSaving(true);
    setSaveError(null);
    try {
      // Build the PATCH payload combining header drafts, cell edits,
      // structural adds, and structural removes. Empty strings clear
      // cells; the backend coerces them per type.
      const payload: Record<string, unknown> = { ...draft };
      const lineEntries = Object.entries(lineDrafts);
      if (lineEntries.length > 0) {
        payload.line_items = lineEntries.map(([num, fields]) => ({
          line_number: Number(num),
          ...fields,
        }));
      }
      // Pending adds — strip the local pendingNumber, send only the
      // user-entered fields. Empty pending adds (the user clicked
      // "Add line" but typed nothing) are dropped silently rather than
      // sent and rejected by the backend's "non-empty description"
      // rule; the user discards them implicitly by saving without
      // filling them in.
      const validAdds = pendingAdds
        .map((p) => p.fields)
        .filter((f) => (f.description ?? "").trim() !== "");
      if (validAdds.length > 0) {
        payload.add_line_items = validAdds;
      }
      if (removedNumbers.length > 0) {
        payload.remove_line_items = removedNumbers;
      }
      const updated = await api.updateInvoice(
        invoice.id,
        payload as Record<string, string | null>,
      );
      setInvoice(updated);
      setDraft({});
      setLineDrafts({});
      setPendingAdds([]);
      setRemovedNumbers([]);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  function onDiscard() {
    setDraft({});
    setLineDrafts({});
    setPendingAdds([]);
    setRemovedNumbers([]);
    setSaveError(null);
  }

  if (loading) return <Pad>Loading…</Pad>;
  if (error) return <Pad>{error}</Pad>;
  if (!job) return <Pad>Not found.</Pad>;

  const dirtyCount =
    Object.keys(draft).length +
    Object.values(lineDrafts).reduce((sum, d) => sum + Object.keys(d).length, 0) +
    // Each non-empty pending add counts once; empty ones are dropped on save.
    pendingAdds.filter((p) => (p.fields.description ?? "").trim() !== "")
      .length +
    removedNumbers.length;

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <Header job={job} onBack={() => router.push("/dashboard")} />

        <div className="grid gap-6 lg:grid-cols-[1fr_1fr] lg:items-start">
          <div className="lg:sticky lg:top-6 lg:h-[calc(100vh-8rem)]">
            <DocumentPreview
              filename={job.original_filename}
              mimeType={job.file_mime_type}
              downloadUrl={job.download_url}
            />
          </div>

          <div className="flex flex-col gap-5">
            {invoice ? (
              <ReviewPanel
                invoice={invoice}
                draft={draft}
                lineDrafts={lineDrafts}
                pendingAdds={pendingAdds}
                removedNumbers={removedNumbers}
                onChangeField={onChangeField}
                onChangeLineCell={onChangeLineCell}
                onChangePendingAdd={onChangePendingAdd}
                onAddLine={onAddLine}
                onRemoveLine={onRemoveLine}
                onUndoRemove={onUndoRemove}
                onDiscardPendingAdd={onDiscardPendingAdd}
                onInvoiceChanged={setInvoice}
              />
            ) : (
              <PendingPanel job={job} />
            )}

            <details className="rounded-xl border border-slate-100 bg-white">
              <summary className="cursor-pointer select-none px-4 py-3 text-2xs font-medium uppercase tracking-wider text-slate-400">
                State history · {job.state_transitions?.length ?? 0} steps
              </summary>
              <ul className="divide-y divide-slate-100 border-t border-slate-100">
                {(job.state_transitions ?? []).map((t, idx) => (
                  <li
                    key={idx}
                    className="flex items-center justify-between px-4 py-2 text-2xs"
                  >
                    <span className="font-medium uppercase tracking-wider text-slate-600">
                      {t.status.replace(/_/g, " ")}
                    </span>
                    <span className="text-slate-400">
                      {new Date(t.at).toLocaleString()}
                    </span>
                  </li>
                ))}
              </ul>
            </details>

            {job.extracted_text && (
              <details className="rounded-xl border border-slate-100 bg-white">
                <summary className="cursor-pointer select-none px-4 py-3 text-2xs font-medium uppercase tracking-wider text-slate-400">
                  Raw extracted text · {job.extracted_text.length} chars
                </summary>
                <pre className="max-h-80 overflow-auto border-t border-slate-100 bg-slate-50 p-4 font-mono text-2xs leading-relaxed text-slate-600">
                  {job.extracted_text}
                </pre>
              </details>
            )}
          </div>
        </div>

        {dirtyCount > 0 && (
          <SaveBar
            count={dirtyCount}
            saving={saving}
            error={saveError}
            onSave={onSave}
            onDiscard={onDiscard}
          />
        )}
      </div>
    </AppShell>
  );
}

function Header({ job, onBack }: { job: IngestionJob; onBack: () => void }) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <Button variant="ghost" size="sm" onClick={onBack}>
          ← Dashboard
        </Button>
        <h1 className="mt-1 font-display text-2xl font-bold tracking-tight">
          {job.original_filename}
        </h1>
        <div className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
          {job.source_channel} · {(job.file_size / 1024).toFixed(1)} KB ·{" "}
          {job.extraction_engine || "no engine"}
          {job.extraction_confidence != null &&
            ` · ${(job.extraction_confidence * 100).toFixed(0)}% confidence`}
        </div>
      </div>
      <StatusPill status={job.status} />
    </div>
  );
}

function PendingPanel({ job }: { job: IngestionJob }) {
  const isError = job.status === "error" || job.status === "rejected";
  return (
    <section className="rounded-xl border border-slate-100 bg-white p-6">
      <h2 className="text-base font-semibold">
        {isError ? "Extraction did not complete" : "Working on it"}
      </h2>
      <p className="mt-2 text-2xs text-slate-500">
        {isError
          ? job.error_message ||
            "Something went wrong before structuring could finish. The audit log captures the cause."
          : `Status: ${job.status.replace(/_/g, " ")}. The page refreshes automatically every 2 seconds while the job is in flight.`}
      </p>
    </section>
  );
}

type ReviewPanelProps = {
  invoice: Invoice;
  draft: Draft;
  lineDrafts: LineDrafts;
  pendingAdds: PendingAdd[];
  removedNumbers: number[];
  onChangeField: (name: string, value: string) => void;
  onChangeLineCell: (lineNumber: number, field: string, value: string) => void;
  onChangePendingAdd: (
    pendingNumber: number,
    field: string,
    value: string,
  ) => void;
  onAddLine: () => void;
  onRemoveLine: (lineNumber: number) => void;
  onUndoRemove: (lineNumber: number) => void;
  onDiscardPendingAdd: (pendingNumber: number) => void;
  /** Slice 59B — receive LHDN panel updates from child component. */
  onInvoiceChanged: (next: Invoice) => void;
};

function ReviewPanel({
  invoice,
  draft,
  lineDrafts,
  pendingAdds,
  removedNumbers,
  onChangeField,
  onChangeLineCell,
  onChangePendingAdd,
  onAddLine,
  onRemoveLine,
  onUndoRemove,
  onDiscardPendingAdd,
  onInvoiceChanged,
}: ReviewPanelProps) {
  const issuesByPath = useMemo(() => groupByPath(invoice.validation_issues), [
    invoice.validation_issues,
  ]);
  const conf = invoice.per_field_confidence ?? {};

  // ``valueOf(name)`` returns the value the user is currently looking at:
  // the draft override if there is one, otherwise the saved invoice
  // value. Dates render as YYYY-MM-DD for the date input control.
  const valueOf = (name: EditableField): string => {
    if (name in draft) return draft[name] ?? "";
    const raw = (invoice as Record<string, unknown>)[name];
    if (raw === null || raw === undefined) return "";
    return String(raw);
  };
  const isDirty = (name: EditableField): boolean => name in draft;

  // Top-level issues that aren't tied to a specific field render as a
  // separate stack so they don't get lost. The ``line_items[N]`` paths
  // are rendered inline by LineItemsTable; a bare ``line_items`` path
  // (e.g. the ``required.line_items`` rule firing on zero items) has
  // nowhere else to land — orphan-stack it.
  const orphanIssues = invoice.validation_issues.filter((i) => {
    if (!i.field_path) return true;
    if (i.field_path.startsWith("line_items[")) return false;
    return !FIELD_PATHS.has(i.field_path);
  });

  // Slice 59B: blocking issues for the LHDN submit gate. We treat
  // any open validation issue as blocking — same threshold the
  // ValidationBanner shows.
  const blockingIssues = invoice.validation_issues.filter(
    (i) => i.severity !== "info",
  ).length;

  return (
    <>
      <ValidationBanner summary={invoice.validation_summary} />

      <LhdnPanel
        invoice={invoice}
        onInvoiceChanged={onInvoiceChanged}
        blockingIssues={blockingIssues}
      />

      <section className="flex flex-col gap-4">
        <h2 className="text-base font-semibold">Header</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <FieldRow
            label="Invoice number"
            name="invoice_number"
            value={valueOf("invoice_number")}
            confidence={conf.invoice_number}
            issues={issuesByPath["invoice_number"]}
            dirty={isDirty("invoice_number")}
            onChange={onChangeField}
          />
          <FieldRow
            label="Issue date"
            name="issue_date"
            kind="date"
            value={valueOf("issue_date")}
            confidence={conf.issue_date}
            issues={issuesByPath["issue_date"]}
            dirty={isDirty("issue_date")}
            onChange={onChangeField}
          />
          <FieldRow
            label="Due date"
            name="due_date"
            kind="date"
            value={valueOf("due_date")}
            confidence={conf.due_date}
            issues={issuesByPath["due_date"]}
            dirty={isDirty("due_date")}
            onChange={onChangeField}
          />
          <FieldRow
            label="Currency"
            name="currency_code"
            value={valueOf("currency_code")}
            confidence={conf.currency_code}
            issues={issuesByPath["currency_code"]}
            dirty={isDirty("currency_code")}
            onChange={onChangeField}
          />
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-base font-semibold">Parties</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <PartyBlock
            label="Supplier"
            prefix="supplier"
            valueOf={valueOf}
            isDirty={isDirty}
            confidence={conf}
            issuesByPath={issuesByPath}
            onChange={onChangeField}
          />
          <PartyBlock
            label="Buyer"
            prefix="buyer"
            valueOf={valueOf}
            isDirty={isDirty}
            confidence={conf}
            issuesByPath={issuesByPath}
            onChange={onChangeField}
          />
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-base font-semibold">Totals</h2>
        <div className="grid gap-3 md:grid-cols-3">
          <FieldRow
            label="Subtotal"
            name="subtotal"
            kind="decimal"
            value={valueOf("subtotal")}
            confidence={conf.subtotal}
            issues={issuesByPath["totals.subtotal"]}
            dirty={isDirty("subtotal")}
            onChange={onChangeField}
            mono
          />
          <FieldRow
            label="Total tax"
            name="total_tax"
            kind="decimal"
            value={valueOf("total_tax")}
            confidence={conf.total_tax}
            issues={issuesByPath["totals.total_tax"]}
            dirty={isDirty("total_tax")}
            onChange={onChangeField}
            mono
          />
          <FieldRow
            label="Grand total"
            name="grand_total"
            kind="decimal"
            value={valueOf("grand_total")}
            confidence={conf.grand_total}
            issues={issuesByPath["totals.grand_total"]}
            dirty={isDirty("grand_total")}
            onChange={onChangeField}
            mono
          />
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold">Line items</h2>
        <LineItemsTable
          lineItems={invoice.line_items}
          issues={invoice.validation_issues}
          currency={invoice.currency_code}
          drafts={lineDrafts}
          pendingAdds={pendingAdds}
          removed={removedNumbers}
          onChangeCell={onChangeLineCell}
          onChangePendingAdd={onChangePendingAdd}
          onAddLine={onAddLine}
          onRemoveLine={onRemoveLine}
          onUndoRemove={onUndoRemove}
          onDiscardPendingAdd={onDiscardPendingAdd}
        />
      </section>

      {orphanIssues.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="text-base font-semibold">Other issues</h2>
          <div className="flex flex-col gap-1.5">
            {orphanIssues.map((issue) => (
              <IssuePill key={issue.code + issue.field_path} issue={issue} />
            ))}
          </div>
        </section>
      )}
    </>
  );
}

type PartyBlockProps = {
  label: string;
  prefix: "supplier" | "buyer";
  valueOf: (name: EditableField) => string;
  isDirty: (name: EditableField) => boolean;
  confidence: Record<string, number>;
  issuesByPath: Record<string, ValidationIssue[]>;
  onChange: (name: string, value: string) => void;
};

function PartyBlock({
  label,
  prefix,
  valueOf,
  isDirty,
  confidence,
  issuesByPath,
  onChange,
}: PartyBlockProps) {
  const nameField = `${prefix}_legal_name` as EditableField;
  const tinField = `${prefix}_tin` as EditableField;
  const addressField = `${prefix}_address` as EditableField;
  const idTypeField = `${prefix}_id_type` as EditableField;
  const idValueField = `${prefix}_id_value` as EditableField;
  return (
    <div className="flex flex-col gap-3">
      <FieldRow
        label={`${label} name`}
        name={nameField}
        value={valueOf(nameField)}
        confidence={confidence[nameField]}
        issues={issuesByPath[nameField]}
        dirty={isDirty(nameField)}
        onChange={onChange}
      />
      <FieldRow
        label={`${label} TIN`}
        name={tinField}
        value={valueOf(tinField)}
        confidence={confidence[tinField]}
        issues={issuesByPath[tinField]}
        dirty={isDirty(tinField)}
        onChange={onChange}
        mono
      />
      <PartyIdTypeRow
        idTypeField={idTypeField}
        idValueField={idValueField}
        valueOf={valueOf}
        isDirty={isDirty}
        onChange={onChange}
      />
      <FieldRow
        label={`${label} address`}
        name={addressField}
        value={valueOf(addressField)}
        confidence={confidence[addressField]}
        issues={issuesByPath[addressField]}
        dirty={isDirty(addressField)}
        onChange={onChange}
      />
    </div>
  );
}

// LHDN secondary-ID picker — NRIC | PASSPORT | BRN | ARMY.
// Two side-by-side fields: a select for the scheme + a free-
// text value. Choose the right scheme based on entity type:
//   - Malaysian individual → NRIC (12-digit MyKad)
//   - Foreigner            → PASSPORT (alphanumeric)
//   - Military             → ARMY
//   - Corporate / business → BRN (registration number)
// Wrong scheme = LHDN ERR206 even when value is correct.
function PartyIdTypeRow({
  idTypeField,
  idValueField,
  valueOf,
  isDirty,
  onChange,
}: {
  idTypeField: EditableField;
  idValueField: EditableField;
  valueOf: (name: EditableField) => string;
  isDirty: (name: EditableField) => boolean;
  onChange: (name: string, value: string) => void;
}) {
  const idType = valueOf(idTypeField);
  const dirty = isDirty(idTypeField) || isDirty(idValueField);
  return (
    <div
      className={[
        "rounded-xl border px-4 py-3",
        dirty ? "border-amber-200 ring-1 ring-amber-200" : "border-slate-100",
      ].join(" ")}
    >
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        ID type / number
      </div>
      <div className="mt-1.5 grid grid-cols-[110px_1fr] gap-2">
        <select
          aria-label="ID type"
          value={idType}
          onChange={(e) => onChange(idTypeField as string, e.target.value)}
          className="rounded-md border border-slate-200 bg-white px-2 py-1.5 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink"
        >
          <option value="">—</option>
          <option value="NRIC">NRIC</option>
          <option value="PASSPORT">PASSPORT</option>
          <option value="BRN">BRN</option>
          <option value="ARMY">ARMY</option>
        </select>
        <input
          type="text"
          aria-label="ID number"
          value={valueOf(idValueField)}
          onChange={(e) => onChange(idValueField as string, e.target.value)}
          placeholder={
            idType === "NRIC"
              ? "12-digit MyKad number"
              : idType === "PASSPORT"
                ? "Passport number"
                : idType === "BRN"
                  ? "Business Registration Number"
                  : idType === "ARMY"
                    ? "Military ID"
                    : "Pick a type first"
          }
          disabled={!idType}
          className="rounded-md border border-slate-200 bg-white px-2 py-1.5 font-mono text-[11px] text-ink focus:outline-none focus:ring-1 focus:ring-ink disabled:bg-slate-50 disabled:text-slate-400"
        />
      </div>
      <p className="mt-1 text-[10px] text-slate-400">
        LHDN matches TIN + this ID against HITS. Wrong scheme returns
        ERR206 even when the number is right.
      </p>
    </div>
  );
}

type SaveBarProps = {
  count: number;
  saving: boolean;
  error: string | null;
  onSave: () => void;
  onDiscard: () => void;
};

function SaveBar({ count, saving, error, onSave, onDiscard }: SaveBarProps) {
  return (
    <div
      role="region"
      aria-label="Unsaved corrections"
      className="sticky bottom-0 left-0 right-0 z-10 -mx-6 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white/95 px-6 py-3 backdrop-blur"
    >
      <div className="text-2xs">
        <span className="font-medium text-ink">
          {count} unsaved correction{count === 1 ? "" : "s"}
        </span>
        {error ? (
          <span className="ml-3 text-error">{error}</span>
        ) : (
          <span className="ml-3 text-slate-500">
            Save to re-validate against LHDN rules. Your masters learn from this.
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onDiscard} disabled={saving}>
          Discard
        </Button>
        <Button size="sm" onClick={onSave} disabled={saving}>
          {saving ? "Saving…" : "Save corrections"}
        </Button>
      </div>
    </div>
  );
}

function Pad({ children }: { children: React.ReactNode }) {
  return (
    <AppShell>
      <div className="grid place-items-center py-24 text-slate-400">{children}</div>
    </AppShell>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status === "validated" || status === "ready_for_review"
      ? "bg-success/10 text-success"
      : status === "error" || status === "rejected"
        ? "bg-error/10 text-error"
        : "bg-slate-100 text-slate-600";
  return (
    <span className={["rounded-full px-3 py-1 text-2xs font-medium", tone].join(" ")}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

function groupByPath(issues: ValidationIssue[]): Record<string, ValidationIssue[]> {
  const out: Record<string, ValidationIssue[]> = {};
  for (const issue of issues) {
    const key = issue.field_path || "_orphan";
    if (!out[key]) out[key] = [];
    out[key].push(issue);
  }
  return out;
}

const FIELD_PATHS = new Set([
  "invoice_number",
  "issue_date",
  "due_date",
  "currency_code",
  "supplier_legal_name",
  "supplier_tin",
  "supplier_address",
  "supplier_msic_code",
  "supplier_id_type",
  "supplier_id_value",
  "buyer_legal_name",
  "buyer_tin",
  "buyer_address",
  "buyer_msic_code",
  "buyer_country_code",
  "buyer_id_type",
  "buyer_id_value",
  "totals.subtotal",
  "totals.total_tax",
  "totals.grand_total",
]);
