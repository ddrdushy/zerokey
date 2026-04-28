"use client";

// Engine activity page.
//
// Surfaces the per-engine telemetry the platform has been recording since
// Slice 5 — every OCR / LLM call produces an EngineCall row with latency,
// cost, outcome, confidence. Customers who're paying per call have a
// legitimate need to see this; ENGINE_REGISTRY.md "observability and
// auditability" requires it.
//
// Two stacks: a per-engine summary (success rate, avg latency, total
// cost) at the top, and the recent-calls list underneath. Same
// vocabulary as the audit log page (cursor pagination, expandable
// detail) so they read as a pair: audit log answers "what business
// actions happened?", engines answers "what AI calls did those actions
// trigger?".

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Sparkles,
  Zap,
} from "lucide-react";

import {
  api,
  ApiError,
  type EngineCallRecord,
  type EngineSummary,
} from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

export default function EngineActivityPage() {
  const router = useRouter();
  const [summary, setSummary] = useState<EngineSummary[] | null>(null);
  const [calls, setCalls] = useState<EngineCallRecord[] | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.engineSummary(),
      api.listEngineCalls({ limit: PAGE_SIZE }),
    ])
      .then(([s, c]) => {
        if (cancelled) return;
        setSummary(s);
        setCalls(c);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/sign-in");
          return;
        }
        setError(
          err instanceof Error ? err.message : "Failed to load engine activity.",
        );
        setSummary([]);
        setCalls([]);
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function onLoadMore() {
    if (!calls || calls.length === 0) return;
    setLoadingMore(true);
    try {
      const cursor = calls[calls.length - 1].started_at;
      const more = await api.listEngineCalls({
        limit: PAGE_SIZE,
        beforeStartedAt: cursor,
      });
      setCalls((prev) => [...(prev ?? []), ...more]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load more.");
    } finally {
      setLoadingMore(false);
    }
  }

  function toggleExpanded(id: string) {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Engine activity
          </h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            AI engines that have processed your invoices
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

        <SummarySection summary={summary} />

        <CallsSection
          calls={calls}
          expanded={expanded}
          loadingMore={loadingMore}
          onToggle={toggleExpanded}
          onLoadMore={onLoadMore}
        />
      </div>
    </AppShell>
  );
}

function SummarySection({ summary }: { summary: EngineSummary[] | null }) {
  if (summary === null) {
    return (
      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold">Per-engine summary</h2>
        <Loading>Loading…</Loading>
      </section>
    );
  }
  if (summary.length === 0) {
    return (
      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold">Per-engine summary</h2>
        <EmptyCard>
          {`No engine calls yet. Drop an invoice from the dashboard and the
          extraction pipeline's calls will appear here.`}
        </EmptyCard>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold">Per-engine summary</h2>
        <span className="text-2xs uppercase tracking-wider text-slate-400">
          {summary.length} engine{summary.length === 1 ? "" : "s"} active
        </span>
      </div>
      <div className="overflow-hidden rounded-xl border border-slate-100 bg-white">
        <table className="w-full text-2xs">
          <thead className="bg-slate-50 text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Engine
              </th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Capability
              </th>
              <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                Calls
              </th>
              <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                Success rate
              </th>
              <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                Avg latency
              </th>
              <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                Total cost
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {summary.map((row) => (
              <tr key={row.engine_name} className="hover:bg-slate-50">
                <td className="px-3 py-3">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-ink">
                      {row.engine_name}
                    </span>
                  </div>
                  <div className="mt-0.5 text-2xs text-slate-400">
                    {row.vendor}
                  </div>
                </td>
                <td className="px-3 py-3">
                  <CapabilityBadge capability={row.capability} />
                </td>
                <td className="px-3 py-3 text-right font-mono">
                  {row.total_calls.toLocaleString()}
                </td>
                <td className="px-3 py-3 text-right">
                  <SuccessRate
                    rate={row.success_rate}
                    total={row.total_calls}
                  />
                </td>
                <td className="px-3 py-3 text-right font-mono">
                  {formatLatency(row.avg_duration_ms)}
                </td>
                <td className="px-3 py-3 text-right font-mono">
                  {formatCost(row.total_cost_micros)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CallsSection({
  calls,
  expanded,
  loadingMore,
  onToggle,
  onLoadMore,
}: {
  calls: EngineCallRecord[] | null;
  expanded: Record<string, boolean>;
  loadingMore: boolean;
  onToggle: (id: string) => void;
  onLoadMore: () => void;
}) {
  if (calls === null) {
    return (
      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold">Recent calls</h2>
        <Loading>Loading…</Loading>
      </section>
    );
  }
  if (calls.length === 0) {
    // The summary's empty-state already explains; here just collapse.
    return null;
  }

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-base font-semibold">Recent calls</h2>
      <div className="overflow-hidden rounded-xl border border-slate-100 bg-white">
        <table className="w-full text-2xs">
          <thead className="bg-slate-50 text-slate-400">
            <tr>
              <th className="w-10 px-3 py-2" />
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                When
              </th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Engine
              </th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Outcome
              </th>
              <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                Latency
              </th>
              <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                Cost
              </th>
              <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                Confidence
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {calls.map((call) => (
              <CallRow
                key={call.id}
                call={call}
                isOpen={!!expanded[call.id]}
                onToggle={() => onToggle(call.id)}
              />
            ))}
          </tbody>
        </table>
      </div>
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
    </section>
  );
}

function CallRow({
  call,
  isOpen,
  onToggle,
}: {
  call: EngineCallRecord;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className="hover:bg-slate-50">
        <td className="w-10 px-3 py-3">
          <button
            type="button"
            onClick={onToggle}
            aria-label={isOpen ? "Collapse details" : "Expand details"}
            className="text-slate-400 hover:text-ink"
          >
            {isOpen ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
        </td>
        <td className="px-3 py-3 text-slate-600">
          {new Date(call.started_at).toLocaleString()}
        </td>
        <td className="px-3 py-3">
          <span className="font-medium">{call.engine_name}</span>
          <span className="ml-1.5 text-2xs text-slate-400">{call.vendor}</span>
        </td>
        <td className="px-3 py-3">
          <OutcomeBadge outcome={call.outcome} errorClass={call.error_class} />
        </td>
        <td className="px-3 py-3 text-right font-mono">
          {formatLatency(call.duration_ms)}
        </td>
        <td className="px-3 py-3 text-right font-mono text-slate-600">
          {formatCost(call.cost_micros)}
        </td>
        <td className="px-3 py-3 text-right font-mono">
          {call.confidence !== null ? `${(call.confidence * 100).toFixed(0)}%` : "—"}
        </td>
      </tr>
      {isOpen && (
        <tr className="bg-slate-50">
          <td />
          <td colSpan={6} className="px-3 py-3">
            <CallExpandedDetails call={call} />
          </td>
        </tr>
      )}
    </>
  );
}

function CallExpandedDetails({ call }: { call: EngineCallRecord }) {
  return (
    <div className="flex flex-col gap-3">
      {call.error_class && (
        <div className="rounded-md border border-error/30 bg-error/5 px-3 py-2 text-2xs text-error">
          <span className="font-medium">Error class:</span> {call.error_class}
        </div>
      )}
      <div className="grid gap-2 text-2xs sm:grid-cols-2">
        <Detail label="Request id">
          <code className="break-all font-mono text-[11px] text-slate-700">
            {call.request_id ?? "—"}
          </code>
        </Detail>
        <Detail label="Cost (micros USD)">
          <code className="font-mono text-[11px] text-slate-700">
            {call.cost_micros.toLocaleString()}
          </code>
        </Detail>
      </div>
      <div>
        <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-slate-400">
          Vendor diagnostics
        </div>
        <pre className="overflow-auto rounded-md border border-slate-200 bg-white p-3 font-mono text-[11px] leading-relaxed text-slate-700">
          {JSON.stringify(call.diagnostics ?? {}, null, 2)}
        </pre>
      </div>
    </div>
  );
}

function CapabilityBadge({ capability }: { capability: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
      <Sparkles className="h-3 w-3 text-slate-400" />
      {capability.replace(/_/g, " ")}
    </span>
  );
}

function SuccessRate({ rate, total }: { rate: number; total: number }) {
  if (total === 0) return <span className="text-slate-400">—</span>;
  const pct = Math.round(rate * 100);
  const tone =
    rate >= 0.95
      ? "text-success"
      : rate >= 0.8
        ? "text-warning"
        : "text-error";
  return (
    <span className={cn("inline-flex items-center gap-1.5 font-mono", tone)}>
      {pct === 100 ? (
        <CheckCircle2 className="h-3 w-3" />
      ) : (
        <AlertCircle className="h-3 w-3" />
      )}
      {pct}%
    </span>
  );
}

function OutcomeBadge({
  outcome,
  errorClass,
}: {
  outcome: EngineCallRecord["outcome"];
  errorClass: string;
}) {
  const tone =
    outcome === "success"
      ? "bg-success/10 text-success"
      : outcome === "unavailable"
        ? "bg-warning/10 text-warning"
        : "bg-error/10 text-error";
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium", tone)}>
      {outcome === "success" ? (
        <CheckCircle2 className="h-3 w-3" />
      ) : outcome === "unavailable" ? (
        <Zap className="h-3 w-3" />
      ) : (
        <AlertCircle className="h-3 w-3" />
      )}
      {outcome}
      {errorClass && outcome !== "success" && (
        <span className="ml-1 font-mono opacity-70">{errorClass}</span>
      )}
    </span>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div className="mt-0.5">{children}</div>
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

function EmptyCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-6 text-center text-2xs text-slate-500">
      {children}
    </div>
  );
}

function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function formatCost(micros: number): string {
  if (micros === 0) return "$0";
  // 1 micro = 1 millionth of a USD; surface in dollars with appropriate
  // precision (≥ 1 cent renders cents, smaller renders fractional).
  const dollars = micros / 1_000_000;
  if (dollars >= 0.01) return `$${dollars.toFixed(2)}`;
  return `$${dollars.toFixed(4)}`;
}
