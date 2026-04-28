"use client";

// Side-by-side invoice review screen.
//
// Layout: source document on the left, structured fields + validation
// findings on the right. Stacks on mobile (< md). Per UX_PRINCIPLES the
// primary "approve and submit" CTA lands here once submission is wired
// (Phase 3 follow-up); this slice presents the data and flags problems
// honestly so the user can review before that CTA exists.
//
// We poll while the job is still in flight, identical cadence to the
// dashboard list, so a freshly-uploaded invoice transitions from
// "received → ready_for_review" without a manual refresh.

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
import { LineItemsTable } from "@/components/review/LineItemsTable";
import { ValidationBanner } from "@/components/review/ValidationBanner";

const TERMINAL = new Set(["validated", "rejected", "cancelled", "error", "ready_for_review"]);

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [job, setJob] = useState<IngestionJob | null>(null);
  const [invoice, setInvoice] = useState<Invoice | null>(null);
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

  if (loading) return <Pad>Loading…</Pad>;
  if (error) return <Pad>{error}</Pad>;
  if (!job) return <Pad>Not found.</Pad>;

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
              <ReviewPanel invoice={invoice} />
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

function ReviewPanel({ invoice }: { invoice: Invoice }) {
  const issuesByPath = useMemo(() => groupByPath(invoice.validation_issues), [
    invoice.validation_issues,
  ]);
  const conf = invoice.per_field_confidence ?? {};

  // Top-level issues that aren't tied to a specific field render as a
  // separate stack so they don't get lost.
  const orphanIssues = invoice.validation_issues.filter((i) => {
    if (!i.field_path) return true;
    if (i.field_path.startsWith("line_items")) return false; // shown in the table
    return !FIELD_PATHS.has(i.field_path);
  });

  return (
    <>
      <ValidationBanner summary={invoice.validation_summary} />

      <section className="flex flex-col gap-4">
        <h2 className="text-base font-semibold">Header</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <FieldRow
            label="Invoice number"
            value={invoice.invoice_number}
            confidence={conf.invoice_number}
            issues={issuesByPath["invoice_number"]}
          />
          <FieldRow
            label="Issue date"
            value={
              invoice.issue_date
                ? new Date(invoice.issue_date).toLocaleDateString()
                : null
            }
            confidence={conf.issue_date}
            issues={issuesByPath["issue_date"]}
          />
          <FieldRow
            label="Due date"
            value={
              invoice.due_date
                ? new Date(invoice.due_date).toLocaleDateString()
                : null
            }
            confidence={conf.due_date}
            issues={issuesByPath["due_date"]}
          />
          <FieldRow
            label="Currency"
            value={invoice.currency_code}
            confidence={conf.currency_code}
            issues={issuesByPath["currency_code"]}
          />
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-base font-semibold">Parties</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <PartyBlock
            label="Supplier"
            name={invoice.supplier_legal_name}
            tin={invoice.supplier_tin}
            address={invoice.supplier_address}
            confidence={conf}
            prefix="supplier"
            issuesByPath={issuesByPath}
          />
          <PartyBlock
            label="Buyer"
            name={invoice.buyer_legal_name}
            tin={invoice.buyer_tin}
            address={invoice.buyer_address}
            confidence={conf}
            prefix="buyer"
            issuesByPath={issuesByPath}
          />
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-base font-semibold">Totals</h2>
        <div className="grid gap-3 md:grid-cols-3">
          <FieldRow
            label="Subtotal"
            value={fmtMoney(invoice.subtotal, invoice.currency_code)}
            confidence={conf.subtotal}
            issues={issuesByPath["totals.subtotal"]}
            mono
          />
          <FieldRow
            label="Total tax"
            value={fmtMoney(invoice.total_tax, invoice.currency_code)}
            confidence={conf.total_tax}
            issues={issuesByPath["totals.total_tax"]}
            mono
          />
          <FieldRow
            label="Grand total"
            value={fmtMoney(invoice.grand_total, invoice.currency_code)}
            confidence={conf.grand_total}
            issues={issuesByPath["totals.grand_total"]}
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

function PartyBlock({
  label,
  name,
  tin,
  address,
  confidence,
  prefix,
  issuesByPath,
}: {
  label: string;
  name: string;
  tin: string;
  address: string;
  confidence: Record<string, number>;
  prefix: "supplier" | "buyer";
  issuesByPath: Record<string, ValidationIssue[]>;
}) {
  return (
    <div className="flex flex-col gap-3">
      <FieldRow
        label={`${label} name`}
        value={name}
        confidence={confidence[`${prefix}_legal_name`]}
        issues={issuesByPath[`${prefix}_legal_name`]}
      />
      <FieldRow
        label={`${label} TIN`}
        value={tin}
        confidence={confidence[`${prefix}_tin`]}
        issues={issuesByPath[`${prefix}_tin`]}
        mono
      />
      <FieldRow
        label={`${label} address`}
        value={address}
        confidence={confidence[`${prefix}_address`]}
        issues={issuesByPath[`${prefix}_address`]}
      />
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

function fmtMoney(value: string | null, currency: string): string | null {
  if (value === null || value === "") return null;
  return `${currency} ${value}`;
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

// Field paths the UI explicitly renders. Anything in validation_issues that
// doesn't match one of these (and isn't a line_items[N] path) shows up in
// the orphan-issues stack so nothing gets lost.
const FIELD_PATHS = new Set([
  "invoice_number",
  "issue_date",
  "due_date",
  "currency_code",
  "supplier_legal_name",
  "supplier_tin",
  "supplier_address",
  "supplier_msic_code",
  "buyer_legal_name",
  "buyer_tin",
  "buyer_address",
  "buyer_msic_code",
  "buyer_country_code",
  "totals.subtotal",
  "totals.total_tax",
  "totals.grand_total",
]);
