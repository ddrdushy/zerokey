"use client";

// Shared upload UI for the three CSV-driven accounting connectors —
// AutoCount (Slice 85), SQL Account + Sage UBS (Slice 98). All three
// hit the same backend endpoint with a per-type URL alias; the page-
// level pages just render this component with the right branding.
//
// PORTAL_PLAN Phase 2 — a third upload target lands here: "Invoices /
// CN / DN". When picked, the form uploads a sales-invoice CSV export
// to the connector's pull-documents endpoint, which creates one
// IngestionJob + Invoice per row. The result summary replaces the
// usual proposal-preview redirect.

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  Database,
  FileText,
  Loader2,
  Upload,
} from "lucide-react";

import { api, ApiError, type DocumentPullResult } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Target = "customers" | "items" | "documents";
type DocumentType = "invoice" | "credit_note" | "debit_note";

export type Variant = "autocount" | "sql_account" | "sage_ubs";

type CopyBlock = {
  title: string;
  exportPath: string;
  customerLabel: string;
  itemLabel: string;
  documentLabel: string;
  columnsHint: string;
  documentColumnsHint: string;
};

const COPY: Record<Variant, CopyBlock> = {
  autocount: {
    title: "AutoCount upload",
    exportPath: "AutoCount (File → Export → CSV)",
    customerLabel: "Debtor List (customers)",
    itemLabel: "Stock Items",
    documentLabel: "Sales Invoices / CN / DN",
    columnsHint:
      "Standard AutoCount export columns are matched automatically (Account No, Company Name, Tax Reg. No, BRN No, Address 1, Phone 1, Country Code; Item Code, Description, UOM, Standard Cost, Tax Code, MSIC Code).",
    documentColumnsHint:
      "Export your Sales Invoice / Credit Note / Debit Note listing from AutoCount. Standard headers are matched automatically (Doc No, Date, Debtor Name, Tax Reg. No, Sub Total, Tax Amount, Grand Total, Currency Code; Ref Doc No for CN / DN).",
  },
  sql_account: {
    title: "SQL Account upload",
    exportPath: "SQL Account (Maintain → Customer / Stock Item → File → Export → CSV)",
    customerLabel: "Debtor Maintenance (customers)",
    itemLabel: "Stock Maintenance",
    documentLabel: "Sales Invoices / CN / DN",
    columnsHint:
      "Standard SQL Account export columns are matched automatically (Code / Account No, Company Name, TIN, BRN, SST Reg. No, Address 1, Phone, Country, MSIC; Item Code, Description, UOM, Cost Price, Tax Code, MSIC).",
    documentColumnsHint:
      "Export your Sales Invoice / Credit Note / Debit Note listing from SQL Account. Standard headers are matched automatically (Doc No, Date, Customer Name, TIN, Sub Total, Tax Amount, Grand Total; Ref Invoice No for CN / DN).",
  },
  sage_ubs: {
    title: "Sage UBS upload",
    exportPath: "Sage UBS Accounting (Reports → Customer / Stock → Print → Export to CSV)",
    customerLabel: "Customer Master (customers)",
    itemLabel: "Stock / Inventory",
    documentLabel: "Sales Invoices / CN / DN",
    columnsHint:
      "Standard Sage UBS export columns are matched automatically (Customer No / Code, Customer Name, TIN / GST Reg No, BRN, Address 1, Telephone, Country, MSIC; Stock No, Description, UOM, Standard Cost, Tax Code, Classification).",
    documentColumnsHint:
      "Export your Sales Invoice / Credit Note / Debit Note listing from Sage UBS. Both legacy 9.x and LHDN-era headers are accepted (Doc No / Invoice No, Date, Customer Name, Tax No / TIN, Sub Total, Tax Amount, Total).",
  },
};

export function CsvAccountingUpload({ variant }: { variant: Variant }) {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [target, setTarget] = useState<Target>("customers");
  const [documentType, setDocumentType] = useState<DocumentType>("invoice");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pullResult, setPullResult] = useState<DocumentPullResult | null>(null);

  const copy = COPY[variant];

  async function onSubmit() {
    if (!file) return;
    setSubmitting(true);
    setError(null);
    setPullResult(null);
    try {
      if (target === "documents") {
        const result = await api.pullConnectorDocuments({
          configId: params.id,
          file,
          documentType,
        });
        setPullResult(result);
        // Stay on this page so the customer can see the summary.
        // The next step is usually opening the inbox to review the
        // ingested rows.
      } else {
        const proposal = await api.uploadAutoCountSync({
          configId: params.id,
          file,
          target,
          variant,
        });
        router.push(`/dashboard/connectors/proposals/${proposal.id}`);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        router.replace("/sign-in");
        return;
      }
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setSubmitting(false);
    }
  }

  function TargetTab({
    value,
    label,
    icon,
  }: {
    value: Target;
    label: string;
    icon?: React.ReactNode;
  }) {
    return (
      <button
        type="button"
        onClick={() => {
          setTarget(value);
          setPullResult(null);
        }}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-2xs font-medium transition",
          target === value
            ? "border-ink bg-ink text-paper"
            : "border-slate-200 text-slate-600 hover:border-slate-300",
        )}
      >
        {icon}
        {label}
      </button>
    );
  }

  return (
    <AppShell>
      <div className="flex max-w-3xl flex-col gap-6">
        <Link
          href="/dashboard/connectors"
          className="inline-flex items-center gap-1 text-2xs font-medium text-slate-500 hover:text-ink"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Connectors
        </Link>

        <header className="flex items-start gap-3">
          <div className="rounded-lg bg-ink/[0.05] p-2">
            <Database className="h-5 w-5 text-ink" />
          </div>
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">{copy.title}</h1>
            <p className="mt-1 text-2xs text-slate-500">
              Export your debtor list, stock items or sales invoices from {copy.exportPath} and
              upload here. ZeroKey reads the standard column headers — no mapping needed.
            </p>
          </div>
        </header>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-ink">1. What are you uploading?</h2>
          <div className="flex flex-wrap gap-2">
            <TargetTab value="customers" label={copy.customerLabel} />
            <TargetTab value="items" label={copy.itemLabel} />
            <TargetTab
              value="documents"
              label={copy.documentLabel}
              icon={<FileText className="h-3 w-3" />}
            />
          </div>
        </section>

        {target === "documents" && (
          <section className="flex flex-col gap-3">
            <h2 className="text-sm font-semibold text-ink">2. Document type</h2>
            <div className="flex gap-2">
              {(
                [
                  ["invoice", "Invoices"],
                  ["credit_note", "Credit notes"],
                  ["debit_note", "Debit notes"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setDocumentType(value)}
                  className={cn(
                    "rounded-md border px-3 py-2 text-2xs font-medium transition",
                    documentType === value
                      ? "border-ink bg-ink text-paper"
                      : "border-slate-200 text-slate-600 hover:border-slate-300",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            <p className="text-2xs text-slate-400">
              We dedupe against the document number — re-uploading the same CSV is safe and
              creates no duplicates.
            </p>
          </section>
        )}

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-ink">
            {target === "documents" ? "3" : "2"}. Upload the CSV
          </h2>
          <label
            htmlFor={`${variant}-file`}
            className="flex cursor-pointer items-center gap-3 rounded-xl border-2 border-dashed border-slate-200 bg-white px-4 py-8 text-center text-2xs text-slate-500 hover:border-slate-300"
          >
            <Upload className="h-4 w-4 text-slate-400" />
            {file ? <span className="text-ink">{file.name}</span> : <span>Click to choose…</span>}
            <input
              id={`${variant}-file`}
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setPullResult(null);
              }}
            />
          </label>
          <p className="text-2xs text-slate-400">
            {target === "documents" ? copy.documentColumnsHint : copy.columnsHint}
          </p>
        </section>

        {error && (
          <div className="rounded-md border border-error bg-error/5 px-4 py-2 text-2xs text-error">
            {error}
          </div>
        )}

        {pullResult && (
          <div className="rounded-xl border border-success/40 bg-success/5 p-4">
            <div className="flex items-start gap-3">
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" />
              <div className="flex-1">
                <div className="text-sm font-semibold text-ink">
                  Imported {pullResult.ingested_count}{" "}
                  {pullResult.document_type === "invoice"
                    ? "invoice"
                    : pullResult.document_type === "credit_note"
                      ? "credit note"
                      : "debit note"}
                  {pullResult.ingested_count === 1 ? "" : "s"}.
                </div>
                <dl className="mt-3 grid grid-cols-3 gap-3 text-2xs">
                  <div>
                    <dt className="text-slate-400">Ingested</dt>
                    <dd className="text-ink">{pullResult.ingested_count}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-400">Skipped (already seen)</dt>
                    <dd className="text-ink">{pullResult.skipped_count}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-400">Failed</dt>
                    <dd className="text-ink">{pullResult.failed_count}</dd>
                  </div>
                </dl>
                {pullResult.new_cursor && (
                  <p className="mt-2 text-2xs text-slate-500">
                    Cursor advanced to{" "}
                    <span className="font-mono text-ink">{pullResult.new_cursor}</span>.
                  </p>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                  <Link
                    href="/dashboard/inbox"
                    className="inline-flex items-center justify-center rounded-md bg-ink px-3 py-1.5 text-2xs font-medium text-paper hover:bg-slate-800"
                  >
                    Open the inbox →
                  </Link>
                  <Link
                    href="/dashboard/invoices"
                    className="inline-flex items-center justify-center rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs font-medium text-ink hover:bg-slate-50"
                  >
                    View invoices
                  </Link>
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="flex justify-end">
          <Button onClick={onSubmit} disabled={!file || submitting}>
            {submitting ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                {target === "documents" ? "Importing…" : "Proposing…"}
              </>
            ) : target === "documents" ? (
              "Import"
            ) : (
              "Propose changes"
            )}
          </Button>
        </div>
      </div>
    </AppShell>
  );
}
