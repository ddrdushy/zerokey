"use client";

// Slice 85 — AutoCount upload.
//
// Single step: pick a file, choose target (customers / items),
// upload. The backend adapter applies AutoCount's standard column
// mapping — no wizard. Customers with customised AutoCount
// installations should fall back to the generic CSV connector.

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Database, Loader2, Upload } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Target = "customers" | "items";

export default function UploadAutoCountPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [target, setTarget] = useState<Target>("customers");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit() {
    if (!file) return;
    setSubmitting(true);
    setError(null);
    try {
      const proposal = await api.uploadAutoCountSync({
        configId: params.id,
        file,
        target,
      });
      router.push(`/dashboard/connectors/proposals/${proposal.id}`);
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
            <h1 className="font-display text-2xl font-bold tracking-tight">AutoCount upload</h1>
            <p className="mt-1 text-2xs text-slate-500">
              Export your debtor list or stock items from AutoCount (File → Export → CSV) and upload
              it here. ZeroKey reads the standard AutoCount column headers — no mapping needed.
            </p>
          </div>
        </header>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-ink">1. What are you uploading?</h2>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setTarget("customers")}
              className={cn(
                "rounded-md border px-3 py-2 text-2xs font-medium transition",
                target === "customers"
                  ? "border-ink bg-ink text-paper"
                  : "border-slate-200 text-slate-600 hover:border-slate-300",
              )}
            >
              Debtor List (customers)
            </button>
            <button
              type="button"
              onClick={() => setTarget("items")}
              className={cn(
                "rounded-md border px-3 py-2 text-2xs font-medium transition",
                target === "items"
                  ? "border-ink bg-ink text-paper"
                  : "border-slate-200 text-slate-600 hover:border-slate-300",
              )}
            >
              Stock Items
            </button>
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-ink">2. Upload the CSV</h2>
          <label
            htmlFor="autocount-file"
            className="flex cursor-pointer items-center gap-3 rounded-xl border-2 border-dashed border-slate-200 bg-white px-4 py-8 text-center text-2xs text-slate-500 hover:border-slate-300"
          >
            <Upload className="h-4 w-4 text-slate-400" />
            {file ? <span className="text-ink">{file.name}</span> : <span>Click to choose…</span>}
            <input
              id="autocount-file"
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <p className="text-2xs text-slate-400">
            Standard AutoCount export columns are matched automatically (Account No, Company Name,
            Tax Reg. No, BRN No, Address 1, Phone 1, Country Code; Item Code, Description, UOM,
            Standard Cost, Tax Code, MSIC Code).
          </p>
        </section>

        {error && (
          <div className="rounded-md border border-error bg-error/5 px-4 py-2 text-2xs text-error">
            {error}
          </div>
        )}

        <div className="flex justify-end">
          <Button onClick={onSubmit} disabled={!file || submitting}>
            {submitting ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Proposing…
              </>
            ) : (
              "Propose changes"
            )}
          </Button>
        </div>
      </div>
    </AppShell>
  );
}
