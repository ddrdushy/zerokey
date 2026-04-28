"use client";

// Admin overview — the operator's first-glance surface.
//
// Pulls platform-wide KPIs from /api/v1/admin/overview/ and renders
// them as compact cards. Each card is a link into the detail page
// behind it (audit, tenants, engines), so the overview doubles as the
// site map for the admin namespace.

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CircleCheck,
  FileText,
  Inbox,
  ScrollText,
  Settings,
  ShieldAlert,
  Users,
} from "lucide-react";

import { api, ApiError, type PlatformOverview } from "@/lib/api";
import { AdminShell } from "@/components/admin/AdminShell";
import { cn } from "@/lib/utils";

export default function AdminOverviewPage() {
  const [overview, setOverview] = useState<PlatformOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .adminOverview()
      .then((response) => {
        if (cancelled) return;
        setOverview(response);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          // AdminShell already handles this; ignore here.
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load overview.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AdminShell>
      <div className="flex flex-col gap-8">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Platform overview
          </h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            Cross-tenant snapshot · live from the audit chain
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

        {overview === null && !error ? (
          <Loading />
        ) : overview === null ? null : (
          <>
            <KPIGrid overview={overview} />
            <section>
              <h2 className="text-2xs font-medium uppercase tracking-wider text-slate-400">
                Engine activity (last 7 days)
              </h2>
              <EngineHealthTable rows={overview.engines.calls_last_7d} />
            </section>
          </>
        )}
      </div>
    </AdminShell>
  );
}

function KPIGrid({ overview }: { overview: PlatformOverview }) {
  const inboxAlert = overview.inbox.open > 0;
  const enginesDegraded = overview.engines.degraded > 0;

  return (
    <section className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
      <KPICard
        href="/admin/tenants"
        label="Tenants"
        icon={Users}
        primary={overview.tenants.total}
        secondary={`${overview.tenants.active_last_7d} active in last 7d`}
      />
      <KPICard
        href="/admin/audit?action_type=ingestion.job.extracted"
        label="Ingestion jobs"
        icon={FileText}
        primary={overview.ingestion.total}
        secondary={`${overview.ingestion.last_24h} in last 24h · ${overview.ingestion.last_7d} in last 7d`}
      />
      <KPICard
        href="/admin/audit?action_type=invoice.created"
        label="Invoices"
        icon={CircleCheck}
        primary={overview.invoices.total}
        secondary={`${overview.invoices.pending_review} pending review`}
      />
      <KPICard
        href="/admin/audit?action_type=inbox.item_opened"
        label="Open inbox"
        icon={Inbox}
        primary={overview.inbox.open}
        secondary={
          inboxAlert
            ? `${overview.inbox.open} item${overview.inbox.open === 1 ? "" : "s"} need attention`
            : "Everything resolved across the platform"
        }
        tone={inboxAlert ? "warning" : "success"}
      />
      <KPICard
        href="/admin/audit"
        label="Audit chain"
        icon={ScrollText}
        primary={overview.audit.total}
        secondary={`${overview.audit.last_24h} events in last 24h`}
      />
      <KPICard
        href="/admin/engines"
        label="Engines"
        icon={Settings}
        primary={overview.engines.total}
        secondary={
          enginesDegraded
            ? `${overview.engines.degraded} degraded · ${overview.engines.active} active`
            : `${overview.engines.active} active · ${overview.engines.archived} archived`
        }
        tone={enginesDegraded ? "warning" : undefined}
      />
      <KPICard
        href="/admin/tenants"
        label="Users"
        icon={Users}
        primary={overview.users.total}
        secondary="Across every tenant"
      />
    </section>
  );
}

function KPICard({
  href,
  label,
  icon: Icon,
  primary,
  secondary,
  tone,
}: {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  primary: number;
  secondary: string;
  tone?: "success" | "warning";
}) {
  const toneCls =
    tone === "warning"
      ? "border-warning/30 bg-warning/5"
      : tone === "success"
        ? "border-success/30 bg-success/5"
        : "border-slate-100 bg-white";
  const iconTone =
    tone === "warning"
      ? "text-warning"
      : tone === "success"
        ? "text-success"
        : "text-slate-400";
  return (
    <Link
      href={href}
      className={cn(
        "group flex flex-col gap-3 rounded-xl border p-4 transition hover:border-ink/30 hover:shadow-sm",
        toneCls,
      )}
    >
      <div className="flex items-center justify-between">
        <div className="text-2xs font-medium uppercase tracking-wider text-slate-500">
          {label}
        </div>
        <Icon className={cn("h-4 w-4", iconTone)} />
      </div>
      <div className="font-display text-3xl font-bold tracking-tight text-ink">
        {primary.toLocaleString()}
      </div>
      <div className="text-2xs text-slate-500">{secondary}</div>
    </Link>
  );
}

function EngineHealthTable({
  rows,
}: {
  rows: PlatformOverview["engines"]["calls_last_7d"];
}) {
  if (rows.length === 0) {
    return (
      <div className="mt-3 rounded-xl border border-slate-100 bg-white p-6 text-center text-2xs text-slate-400">
        No engine calls in the last 7 days.
      </div>
    );
  }
  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-slate-100 bg-white">
      <table className="w-full text-2xs">
        <thead className="bg-slate-50 text-slate-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Engine
            </th>
            <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
              Calls
            </th>
            <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
              Success
            </th>
            <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
              Fail / unavailable
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Health
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => {
            const issues = row.failure + row.unavailable;
            const successRate =
              row.total > 0 ? Math.round((row.success / row.total) * 100) : 0;
            const healthIcon = issues === 0 ? (
              <span className="inline-flex items-center gap-1 text-success">
                <Activity className="h-3 w-3" />
                {successRate}%
              </span>
            ) : successRate >= 80 ? (
              <span className="inline-flex items-center gap-1 text-warning">
                <ShieldAlert className="h-3 w-3" />
                {successRate}%
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-error">
                <AlertTriangle className="h-3 w-3" />
                {successRate}%
              </span>
            );
            return (
              <tr key={row.engine} className="hover:bg-slate-50">
                <td className="px-3 py-3">
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
                    {row.engine}
                  </code>
                </td>
                <td className="px-3 py-3 text-right text-slate-600">
                  {row.total}
                </td>
                <td className="px-3 py-3 text-right text-success">
                  {row.success}
                </td>
                <td className="px-3 py-3 text-right">
                  <span
                    className={
                      issues > 0 ? "font-medium text-error" : "text-slate-400"
                    }
                  >
                    {issues}
                  </span>
                </td>
                <td className="px-3 py-3">{healthIcon}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Loading() {
  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="h-32 animate-pulse rounded-xl border border-slate-100 bg-slate-50"
        />
      ))}
    </div>
  );
}
