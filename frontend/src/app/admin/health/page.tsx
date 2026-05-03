"use client";

// Slice 99 — System health dashboard.
//
// Real-time view of every critical subsystem: postgres, celery,
// LHDN, Stripe, plus queue depth and per-engine latency. Polls every
// 5s while the page is in the foreground.

import { useEffect, useState } from "react";
import { Activity, AlertTriangle, CircleCheck, ShieldAlert } from "lucide-react";

import { api, type AdminSystemHealth } from "@/lib/api";
import { AdminShell } from "@/components/admin/AdminShell";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 5000;

export default function AdminHealthPage() {
  const [snap, setSnap] = useState<AdminSystemHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function load() {
      try {
        const data = await api.adminSystemHealth();
        if (!cancelled) setSnap(data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load.");
      } finally {
        if (!cancelled) timer = setTimeout(load, POLL_INTERVAL_MS);
      }
    }
    load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  return (
    <AdminShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">System health</h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            Real-time subsystem probes · refreshes every 5s
          </p>
        </header>

        {error && (
          <div role="alert" className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error">
            {error}
          </div>
        )}

        {snap === null ? (
          <Loading />
        ) : (
          <>
            <SubsystemGrid subsystems={snap.subsystems} />
            <QueueDepthCard depth={snap.queue_depth} />
            <ExtractionLatencyCard rows={snap.extraction_latency} />
            <p className="text-2xs text-slate-400">
              Last checked {new Date(snap.checked_at).toLocaleString()}
            </p>
          </>
        )}
      </div>
    </AdminShell>
  );
}

function SubsystemGrid({
  subsystems,
}: {
  subsystems: AdminSystemHealth["subsystems"];
}) {
  return (
    <section>
      <h2 className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        Subsystems
      </h2>
      <div className="mt-2 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        {Object.entries(subsystems).map(([name, info]) => (
          <SubsystemCard key={name} name={name} status={info.status} detail={info.detail} httpStatus={info.http_status} />
        ))}
      </div>
    </section>
  );
}

function SubsystemCard({
  name,
  status,
  detail,
  httpStatus,
}: {
  name: string;
  status: string;
  detail?: string;
  httpStatus?: number;
}) {
  const tone =
    status === "ok" || status === "configured"
      ? "success"
      : status === "degraded"
        ? "warning"
        : status === "down"
          ? "error"
          : "neutral";
  const Icon =
    tone === "success" ? CircleCheck : tone === "warning" ? ShieldAlert : tone === "error" ? AlertTriangle : Activity;
  const colour =
    tone === "success"
      ? "text-success border-success/30 bg-success/5"
      : tone === "warning"
        ? "text-warning border-warning/30 bg-warning/5"
        : tone === "error"
          ? "text-error border-error/30 bg-error/5"
          : "text-slate-500 border-slate-100 bg-white";
  return (
    <div className={cn("flex flex-col gap-2 rounded-xl border p-4", colour)}>
      <div className="flex items-center justify-between">
        <div className="text-2xs font-medium uppercase tracking-wider text-slate-500">{name}</div>
        <Icon className="h-4 w-4" />
      </div>
      <div className="text-base font-semibold">{status}</div>
      {httpStatus !== undefined && (
        <div className="text-2xs text-slate-500">HTTP {httpStatus}</div>
      )}
      {detail && <div className="truncate text-2xs text-slate-500">{detail}</div>}
    </div>
  );
}

function QueueDepthCard({ depth }: { depth: AdminSystemHealth["queue_depth"] }) {
  const queues = Object.entries(depth);
  return (
    <section>
      <h2 className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        Celery queue depth
      </h2>
      <div className="mt-2 grid gap-3 md:grid-cols-3">
        {queues.map(([q, n]) => {
          const tone =
            n === null
              ? "neutral"
              : n === 0
                ? "success"
                : n < 10
                  ? "neutral"
                  : n < 100
                    ? "warning"
                    : "error";
          return (
            <div
              key={q}
              className={cn(
                "rounded-xl border p-4",
                tone === "success" && "border-success/30 bg-success/5",
                tone === "warning" && "border-warning/30 bg-warning/5",
                tone === "error" && "border-error/30 bg-error/5",
                tone === "neutral" && "border-slate-100 bg-white",
              )}
            >
              <div className="text-2xs font-medium uppercase tracking-wider text-slate-500">{q}</div>
              <div className="mt-1 font-display text-2xl font-bold tracking-tight text-ink">
                {n === null ? "—" : n.toLocaleString()}
              </div>
              <div className="mt-1 text-2xs text-slate-400">tasks pending</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ExtractionLatencyCard({
  rows,
}: {
  rows: AdminSystemHealth["extraction_latency"];
}) {
  return (
    <section>
      <h2 className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        Extraction latency (last 60 min)
      </h2>
      {rows.length === 0 ? (
        <div className="mt-2 rounded-xl border border-slate-100 bg-white p-6 text-center text-2xs text-slate-400">
          No engine calls in the last hour.
        </div>
      ) : (
        <div className="mt-2 overflow-hidden rounded-xl border border-slate-100 bg-white">
          <table className="w-full text-2xs">
            <thead className="bg-slate-50 text-slate-400">
              <tr>
                <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Engine</th>
                <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">Calls</th>
                <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">Avg latency</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={r.engine} className="hover:bg-slate-50">
                  <td className="px-3 py-3">
                    <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
                      {r.engine}
                    </code>
                  </td>
                  <td className="px-3 py-3 text-right text-slate-600">{r.calls}</td>
                  <td className="px-3 py-3 text-right text-slate-600">{r.avg_ms.toLocaleString()} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Loading() {
  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="h-32 animate-pulse rounded-xl border border-slate-100 bg-slate-50" />
      ))}
    </div>
  );
}
