"use client";

// Compliance posture (Slice 96).
//
// Surfaces the metrics LHDN-Phase-4-mandated SMEs care about most:
//
//   - success rate (validated / [validated + rejected + cancelled + error])
//   - median time to validation (creation → validated_timestamp)
//   - penalty-window compliance (% of validated invoices submitted
//     within 30 days of issue_date — LHDN's enforcement window)
//
// Derived from existing Invoice rows; no aggregation table. Cheap
// to compute for tenants in the hundreds-of-invoices range; we'd
// add a materialised view if a customer hits five-figure volumes.

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";

type Posture = Awaited<ReturnType<typeof api.compliancePosture>>;

const WINDOW_OPTIONS: { value: number; label: string }[] = [
  { value: 7, label: "7 days" },
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
  { value: 365, label: "1 year" },
];

export default function ComplianceDashboardPage() {
  const [days, setDays] = useState(30);
  const [posture, setPosture] = useState<Posture | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .compliancePosture(days)
      .then(setPosture)
      .catch(() => {
        // Non-fatal — render the empty state.
      })
      .finally(() => setLoading(false));
  }, [days]);

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">
              Compliance posture
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-600">
              How your invoicing operation is doing against LHDN's enforcement
              expectations. Numbers are derived from your validated submissions.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-2xs uppercase tracking-wider text-slate-500" htmlFor="window">
              Window
            </label>
            <select
              id="window"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-ink focus:border-ink focus:outline-none"
            >
              {WINDOW_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </header>

        {loading ? (
          <div className="grid place-items-center py-24 text-slate-400">Loading…</div>
        ) : posture && posture.counts.total === 0 ? (
          <div className="rounded-xl border border-slate-100 bg-white p-8 text-center">
            <p className="text-sm text-slate-500">
              No invoices in the last {days} day{days === 1 ? "" : "s"}.
            </p>
          </div>
        ) : posture ? (
          <>
            <section className="grid gap-4 md:grid-cols-3">
              <Headline
                label="Success rate"
                value={fmtPct(posture.success_rate)}
                detail={`${posture.counts.validated} of ${
                  posture.counts.validated +
                  posture.counts.rejected +
                  posture.counts.cancelled +
                  posture.counts.error
                } reached terminal state cleanly`}
                tone={
                  posture.success_rate == null
                    ? "neutral"
                    : posture.success_rate >= 0.95
                      ? "good"
                      : posture.success_rate >= 0.85
                        ? "warn"
                        : "bad"
                }
              />
              <Headline
                label="Penalty-window compliance"
                value={fmtPct(posture.penalty_window_compliance)}
                detail={`Submitted within ${posture.penalty_window_days} days of issue date · ${posture.in_penalty_window}/${posture.in_penalty_window + posture.out_of_penalty_window}`}
                tone={
                  posture.penalty_window_compliance == null
                    ? "neutral"
                    : posture.penalty_window_compliance >= 0.95
                      ? "good"
                      : posture.penalty_window_compliance >= 0.85
                        ? "warn"
                        : "bad"
                }
              />
              <Headline
                label="Median time to validation"
                value={fmtDuration(posture.median_seconds_to_validation)}
                detail="From upload to LHDN-validated UUID"
                tone="neutral"
              />
            </section>

            <section className="rounded-xl border border-slate-100 bg-white p-6">
              <h2 className="text-base font-semibold">Status breakdown</h2>
              <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
                Last {posture.window_days} days · {posture.counts.total} invoice
                {posture.counts.total === 1 ? "" : "s"}
              </p>
              <ul className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                <BreakdownRow label="Validated by LHDN" count={posture.counts.validated} tone="good" />
                <BreakdownRow label="Ready for review" count={posture.counts.ready_for_review} tone="neutral" />
                <BreakdownRow label="In flight" count={posture.counts.in_flight} tone="neutral" />
                <BreakdownRow label="Rejected by LHDN" count={posture.counts.rejected} tone="bad" />
                <BreakdownRow label="Cancelled" count={posture.counts.cancelled} tone="neutral" />
                <BreakdownRow label="Error" count={posture.counts.error} tone="bad" />
              </ul>
            </section>
          </>
        ) : (
          <div className="rounded-xl border border-error/30 bg-error/5 p-6 text-sm text-error">
            Couldn't load compliance posture.
          </div>
        )}
      </div>
    </AppShell>
  );
}

function Headline({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "good" | "warn" | "bad" | "neutral";
}) {
  const ring =
    tone === "good"
      ? "border-success/40"
      : tone === "warn"
        ? "border-warning/40"
        : tone === "bad"
          ? "border-error/40"
          : "border-slate-100";
  const text =
    tone === "good"
      ? "text-success"
      : tone === "warn"
        ? "text-warning"
        : tone === "bad"
          ? "text-error"
          : "text-ink";
  return (
    <div className={`rounded-xl border bg-white p-5 ${ring}`}>
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div className={`mt-2 font-display text-3xl font-bold tracking-tight ${text}`}>
        {value}
      </div>
      <div className="mt-2 text-2xs text-slate-500">{detail}</div>
    </div>
  );
}

function BreakdownRow({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: "good" | "bad" | "neutral";
}) {
  const dot =
    tone === "good" ? "bg-success" : tone === "bad" ? "bg-error" : "bg-slate-300";
  return (
    <li className="flex items-center justify-between rounded-md border border-slate-100 bg-slate-50 px-3 py-2 text-2xs">
      <span className="flex items-center gap-2 text-slate-600">
        <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
        {label}
      </span>
      <span className="font-mono font-semibold text-ink">{count}</span>
    </li>
  );
}

function fmtPct(value: number | null): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function fmtDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)} min`;
  return `${(seconds / 3600).toFixed(1)} hr`;
}
