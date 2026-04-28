"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { api, ApiError, type IngestionJob, type Invoice } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { AppShell } from "@/components/shell/AppShell";

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
        // Try to fetch the structured invoice if it exists. 404 is fine —
        // structuring may still be in flight or the engine was unavailable.
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

  if (loading) {
    return <Pad>Loading…</Pad>;
  }
  if (error) {
    return <Pad>{error}</Pad>;
  }
  if (!job) {
    return <Pad>Not found.</Pad>;
  }

  return (
    <AppShell>
    <div className="mx-auto flex max-w-4xl flex-col gap-8">
      <div className="flex items-center justify-between">
        <div>
          <Button variant="ghost" size="sm" onClick={() => router.push("/dashboard")}>
            ← Dashboard
          </Button>
          <h1 className="mt-2 font-display text-2xl font-bold tracking-tight">
            {job.original_filename}
          </h1>
        </div>
        <StatusPill status={job.status} />
      </div>

      <section className="grid gap-4 md:grid-cols-2">
        <Card label="Source">{job.source_channel}</Card>
        <Card label="Size">{(job.file_size / 1024).toFixed(1)} KB</Card>
        <Card label="Engine">{job.extraction_engine || "—"}</Card>
        <Card label="Confidence">
          {job.extraction_confidence != null
            ? `${(job.extraction_confidence * 100).toFixed(0)}%`
            : "—"}
        </Card>
      </section>

      {job.error_message && (
        <section
          role="alert"
          className="rounded-md border border-error bg-error/5 px-4 py-3 text-xs text-error"
        >
          <div className="font-medium">Extraction error</div>
          <div className="mt-1">{job.error_message}</div>
        </section>
      )}

      {invoice && <InvoiceCard invoice={invoice} />}

      {job.extracted_text && (
        <section>
          <h2 className="text-xl font-semibold">Extracted text</h2>
          <pre className="mt-3 max-h-96 overflow-auto rounded-md border border-slate-100 bg-slate-50 p-4 font-mono text-2xs leading-relaxed text-slate-600">
            {job.extracted_text}
          </pre>
        </section>
      )}

      {job.state_transitions && job.state_transitions.length > 0 && (
        <section>
          <h2 className="text-xl font-semibold">State history</h2>
          <ul className="mt-3 divide-y divide-slate-100 border-y border-slate-100">
            {job.state_transitions.map((t, idx) => (
              <li key={idx} className="flex items-center justify-between py-2 text-2xs">
                <span className="font-medium uppercase tracking-wider text-slate-600">
                  {t.status.replace(/_/g, " ")}
                </span>
                <span className="text-slate-400">{new Date(t.at).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {job.download_url && (
        <section>
          <a
            href={job.download_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-medium text-ink underline-offset-4 hover:underline"
          >
            Download original (link expires in 5 minutes)
          </a>
        </section>
      )}
    </div>
    </AppShell>
  );
}

function Pad({ children }: { children: React.ReactNode }) {
  return (
    <AppShell>
      <div className="grid place-items-center py-24 text-slate-400">{children}</div>
    </AppShell>
  );
}

function Card({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-4">
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-1 text-base">{children}</div>
    </div>
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


function InvoiceCard({ invoice }: { invoice: Invoice }) {
  const hasAnyField =
    invoice.invoice_number ||
    invoice.supplier_legal_name ||
    invoice.buyer_legal_name ||
    invoice.grand_total;

  return (
    <section>
      <div className="flex items-baseline justify-between">
        <h2 className="text-xl font-semibold">Structured invoice</h2>
        {invoice.overall_confidence != null && (
          <span className="text-2xs uppercase tracking-wider text-slate-400">
            confidence {(invoice.overall_confidence * 100).toFixed(0)}% ·{" "}
            {invoice.structuring_engine || "—"}
          </span>
        )}
      </div>

      {!hasAnyField && (
        <p className="mt-3 text-base text-slate-400">
          {invoice.error_message ||
            "No fields populated. Auto-structuring may have been skipped or the document didn't contain recognised invoice text."}
        </p>
      )}

      {hasAnyField && (
        <>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <Field label="Invoice number" value={invoice.invoice_number} />
            <Field
              label="Issue date"
              value={invoice.issue_date ? new Date(invoice.issue_date).toLocaleDateString() : ""}
            />
            <Field label="Currency" value={invoice.currency_code} />
            <Field
              label="Grand total"
              value={invoice.grand_total ? `${invoice.currency_code} ${invoice.grand_total}` : ""}
            />
          </div>

          <div className="mt-6 grid gap-4 md:grid-cols-2">
            <Party
              label="Supplier"
              name={invoice.supplier_legal_name}
              tin={invoice.supplier_tin}
              address={invoice.supplier_address}
            />
            <Party
              label="Buyer"
              name={invoice.buyer_legal_name}
              tin={invoice.buyer_tin}
              address={invoice.buyer_address}
            />
          </div>

          {invoice.line_items.length > 0 && (
            <div className="mt-6 overflow-hidden rounded-xl border border-slate-100">
              <table className="w-full text-2xs">
                <thead className="bg-slate-50 text-slate-400">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">#</th>
                    <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                      Description
                    </th>
                    <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                      Qty
                    </th>
                    <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                      Unit price
                    </th>
                    <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                      Tax
                    </th>
                    <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                      Total
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {invoice.line_items.map((line) => (
                    <tr key={line.id}>
                      <td className="px-3 py-2 text-slate-400">{line.line_number}</td>
                      <td className="px-3 py-2">{line.description}</td>
                      <td className="px-3 py-2 text-right font-mono">{line.quantity ?? "—"}</td>
                      <td className="px-3 py-2 text-right font-mono">
                        {line.unit_price_excl_tax ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {line.tax_amount ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {line.line_total_incl_tax ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-4">
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-1 text-base">{value || <span className="text-slate-400">—</span>}</div>
    </div>
  );
}

function Party({
  label,
  name,
  tin,
  address,
}: {
  label: string;
  name: string;
  tin: string;
  address: string;
}) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-4">
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-2 text-base font-medium">{name || <span className="text-slate-400">—</span>}</div>
      {tin && <div className="font-mono text-2xs text-slate-600">TIN {tin}</div>}
      {address && <div className="mt-1 text-2xs text-slate-600 whitespace-pre-line">{address}</div>}
    </div>
  );
}
