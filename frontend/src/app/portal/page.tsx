"use client";

// Phase 4 of PORTAL_PLAN.md — accountant portal landing.
//
// Lists every active org the signed-in user is a member of, with the
// pills the operator needs to triage at a glance: ERP connector
// status + last sync, MyInvois registration (TIN + BRN), signing
// mode, auto-submit on/off, last activity.
//
// "Open" takes the user into the per-org monthly view at
// /portal/<orgId>/monthly. The existing /dashboard, /dashboard/invoices,
// and /dashboard/settings routes continue to work; this page sits on
// top of the multi-org switcher rather than replacing them.

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Bot,
  Building2,
  CheckCircle2,
  Database,
  KeySquare,
  Loader2,
  ShieldCheck,
} from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";

type OrgRow = Awaited<ReturnType<typeof api.getPortalSummary>>["results"][number];

export default function PortalLandingPage() {
  const [rows, setRows] = useState<OrgRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api
      .getPortalSummary()
      .then((r) => {
        if (!cancelled) setRows(r.results);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Failed to load portal summary.");
          setRows([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header className="flex flex-col gap-1">
          <h1 className="font-display text-2xl font-bold tracking-tight">My Organisations</h1>
          <p className="text-2xs text-slate-500">
            Every organisation you can act for. Pick one to open the monthly view.
          </p>
        </header>

        {error && (
          <div role="alert" className="rounded-md border border-error/30 bg-error/5 px-3 py-2 text-2xs text-error">
            {error}
          </div>
        )}

        {rows === null ? (
          <div className="flex items-center gap-2 rounded-md border border-slate-100 bg-white p-6 text-2xs text-slate-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading…
          </div>
        ) : rows.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="grid gap-3">
            {rows.map((row) => (
              <OrgCard key={row.organization_id} row={row} />
            ))}
          </ul>
        )}
      </div>
    </AppShell>
  );
}

function OrgCard({ row }: { row: OrgRow }) {
  const last =
    row.last_activity_at != null
      ? new Date(row.last_activity_at).toLocaleDateString()
      : "—";
  const lastSync =
    row.connector_last_sync_at != null
      ? new Date(row.connector_last_sync_at).toLocaleDateString()
      : "Never";

  return (
    <li className="rounded-xl border border-slate-100 bg-white">
      <Link
        href={`/portal/${row.organization_id}/monthly`}
        className="group flex flex-col gap-4 p-5 transition-colors hover:bg-slate-50 md:flex-row md:items-center md:justify-between"
      >
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-ink/5 text-ink">
            <Building2 size={18} />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="font-display text-base font-bold text-ink">
                {row.legal_name}
              </span>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-slate-500">
                {row.role || "member"}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
              <span>
                <span className="text-slate-400">TIN:</span>{" "}
                <span className="font-mono text-ink">{row.tin || "—"}</span>
              </span>
              {row.registration_number && (
                <span>
                  <span className="text-slate-400">BRN:</span>{" "}
                  <span className="font-mono text-ink">{row.registration_number}</span>
                </span>
              )}
              <span>
                <span className="text-slate-400">Last activity:</span> {last}
              </span>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <SigningPill mode={row.signing_mode} consent={row.intermediary_consent_at} />
          <AutoSubmitPill on={row.auto_submit_default} />
          <ConnectorPill kind={row.connector_type} lastSync={lastSync} />
          <span className="ml-1 inline-flex items-center gap-1 rounded-md bg-ink px-3 py-1.5 text-2xs font-semibold text-paper group-hover:bg-slate-800">
            Open
            <ArrowRight size={12} />
          </span>
        </div>
      </Link>
    </li>
  );
}

function SigningPill({
  mode,
  consent,
}: {
  mode: "intermediary" | "self_signed";
  consent: string | null;
}) {
  const isIntermediary = mode === "intermediary";
  const pending = isIntermediary && !consent;
  return (
    <span
      className={[
        "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium",
        pending
          ? "bg-warning/10 text-warning"
          : isIntermediary
            ? "bg-success/10 text-success"
            : "bg-slate-100 text-slate-600",
      ].join(" ")}
      title={
        pending
          ? "Intermediary consent pending — Symprio cannot sign yet"
          : isIntermediary
            ? "Symprio signs as your intermediary"
            : "You sign with your own LHDN certificate"
      }
    >
      {isIntermediary ? <ShieldCheck size={11} /> : <KeySquare size={11} />}
      {pending
        ? "Consent pending"
        : isIntermediary
          ? "Intermediary"
          : "Self-signed"}
    </span>
  );
}

function AutoSubmitPill({ on }: { on: boolean }) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium",
        on ? "bg-success/10 text-success" : "bg-slate-100 text-slate-600",
      ].join(" ")}
      title={
        on
          ? "Auto-submit is on — new invoices go to LHDN automatically when gates pass"
          : "Auto-submit is off — every new invoice waits for your click"
      }
    >
      <Bot size={11} />
      {on ? "Auto-submit ON" : "Auto-submit OFF"}
    </span>
  );
}

function ConnectorPill({ kind, lastSync }: { kind: string; lastSync: string }) {
  if (!kind) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 text-[10px] font-medium text-slate-500"
        title="No ERP connector configured"
      >
        <Database size={11} />
        No connector
      </span>
    );
  }
  const label =
    kind === "sql_account"
      ? "SQL Account"
      : kind === "autocount"
        ? "AutoCount"
        : kind === "sage_ubs"
          ? "Sage UBS"
          : kind === "csv"
            ? "CSV"
            : kind;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md bg-ink/[0.06] px-2 py-1 text-[10px] font-medium text-ink"
      title={`Last sync: ${lastSync}`}
    >
      <Database size={11} />
      {label}
    </span>
  );
}

function EmptyState() {
  return (
    <div className="rounded-xl border border-dashed border-slate-200 bg-white p-12 text-center">
      <CheckCircle2 className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
      <h2 className="mt-4 font-display text-xl font-semibold">No organisations linked</h2>
      <p className="mt-2 text-xs text-slate-500">
        You aren&apos;t a member of any active organisation. If this looks wrong, contact the owner.
      </p>
    </div>
  );
}
