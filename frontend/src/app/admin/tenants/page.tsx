"use client";

// Tenant directory — every Organization on the platform with member +
// activity counts. The first triage surface a platform operator looks
// at when something goes wrong: "show me everyone, narrow by name or
// TIN, see who's idle vs active." Clicking through into the audit log
// for a specific tenant lands as a follow-up gesture from this page.
//
// Cross-tenant read; the list call audits itself as
// admin.platform_tenants_listed (with the search term in the payload).

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Search, Users } from "lucide-react";

import {
  api,
  type PlatformTenant,
} from "@/lib/api";
import { AdminShell } from "@/components/admin/AdminShell";

export default function TenantDirectoryPage() {
  const [tenants, setTenants] = useState<PlatformTenant[] | null>(null);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Debounce so typing doesn't fire a query per keystroke.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    let cancelled = false;
    setTenants(null);
    setError(null);
    api
      .adminListTenants({
        search: debouncedSearch || undefined,
        limit: 200,
      })
      .then((response) => {
        if (cancelled) return;
        setTenants(response);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load.");
        setTenants([]);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedSearch]);

  // Sort active tenants (recent uploads) above idle ones. Same legal-name
  // alphabetical within the activity group.
  const sorted = useMemo(() => {
    if (!tenants) return null;
    return [...tenants].sort((a, b) => {
      if (a.ingestion_jobs_recent_7d !== b.ingestion_jobs_recent_7d) {
        return b.ingestion_jobs_recent_7d - a.ingestion_jobs_recent_7d;
      }
      return a.legal_name.localeCompare(b.legal_name);
    });
  }, [tenants]);

  return (
    <AdminShell>
      <div className="flex flex-col gap-6">
        <header className="flex items-end justify-between">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">
              Tenants
            </h1>
            <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
              Every Organization on the platform · cross-tenant
            </p>
          </div>
          {tenants && (
            <div className="rounded-md bg-slate-100 px-3 py-1.5 text-2xs text-slate-600">
              <span className="inline-flex items-center gap-1.5">
                <Users className="h-3.5 w-3.5" />
                <span className="font-medium">{tenants.length}</span>
                <span>
                  tenant{tenants.length === 1 ? "" : "s"}
                  {debouncedSearch && " match"}
                </span>
              </span>
            </div>
          )}
        </header>

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error"
          >
            {error}
          </div>
        )}

        <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 max-w-md">
          <Search className="h-4 w-4 text-slate-400" aria-hidden />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or TIN…"
            className="h-6 flex-1 bg-transparent text-2xs text-ink placeholder-slate-400 outline-none"
            aria-label="Search tenants"
          />
        </div>

        {sorted === null ? (
          <Empty>Loading…</Empty>
        ) : sorted.length === 0 ? (
          <EmptyState filtered={!!debouncedSearch} />
        ) : (
          <TenantTable tenants={sorted} />
        )}
      </div>
    </AdminShell>
  );
}

function TenantTable({ tenants }: { tenants: PlatformTenant[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-100 bg-white">
      <table className="w-full text-2xs">
        <thead className="bg-slate-50 text-slate-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Legal name
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              TIN
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              State
            </th>
            <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
              Members
            </th>
            <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
              Uploads
            </th>
            <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
              Last 7d
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Last activity
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Audit
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {tenants.map((t) => (
            <tr key={t.id} className="hover:bg-slate-50">
              <td className="px-3 py-3">
                <div className="font-medium text-ink">{t.legal_name}</div>
                <div className="text-[10px] text-slate-400">
                  {t.contact_email || "—"}
                </div>
              </td>
              <td className="px-3 py-3">
                <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
                  {t.tin}
                </code>
              </td>
              <td className="px-3 py-3">
                <StateBadge state={t.subscription_state} />
              </td>
              <td className="px-3 py-3 text-right text-slate-600">
                {t.member_count}
              </td>
              <td className="px-3 py-3 text-right text-slate-600">
                {t.ingestion_jobs_total}
              </td>
              <td className="px-3 py-3 text-right">
                <span
                  className={
                    t.ingestion_jobs_recent_7d > 0
                      ? "font-medium text-success"
                      : "text-slate-400"
                  }
                >
                  {t.ingestion_jobs_recent_7d}
                </span>
              </td>
              <td className="px-3 py-3 text-slate-500">
                {t.last_activity_at
                  ? formatRelative(t.last_activity_at)
                  : "—"}
              </td>
              <td className="px-3 py-3">
                <Link
                  href={`/admin/tenants/${t.id}`}
                  className="text-2xs font-medium text-ink underline-offset-4 hover:underline"
                >
                  Open →
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StateBadge({ state }: { state: string }) {
  const tone = state === "active" ? "success" : state === "trial" ? "signal" : "slate";
  const cls =
    tone === "success"
      ? "bg-success/10 text-success"
      : tone === "signal"
        ? "bg-signal/15 text-ink"
        : "bg-slate-100 text-slate-500";
  return (
    <span
      className={`inline-flex rounded-sm px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${cls}`}
    >
      {state || "—"}
    </span>
  );
}

function EmptyState({ filtered }: { filtered: boolean }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-12 text-center">
      <Users className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
      <h2 className="mt-4 font-display text-xl font-semibold">
        {filtered ? "No matching tenants" : "No tenants yet"}
      </h2>
      <p className="mx-auto mt-2 max-w-md text-2xs text-slate-500">
        {filtered
          ? "Try a shorter substring, or clear the search."
          : "Tenants appear here once they sign up at /sign-up."}
      </p>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid place-items-center py-24 text-2xs uppercase tracking-wider text-slate-400">
      {children}
    </div>
  );
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "recently";
  const diffSec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (diffSec < 60) return "just now";
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  const diffMon = Math.round(diffDay / 30);
  return `${diffMon}mo ago`;
}
