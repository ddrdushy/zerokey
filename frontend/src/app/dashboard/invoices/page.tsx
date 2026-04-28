"use client";

// All-invoices list. Different shape from the dashboard's "recent
// uploads" excerpt: filterable by status + free-text search across
// invoice number / buyer name / buyer TIN, cursor-paginated. Each row
// links to the existing review screen via the ingestion job id.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FileText, Search } from "lucide-react";

import {
  api,
  ApiError,
  type InvoiceListSummary,
} from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";

const PAGE_SIZE = 50;

// Status options for the filter dropdown. Matches Invoice.Status on the
// backend; "" is the "All" entry. Hard-coded because the set of statuses
// is enumerated server-side and changes only when the state machine
// evolves (a deliberate, code-reviewed change).
const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "All statuses" },
  { value: "extracting", label: "Extracting" },
  { value: "enriching", label: "Enriching" },
  { value: "validating", label: "Validating" },
  { value: "ready_for_review", label: "Ready for review" },
  { value: "awaiting_approval", label: "Awaiting approval" },
  { value: "signing", label: "Signing" },
  { value: "submitting", label: "Submitting" },
  { value: "validated", label: "Validated by LHDN" },
  { value: "rejected", label: "Rejected by LHDN" },
  { value: "cancelled", label: "Cancelled" },
  { value: "error", label: "Error" },
];

export default function InvoicesListPage() {
  const router = useRouter();
  const [invoices, setInvoices] = useState<InvoiceListSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initial / filter-change load.
  useEffect(() => {
    let cancelled = false;
    setInvoices(null);
    setError(null);
    api
      .listInvoices({
        status: statusFilter || undefined,
        search: activeSearch || undefined,
        limit: PAGE_SIZE,
      })
      .then((response) => {
        if (cancelled) return;
        setInvoices(response.results);
        setTotal(response.total);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/sign-in");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load invoices.");
        setInvoices([]);
      });
    return () => {
      cancelled = true;
    };
  }, [statusFilter, activeSearch, router]);

  function onApplySearch() {
    setActiveSearch(searchInput.trim());
  }

  function onClearSearch() {
    setSearchInput("");
    setActiveSearch("");
  }

  async function onLoadMore() {
    if (!invoices || invoices.length === 0) return;
    setLoadingMore(true);
    try {
      const cursor = invoices[invoices.length - 1].created_at;
      const response = await api.listInvoices({
        status: statusFilter || undefined,
        search: activeSearch || undefined,
        limit: PAGE_SIZE,
        beforeCreatedAt: cursor,
      });
      setInvoices((prev) => [...(prev ?? []), ...response.results]);
      setTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load more.");
    } finally {
      setLoadingMore(false);
    }
  }

  const hasMore = useMemo(() => {
    if (!invoices) return false;
    if (statusFilter || activeSearch) {
      // Filtered: we don't know the filtered total, so use page-size
      // fullness as a proxy. Better than guessing zero.
      return invoices.length > 0 && invoices.length % PAGE_SIZE === 0;
    }
    return invoices.length < total;
  }, [invoices, total, statusFilter, activeSearch]);

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header className="flex items-end justify-between">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">
              Invoices
            </h1>
            <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
              Every invoice your organization has produced
            </p>
          </div>
          <span className="text-2xs uppercase tracking-wider text-slate-400">
            {total.toLocaleString()} total
          </span>
        </header>

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error"
          >
            {error}
          </div>
        )}

        <FilterBar
          statusFilter={statusFilter}
          onChangeStatus={setStatusFilter}
          searchInput={searchInput}
          onChangeSearch={setSearchInput}
          activeSearch={activeSearch}
          onApplySearch={onApplySearch}
          onClearSearch={onClearSearch}
        />

        {invoices === null ? (
          <Loading>Loading…</Loading>
        ) : invoices.length === 0 ? (
          <EmptyState filtered={!!(statusFilter || activeSearch)} />
        ) : (
          <>
            <InvoiceTable invoices={invoices} />
            {hasMore && (
              <div className="flex justify-center">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onLoadMore}
                  disabled={loadingMore}
                >
                  {loadingMore ? "Loading…" : "Load more"}
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}

function FilterBar({
  statusFilter,
  onChangeStatus,
  searchInput,
  onChangeSearch,
  activeSearch,
  onApplySearch,
  onClearSearch,
}: {
  statusFilter: string;
  onChangeStatus: (next: string) => void;
  searchInput: string;
  onChangeSearch: (next: string) => void;
  activeSearch: string;
  onApplySearch: () => void;
  onClearSearch: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <select
        value={statusFilter}
        onChange={(e) => onChangeStatus(e.target.value)}
        className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink"
      >
        {STATUS_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      <div className="flex flex-1 min-w-[200px] items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-1.5">
        <Search className="h-3.5 w-3.5 text-slate-400" aria-hidden />
        <input
          type="search"
          placeholder="Search by invoice number, buyer name, or TIN"
          value={searchInput}
          onChange={(e) => onChangeSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onApplySearch();
          }}
          className="flex-1 bg-transparent text-2xs text-ink placeholder-slate-400 outline-none"
          aria-label="Search invoices"
        />
        {searchInput && (
          <button
            type="button"
            onClick={onApplySearch}
            className="text-2xs font-medium text-ink hover:underline"
          >
            Search
          </button>
        )}
      </div>

      {(statusFilter || activeSearch) && (
        <button
          type="button"
          onClick={() => {
            onChangeStatus("");
            onClearSearch();
          }}
          className="text-2xs text-slate-500 underline-offset-4 hover:text-ink hover:underline"
        >
          Clear filters
        </button>
      )}
    </div>
  );
}

function InvoiceTable({ invoices }: { invoices: InvoiceListSummary[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-100 bg-white">
      <table className="w-full text-2xs">
        <thead className="bg-slate-50 text-slate-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Invoice
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Buyer
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Issue date
            </th>
            <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
              Grand total
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Status
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {invoices.map((invoice) => (
            <tr key={invoice.id} className="hover:bg-slate-50">
              <td className="px-3 py-3">
                <Link
                  href={`/dashboard/jobs/${invoice.ingestion_job_id}`}
                  className="font-medium text-ink hover:underline"
                >
                  {invoice.invoice_number || (
                    <span className="text-slate-400">no number</span>
                  )}
                </Link>
              </td>
              <td className="px-3 py-3">
                {invoice.buyer_legal_name || (
                  <span className="text-slate-400">—</span>
                )}
                {invoice.buyer_tin && (
                  <div className="mt-0.5 font-mono text-2xs text-slate-400">
                    {invoice.buyer_tin}
                  </div>
                )}
              </td>
              <td className="px-3 py-3 text-slate-600">
                {invoice.issue_date
                  ? new Date(invoice.issue_date).toLocaleDateString()
                  : "—"}
              </td>
              <td className="px-3 py-3 text-right font-mono">
                {invoice.grand_total
                  ? `${invoice.currency_code} ${invoice.grand_total}`
                  : "—"}
              </td>
              <td className="px-3 py-3">
                <StatusPill status={invoice.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status === "validated"
      ? "bg-success/10 text-success"
      : status === "ready_for_review"
        ? "bg-success/10 text-success"
        : status === "error" || status === "rejected" || status === "cancelled"
          ? "bg-error/10 text-error"
          : "bg-slate-100 text-slate-600";
  return (
    <span
      className={[
        "inline-block rounded-full px-2 py-0.5 text-[10px] font-medium",
        tone,
      ].join(" ")}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function EmptyState({ filtered }: { filtered: boolean }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-12 text-center">
      <FileText className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
      <h2 className="mt-4 font-display text-xl font-semibold">
        {filtered ? "No invoices match these filters" : "No invoices yet"}
      </h2>
      <p className="mx-auto mt-2 max-w-md text-2xs text-slate-500">
        {filtered
          ? "Try a different status or search term, or clear the filters to see everything."
          : "Drop an invoice on the dashboard. As soon as it's extracted, it appears here."}
      </p>
      {!filtered && (
        <Link
          href="/dashboard"
          className="mt-6 inline-block text-2xs font-medium text-ink underline-offset-4 hover:underline"
        >
          Drop your first invoice →
        </Link>
      )}
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
