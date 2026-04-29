"use client";

// Slice 77b — CSV upload wizard.
//
// Three-step flow on a single page:
//   1. Pick a file (drag-or-browse).
//   2. Map source columns → ZeroKey master fields. Auto-suggests a
//      mapping based on header heuristics; the user reviews +
//      adjusts.
//   3. Submit → backend creates SyncProposal → redirect to the
//      preview page.
//
// The header preview is parsed entirely client-side so the user
// sees the mapping suggestions before any byte hits the server.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, FileSpreadsheet, Loader2, Upload } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Target = "customers" | "items";

const CUSTOMER_FIELDS: { key: string; label: string }[] = [
  { key: "legal_name", label: "Legal name" },
  { key: "tin", label: "TIN" },
  { key: "registration_number", label: "Registration number" },
  { key: "msic_code", label: "MSIC code" },
  { key: "address", label: "Address" },
  { key: "phone", label: "Phone" },
  { key: "sst_number", label: "SST number" },
  { key: "country_code", label: "Country code" },
  { key: "source_record_id", label: "Source record ID (optional)" },
];

const ITEM_FIELDS: { key: string; label: string }[] = [
  { key: "canonical_name", label: "Item name" },
  { key: "default_msic_code", label: "Default MSIC code" },
  { key: "default_classification_code", label: "Default classification code" },
  { key: "default_tax_type_code", label: "Default tax type code" },
  { key: "default_unit_of_measurement", label: "Default unit of measurement" },
  { key: "source_record_id", label: "Source record ID (optional)" },
];

// Heuristic suggestions for the auto-mapping. Conservative — the
// user always sees + can override. Keys are case-insensitive
// substrings checked against each source-CSV column header.
const HEURISTICS_CUSTOMER: Array<{ patterns: string[]; field: string }> = [
  { patterns: ["company name", "customer name", "debtor name", "name"], field: "legal_name" },
  { patterns: ["tax id", "tax_no", "tin", "tax number"], field: "tin" },
  { patterns: ["company no", "registration", "brn"], field: "registration_number" },
  { patterns: ["msic"], field: "msic_code" },
  { patterns: ["address"], field: "address" },
  { patterns: ["phone", "tel", "mobile"], field: "phone" },
  { patterns: ["sst"], field: "sst_number" },
  { patterns: ["country"], field: "country_code" },
  { patterns: ["row id", "record id", "external id", "code"], field: "source_record_id" },
];

const HEURISTICS_ITEM: Array<{ patterns: string[]; field: string }> = [
  { patterns: ["item name", "product name", "description", "name"], field: "canonical_name" },
  { patterns: ["msic"], field: "default_msic_code" },
  { patterns: ["classification"], field: "default_classification_code" },
  { patterns: ["tax type", "tax_code"], field: "default_tax_type_code" },
  { patterns: ["unit", "uom"], field: "default_unit_of_measurement" },
  { patterns: ["row id", "record id", "sku"], field: "source_record_id" },
];

function suggestMapping(headers: string[], target: Target): Record<string, string> {
  const heuristics = target === "customers" ? HEURISTICS_CUSTOMER : HEURISTICS_ITEM;
  const out: Record<string, string> = {};
  // First pass — exact-substring matches per heuristic, first
  // header that matches wins for each ZeroKey field.
  const claimed = new Set<string>();
  for (const { patterns, field } of heuristics) {
    if (claimed.has(field)) continue;
    for (const header of headers) {
      const norm = header.toLowerCase().trim();
      if (patterns.some((p) => norm.includes(p))) {
        out[header] = field;
        claimed.add(field);
        break;
      }
    }
  }
  return out;
}

export default function UploadCsvPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();

  const [target, setTarget] = useState<Target>("customers");
  const [file, setFile] = useState<File | null>(null);
  const [headers, setHeaders] = useState<string[] | null>(null);
  const [previewRows, setPreviewRows] = useState<string[][]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const targetFields = target === "customers" ? CUSTOMER_FIELDS : ITEM_FIELDS;

  async function onFileChange(picked: File | null) {
    setError(null);
    setFile(picked);
    if (!picked) {
      setHeaders(null);
      setPreviewRows([]);
      setMapping({});
      return;
    }
    try {
      const text = await picked.text();
      const lines = text.split(/\r?\n/).filter((l) => l.trim() !== "");
      if (lines.length === 0) {
        setError("CSV looks empty.");
        return;
      }
      const parsedHeaders = parseCsvLine(lines[0]);
      setHeaders(parsedHeaders);
      // First 3 data rows for preview.
      setPreviewRows(lines.slice(1, 4).map((l) => parseCsvLine(l)));
      setMapping(suggestMapping(parsedHeaders, target));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't read the file.");
    }
  }

  // Re-suggest when target switches.
  useEffect(() => {
    if (headers) {
      setMapping(suggestMapping(headers, target));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  function setMappingFor(header: string, field: string) {
    setMapping((prev) => {
      const next = { ...prev };
      if (!field) {
        delete next[header];
        return next;
      }
      // Each ZeroKey field can only be claimed once — clear any
      // other header pointing at this field.
      for (const k of Object.keys(next)) {
        if (next[k] === field && k !== header) delete next[k];
      }
      next[header] = field;
      return next;
    });
  }

  async function onSubmit() {
    if (!file) {
      setError("Pick a CSV file first.");
      return;
    }
    if (Object.keys(mapping).length === 0) {
      setError("Map at least one column before submitting.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const proposal = await api.uploadCsvSync({
        configId: params.id,
        file,
        columnMapping: mapping,
        target,
      });
      router.push(`/dashboard/connectors/proposals/${proposal.id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : "Upload failed.");
      }
      setSubmitting(false);
    }
  }

  const mappedFieldCount = useMemo(() => new Set(Object.values(mapping)).size, [mapping]);

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header>
          <Link
            href="/dashboard/connectors"
            className="inline-flex items-center gap-1 text-2xs font-medium text-slate-500 hover:text-ink"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to connectors
          </Link>
          <h1 className="mt-2 font-display text-2xl font-bold tracking-tight">Upload a CSV</h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            Two-phase sync — review what will change before any of it lands
          </p>
        </header>

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error"
          >
            {error}
          </div>
        )}

        <Section title="What are you importing?">
          <div className="flex gap-2">
            <TargetButton active={target === "customers"} onClick={() => setTarget("customers")}>
              Customers / debtors
            </TargetButton>
            <TargetButton active={target === "items"} onClick={() => setTarget("items")}>
              Items / products
            </TargetButton>
          </div>
        </Section>

        <Section title="Pick a CSV">
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => onFileChange(e.target.files?.[0] ?? null)}
            className="rounded-md border border-slate-200 bg-white px-3 py-2 text-2xs file:mr-2 file:rounded file:border-0 file:bg-slate-100 file:px-2 file:py-0.5 file:text-2xs file:text-ink"
          />
          {file && (
            <div className="text-2xs text-slate-500">
              <FileSpreadsheet className="mr-1 inline h-3.5 w-3.5" />
              {file.name} ({Math.round(file.size / 1024)} KB)
            </div>
          )}
        </Section>

        {headers && (
          <>
            <Section title="Map columns">
              <p className="text-2xs text-slate-500">
                {mappedFieldCount} of your CSV column
                {mappedFieldCount === 1 ? "" : "s"} mapped. Unmapped columns are dropped silently.
              </p>
              <div className="overflow-hidden rounded-xl border border-slate-100 bg-white">
                <table className="w-full text-2xs">
                  <thead className="bg-slate-50 text-slate-400">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                        Source column
                      </th>
                      <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                        ZeroKey field
                      </th>
                      <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                        Sample
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {headers.map((header, idx) => {
                      const sample = previewRows
                        .map((r) => r[idx] ?? "")
                        .filter((v) => v)
                        .slice(0, 1)
                        .join(" / ");
                      const current = mapping[header] ?? "";
                      return (
                        <tr key={header}>
                          <td className="px-3 py-3 font-medium text-ink">{header}</td>
                          <td className="px-3 py-3">
                            <select
                              value={current}
                              onChange={(e) => setMappingFor(header, e.target.value)}
                              className="rounded-md border border-slate-200 bg-white px-2 py-1.5 text-2xs focus:outline-none focus:ring-1 focus:ring-ink"
                            >
                              <option value="">— Don&apos;t import —</option>
                              {targetFields.map((f) => (
                                <option
                                  key={f.key}
                                  value={f.key}
                                  disabled={
                                    Object.values(mapping).includes(f.key) && current !== f.key
                                  }
                                >
                                  {f.label}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td className="px-3 py-3 text-slate-500">{sample || "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Section>

            <Section title="Sample data">
              <div className="overflow-hidden rounded-xl border border-slate-100 bg-white">
                <table className="w-full text-2xs">
                  <thead className="bg-slate-50 text-slate-400">
                    <tr>
                      {headers.map((h) => (
                        <th
                          key={h}
                          className="px-3 py-2 text-left font-medium uppercase tracking-wider"
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {previewRows.map((row, idx) => (
                      <tr key={idx}>
                        {row.map((cell, ci) => (
                          <td key={ci} className="px-3 py-2 text-slate-600">
                            {cell || "—"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>

            <div className="flex items-center justify-end gap-2">
              <Link
                href="/dashboard/connectors"
                className="inline-flex items-center rounded-md px-3 py-1.5 text-2xs font-medium text-slate-500 hover:bg-slate-100 hover:text-ink"
              >
                Cancel
              </Link>
              <Button size="sm" onClick={onSubmit} disabled={submitting || mappedFieldCount === 0}>
                {submitting ? (
                  <>
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    Building proposal…
                  </>
                ) : (
                  <>
                    <Upload className="mr-1.5 h-3.5 w-3.5" />
                    Build sync proposal
                  </>
                )}
              </Button>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}

function TargetButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-md border px-3 py-2 text-2xs font-medium transition",
        active
          ? "border-ink bg-ink/[0.05] text-ink"
          : "border-slate-200 bg-white text-slate-500 hover:border-slate-300",
      )}
    >
      {children}
    </button>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

// Minimal RFC-4180-flavoured CSV line parser. Handles quoted
// fields with embedded commas + escaped quotes. Sufficient for the
// preview; the backend uses Python's csv module for the real parse.
function parseCsvLine(line: string): string[] {
  const out: string[] = [];
  let buf = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          buf += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        buf += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      out.push(buf);
      buf = "";
    } else {
      buf += ch;
    }
  }
  out.push(buf);
  return out.map((s) => s.trim());
}
