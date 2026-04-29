"use client";

// Exception Inbox page.
//
// The triage queue per DATA_MODEL.md "exception inbox entities". Auto-
// populated as the pipeline detects invoices needing human attention
// (validation errors today; structuring-skipped + LHDN-rejection +
// low-confidence + manual review wire in as their pipelines mature).
// Auto-resolved when the underlying condition clears (e.g. user fixes
// a validation issue and re-validates).
//
// What this page does NOT show: resolved items. Triage is forward-
// looking — once an item is dealt with it falls out of view, but the
// audit log preserves the full lifecycle. A "show resolved" toggle is
// a follow-up if customers want a recovery surface.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircle, CheckCircle2, Inbox as InboxIcon, Sparkles } from "lucide-react";

import { api, ApiError, type InboxItem } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const REASON_LABEL: Record<InboxItem["reason"], string> = {
  validation_failure: "Validation failure",
  structuring_skipped: "Structuring skipped",
  low_confidence_extraction: "Low-confidence extraction",
  lhdn_rejection: "Rejected by LHDN",
  manual_review_requested: "Manual review requested",
};

const REASON_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "All reasons" },
  ...Object.entries(REASON_LABEL).map(([value, label]) => ({ value, label })),
];

export default function InboxPage() {
  const router = useRouter();
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [reason, setReason] = useState("");
  const [resolving, setResolving] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setError(null);
    api
      .listInbox({ reason: reason || undefined })
      .then((response) => {
        if (cancelled) return;
        setItems(response.results);
        setTotal(response.total);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/sign-in");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load inbox.");
        setItems([]);
      });
    return () => {
      cancelled = true;
    };
  }, [reason, router]);

  async function onResolve(item: InboxItem) {
    setResolving((prev) => ({ ...prev, [item.id]: true }));
    setError(null);
    try {
      await api.resolveInboxItem(item.id);
      // Optimistic-ish: refresh the list so the resolved item drops out
      // and the count + ordering reflect the change. Cheap relative to
      // expected list size.
      const response = await api.listInbox({ reason: reason || undefined });
      setItems(response.results);
      setTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Resolve failed.");
    } finally {
      setResolving((prev) => {
        const next = { ...prev };
        delete next[item.id];
        return next;
      });
    }
  }

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header className="flex items-end justify-between">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">Inbox</h1>
            <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
              Invoices that need a human look
            </p>
          </div>
          <CountBadge total={total} />
        </header>

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error"
          >
            {error}
          </div>
        )}

        <FilterBar value={reason} onChange={setReason} />

        {items === null ? (
          <Loading>Loading…</Loading>
        ) : items.length === 0 ? (
          <EmptyState filtered={!!reason} />
        ) : (
          <InboxTable items={items} resolving={resolving} onResolve={onResolve} />
        )}
      </div>
    </AppShell>
  );
}

function CountBadge({ total }: { total: number }) {
  const tone = total === 0 ? "bg-success/10 text-success" : "bg-warning/10 text-warning";
  const Icon = total === 0 ? CheckCircle2 : AlertCircle;
  return (
    <div className={cn("rounded-md px-3 py-1.5 text-2xs", tone)}>
      <span className="inline-flex items-center gap-1.5">
        <Icon className="h-3.5 w-3.5" />
        <span className="font-medium">{total.toLocaleString()}</span>
        <span>open item{total === 1 ? "" : "s"}</span>
      </span>
    </div>
  );
}

function FilterBar({ value, onChange }: { value: string; onChange: (next: string) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        Filter by reason
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink"
      >
        {REASON_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          className="text-2xs text-slate-500 underline-offset-4 hover:text-ink hover:underline"
        >
          Clear filter
        </button>
      )}
    </div>
  );
}

function InboxTable({
  items,
  resolving,
  onResolve,
}: {
  items: InboxItem[];
  resolving: Record<string, boolean>;
  onResolve: (item: InboxItem) => void;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-100 bg-white">
      <table className="w-full text-2xs">
        <thead className="bg-slate-50 text-slate-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Reason</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Invoice</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Buyer</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Detail</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Created</th>
            <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((item) => (
            <tr key={item.id} className="hover:bg-slate-50">
              <td className="px-3 py-3">
                <ReasonBadge reason={item.reason} priority={item.priority} />
              </td>
              <td className="px-3 py-3">
                <Link
                  href={`/dashboard/jobs/${item.ingestion_job_id}`}
                  className="font-medium text-ink hover:underline"
                >
                  {item.invoice_number || <span className="text-slate-400">no number</span>}
                </Link>
                <div className="mt-0.5 text-slate-400">
                  {item.invoice_status.replace(/_/g, " ")}
                </div>
              </td>
              <td className="px-3 py-3 text-slate-600">
                {item.buyer_legal_name || <span className="text-slate-400">—</span>}
              </td>
              <td className="px-3 py-3 text-slate-600">
                <DetailSummary detail={item.detail} reason={item.reason} />
              </td>
              <td className="px-3 py-3 text-slate-600">
                {new Date(item.created_at).toLocaleString()}
              </td>
              <td className="px-3 py-3 text-right">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onResolve(item)}
                  disabled={!!resolving[item.id]}
                >
                  {resolving[item.id] ? "Resolving…" : "Mark resolved"}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReasonBadge({
  reason,
  priority,
}: {
  reason: InboxItem["reason"];
  priority: InboxItem["priority"];
}) {
  const urgent = priority === "urgent";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-medium",
        urgent ? "bg-error/10 text-error" : "bg-warning/10 text-warning",
      )}
    >
      <Sparkles className="h-3 w-3" />
      {REASON_LABEL[reason]}
    </span>
  );
}

function DetailSummary({
  detail,
  reason,
}: {
  detail: Record<string, unknown>;
  reason: InboxItem["reason"];
}) {
  // Reason-specific renderings of the detail JSON. Falls back to a
  // pretty-printed snapshot for reasons we haven't explicitly handled
  // — keeps new reasons visible even before the UI knows about them.
  if (reason === "validation_failure") {
    const errors = typeof detail.errors === "number" ? detail.errors : null;
    const warnings = typeof detail.warnings === "number" ? detail.warnings : null;
    if (errors == null && warnings == null) return <Muted>—</Muted>;
    return (
      <span>
        {errors !== null && (
          <span className="text-error">
            {errors} error{errors === 1 ? "" : "s"}
          </span>
        )}
        {warnings ? (
          <>
            {errors !== null && <span className="text-slate-400"> · </span>}
            <span className="text-warning">
              {warnings} warning{warnings === 1 ? "" : "s"}
            </span>
          </>
        ) : null}
      </span>
    );
  }
  if (reason === "structuring_skipped") {
    const text = typeof detail.reason === "string" ? detail.reason : "no detail";
    return <span className="line-clamp-2 max-w-xs text-slate-600">{text}</span>;
  }
  if (Object.keys(detail).length === 0) return <Muted>—</Muted>;
  return <code className="text-[11px] text-slate-500">{JSON.stringify(detail)}</code>;
}

function Muted({ children }: { children: React.ReactNode }) {
  return <span className="text-slate-400">{children}</span>;
}

function EmptyState({ filtered }: { filtered: boolean }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-12 text-center">
      <InboxIcon className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
      <h2 className="mt-4 font-display text-xl font-semibold">
        {filtered ? "No items match this reason" : "Inbox zero"}
      </h2>
      <p className="mx-auto mt-2 max-w-md text-2xs text-slate-500">
        {filtered
          ? "Try a different reason or clear the filter to see everything."
          : "Nothing needs your attention right now. Items appear here as soon as the pipeline flags an invoice — validation failures, structuring issues, LHDN rejections."}
      </p>
    </div>
  );
}

function Loading({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid place-items-center py-12 text-2xs uppercase tracking-wider text-slate-400">
      {children}
    </div>
  );
}
