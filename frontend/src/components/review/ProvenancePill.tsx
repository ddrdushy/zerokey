"use client";

// Slice 73 — per-field provenance pill on the Customers / Items
// detail pages.
//
// Reads ``CustomerMaster.field_provenance[fieldName]`` (or
// ``ItemMaster.field_provenance[fieldName]``) and renders a small
// pill beneath the field row that says where the value came from:
// extracted from an invoice, entered manually, synced from an
// accounting system, or manually resolved in the conflict queue.
//
// Distinct from the confidence dot on FieldRow itself (which says
// "how sure was the LLM"). Provenance answers a different
// question: "where did this value originate?". Both can coexist on
// the same field — a synced TIN that's also LHDN-verified shows the
// "from AutoCount" pill here and the verified state in the
// VerificationCard alongside.

import type { FieldProvenanceEntry, FieldProvenanceSource } from "@/lib/api";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "synced" | "manual" | "resolved";

const SOURCE_COPY: Record<FieldProvenanceSource, { label: string; tone: Tone }> = {
  extracted: { label: "Extracted from invoice", tone: "neutral" },
  manual: { label: "Entered manually", tone: "manual" },
  manually_resolved: { label: "Manually resolved", tone: "resolved" },
  synced_csv: { label: "From CSV import", tone: "synced" },
  synced_autocount: { label: "From AutoCount", tone: "synced" },
  synced_sql_accounting: { label: "From SQL Accounting", tone: "synced" },
  synced_xero: { label: "From Xero", tone: "synced" },
  synced_quickbooks: { label: "From QuickBooks", tone: "synced" },
  synced_shopify: { label: "From Shopify", tone: "synced" },
  synced_woocommerce: { label: "From WooCommerce", tone: "synced" },
};

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-500",
  synced: "bg-signal/10 text-ink",
  manual: "bg-amber-50 text-amber-700",
  resolved: "bg-success/10 text-success",
};

function deriveTimestamp(entry: FieldProvenanceEntry): string | null {
  // Prefer the most specific timestamp — `synced_at` for synced
  // sources, `entered_at` for manual, `extracted_at` for
  // extracted. The first one present wins.
  return entry.synced_at ?? entry.entered_at ?? entry.extracted_at ?? null;
}

export function ProvenancePill({ entry }: { entry: FieldProvenanceEntry | undefined | null }) {
  if (!entry) return null;
  const copy = (SOURCE_COPY as Record<string, { label: string; tone: Tone }>)[entry.source] ?? {
    // Forward-compat: an unknown source key (server adds a new
    // connector before the FE bundle ships) renders generically
    // rather than crashing.
    label: "Source recorded",
    tone: "neutral" as const,
  };
  const ts = deriveTimestamp(entry);
  return (
    <div
      className={cn(
        "mt-1.5 inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[10px] font-medium",
        TONE_CLASSES[copy.tone],
      )}
      title={ts ? `${copy.label} · ${new Date(ts).toLocaleString()}` : copy.label}
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current opacity-50" />
      <span>{copy.label}</span>
    </div>
  );
}
