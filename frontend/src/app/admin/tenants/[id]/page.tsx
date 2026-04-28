"use client";

// Per-tenant detail page — the drill-down from the tenant directory.
// Shows everything an operator wants when investigating one tenant:
// identity (name, TIN, contact, certificate state), KPIs (members,
// jobs, invoices, inbox, audit), member list, recent ingestion jobs,
// recent invoices. Each section deep-links into the relevant detail
// (audit log filtered to this tenant; specific job page; etc.).

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  CircleAlert,
  CircleCheck,
  FileText,
  Inbox,
  Mail,
  Phone,
  ScrollText,
  ShieldCheck,
  Users,
} from "lucide-react";

import { api, ApiError, type TenantDetail } from "@/lib/api";
import { AdminShell } from "@/components/admin/AdminShell";
import { cn } from "@/lib/utils";

const REASON_LABEL: Record<string, string> = {
  validation_failure: "Validation failure",
  structuring_skipped: "Structuring skipped",
  low_confidence_extraction: "Low confidence",
  lhdn_rejection: "LHDN rejection",
  manual_review_requested: "Manual review",
};

export default function TenantDetailPage() {
  const params = useParams();
  const router = useRouter();
  const tenantId = typeof params.id === "string" ? params.id : params.id?.[0] ?? "";
  const [detail, setDetail] = useState<TenantDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!tenantId) return;
    setDetail(null);
    setError(null);
    setNotFound(false);
    api
      .adminTenantDetail(tenantId)
      .then((response) => {
        if (cancelled) return;
        setDetail(response);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load tenant.");
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  if (notFound) {
    return (
      <AdminShell>
        <div className="rounded-xl border border-slate-100 bg-white p-12 text-center">
          <CircleAlert className="mx-auto h-8 w-8 text-slate-300" />
          <h2 className="mt-4 font-display text-xl font-semibold">
            Tenant not found
          </h2>
          <p className="mx-auto mt-2 max-w-md text-2xs text-slate-500">
            That UUID doesn&apos;t match any organization on the platform.
          </p>
          <button
            type="button"
            onClick={() => router.replace("/admin/tenants")}
            className="mt-4 rounded-md bg-ink px-4 py-2 text-2xs font-medium text-paper hover:opacity-90"
          >
            Back to tenants
          </button>
        </div>
      </AdminShell>
    );
  }

  return (
    <AdminShell>
      <div className="flex flex-col gap-6">
        <Link
          href="/admin/tenants"
          className="inline-flex items-center gap-1 self-start text-2xs font-medium text-slate-500 hover:text-ink"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to tenants
        </Link>

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error"
          >
            {error}
          </div>
        )}

        {detail === null && !error ? (
          <Loading />
        ) : detail === null ? null : (
          <>
            <Header detail={detail} />
            <KPIGrid detail={detail} />
            <div className="grid gap-6 md:grid-cols-2">
              <MembersSection detail={detail} />
              <InboxSection detail={detail} />
            </div>
            <RecentJobsSection detail={detail} />
            <RecentInvoicesSection detail={detail} />
          </>
        )}
      </div>
    </AdminShell>
  );
}

function Header({ detail }: { detail: TenantDetail }) {
  return (
    <header className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="font-display text-2xl font-bold tracking-tight">
          {detail.legal_name}
        </h1>
        <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
          TIN {detail.tin}
        </code>
        <StateBadge state={detail.subscription_state} />
        {detail.certificate_uploaded && (
          <span className="inline-flex items-center gap-1 rounded-sm bg-success/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-success">
            <ShieldCheck className="h-3 w-3" />
            Cert uploaded
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-4 text-2xs text-slate-500">
        {detail.contact_email && (
          <span className="inline-flex items-center gap-1">
            <Mail className="h-3.5 w-3.5 text-slate-400" />
            {detail.contact_email}
          </span>
        )}
        {detail.contact_phone && (
          <span className="inline-flex items-center gap-1">
            <Phone className="h-3.5 w-3.5 text-slate-400" />
            {detail.contact_phone}
          </span>
        )}
        <span className="text-slate-400">
          {detail.timezone || "no timezone"} · {detail.billing_currency || "—"}{" "}
          · joined{" "}
          {detail.created_at
            ? new Date(detail.created_at).toLocaleDateString()
            : "—"}
        </span>
      </div>
    </header>
  );
}

function KPIGrid({ detail }: { detail: TenantDetail }) {
  const inboxAlert = detail.stats.inbox_open > 0;
  return (
    <section className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
      <Stat
        label="Members"
        primary={detail.stats.member_count}
        icon={Users}
      />
      <Stat
        label="Ingestion jobs"
        primary={detail.stats.ingestion_jobs_total}
        secondary={`${detail.stats.ingestion_jobs_recent_7d} in last 7d`}
        icon={FileText}
      />
      <Stat
        label="Invoices"
        primary={detail.stats.invoices_total}
        secondary={`${detail.stats.invoices_pending_review} pending review`}
        icon={CircleCheck}
      />
      <Stat
        label="Open inbox"
        primary={detail.stats.inbox_open}
        secondary={
          inboxAlert
            ? "Items waiting on a human"
            : "Inbox zero — nothing waiting"
        }
        icon={Inbox}
        tone={inboxAlert ? "warning" : "success"}
      />
      <Link
        href={`/admin/audit?org=${detail.id}`}
        className="md:col-span-2 lg:col-span-4 inline-flex items-center justify-center gap-2 rounded-md border border-slate-200 bg-white px-4 py-2 text-2xs font-medium text-ink hover:border-ink/30 hover:shadow-sm"
      >
        <ScrollText className="h-3.5 w-3.5 text-slate-400" />
        Open the audit log filtered to this tenant ({detail.stats.audit_events.toLocaleString()} events)
      </Link>
    </section>
  );
}

function Stat({
  label,
  primary,
  secondary,
  icon: Icon,
  tone,
}: {
  label: string;
  primary: number;
  secondary?: string;
  icon: React.ComponentType<{ className?: string }>;
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
    <div className={cn("flex flex-col gap-2 rounded-xl border p-4", toneCls)}>
      <div className="flex items-center justify-between">
        <div className="text-2xs font-medium uppercase tracking-wider text-slate-500">
          {label}
        </div>
        <Icon className={cn("h-4 w-4", iconTone)} />
      </div>
      <div className="font-display text-3xl font-bold tracking-tight text-ink">
        {primary.toLocaleString()}
      </div>
      {secondary && <div className="text-2xs text-slate-500">{secondary}</div>}
    </div>
  );
}

function StateBadge({ state }: { state: string }) {
  const tone =
    state === "active" ? "success" : state === "trial" ? "signal" : "slate";
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

function MembersSection({ detail }: { detail: TenantDetail }) {
  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <header className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
        <span className="text-2xs font-medium uppercase tracking-wider text-slate-400">
          Members ({detail.members.length})
        </span>
      </header>
      {detail.members.length === 0 ? (
        <div className="px-4 py-6 text-center text-2xs text-slate-400">
          No members.
        </div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {detail.members.map((m) => (
            <li
              key={m.id}
              className="flex items-center justify-between gap-3 px-4 py-2 text-2xs"
            >
              <div className="flex-1 truncate">
                <span className="font-medium text-ink">{m.email}</span>
              </div>
              <span className="rounded-sm bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-slate-500">
                {m.role}
              </span>
              <span className="text-[10px] text-slate-400">
                {m.joined_date
                  ? new Date(m.joined_date).toLocaleDateString()
                  : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function InboxSection({ detail }: { detail: TenantDetail }) {
  const reasons = Object.entries(detail.inbox_open_by_reason);
  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <header className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
        <span className="text-2xs font-medium uppercase tracking-wider text-slate-400">
          Inbox open by reason
        </span>
      </header>
      {reasons.length === 0 ? (
        <div className="px-4 py-6 text-center text-2xs text-slate-400">
          Nothing open.
        </div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {reasons.map(([reason, count]) => (
            <li
              key={reason}
              className="flex items-center justify-between px-4 py-2 text-2xs"
            >
              <span className="text-slate-600">
                {REASON_LABEL[reason] ?? reason}
              </span>
              <span className="font-mono text-[11px] font-medium text-ink">
                {count}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RecentJobsSection({ detail }: { detail: TenantDetail }) {
  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <header className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
        <span className="text-2xs font-medium uppercase tracking-wider text-slate-400">
          Recent ingestion jobs
        </span>
      </header>
      {detail.recent_jobs.length === 0 ? (
        <div className="px-4 py-6 text-center text-2xs text-slate-400">
          No jobs yet.
        </div>
      ) : (
        <table className="w-full text-2xs">
          <thead className="bg-slate-50 text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Filename
              </th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Status
              </th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Engine
              </th>
              <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                Confidence
              </th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                When
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {detail.recent_jobs.map((job) => (
              <tr key={job.id}>
                <td className="px-3 py-2 truncate text-ink max-w-xs">
                  {job.filename}
                </td>
                <td className="px-3 py-2">
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-700">
                    {job.status}
                  </code>
                </td>
                <td className="px-3 py-2 text-slate-500">{job.engine || "—"}</td>
                <td className="px-3 py-2 text-right text-slate-500">
                  {job.confidence !== null
                    ? `${Math.round(job.confidence * 100)}%`
                    : "—"}
                </td>
                <td className="px-3 py-2 text-slate-500">
                  {job.created_at
                    ? new Date(job.created_at).toLocaleString()
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function RecentInvoicesSection({ detail }: { detail: TenantDetail }) {
  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <header className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
        <span className="text-2xs font-medium uppercase tracking-wider text-slate-400">
          Recent invoices
        </span>
      </header>
      {detail.recent_invoices.length === 0 ? (
        <div className="px-4 py-6 text-center text-2xs text-slate-400">
          No invoices yet.
        </div>
      ) : (
        <table className="w-full text-2xs">
          <thead className="bg-slate-50 text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Invoice #
              </th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Buyer
              </th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Status
              </th>
              <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                Total
              </th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                When
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {detail.recent_invoices.map((inv) => (
              <tr key={inv.id}>
                <td className="px-3 py-2 font-mono text-ink">
                  {inv.invoice_number || "—"}
                </td>
                <td className="px-3 py-2 truncate text-slate-600 max-w-xs">
                  {inv.buyer_legal_name || "—"}
                </td>
                <td className="px-3 py-2">
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-700">
                    {inv.status}
                  </code>
                </td>
                <td className="px-3 py-2 text-right text-slate-600">
                  {inv.grand_total
                    ? `${inv.currency_code} ${inv.grand_total}`
                    : "—"}
                </td>
                <td className="px-3 py-2 text-slate-500">
                  {inv.created_at
                    ? new Date(inv.created_at).toLocaleString()
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Loading() {
  return (
    <div className="grid place-items-center py-24 text-2xs uppercase tracking-wider text-slate-400">
      Loading tenant detail…
    </div>
  );
}
