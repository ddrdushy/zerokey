"use client";

// Audit log page.
//
// Surfaces ZeroKey's most distinctive technical claim — the immutable,
// hash-chained audit log — to the user. Every business-meaningful action
// produces an event; this page is the operator + compliance-officer
// surface for browsing them.
//
// Filters: by action_type (dropdown is populated from the codes that
// actually appear in the user's data, so they don't have to know the
// taxonomy upfront). Pagination via sequence-cursor — each "Load more"
// click fetches events older than the last-seen sequence, which keeps
// the query a point lookup as the log grows.
//
// Each row is collapsed by default; click to expand the JSON payload +
// hash-chain "technical details". The visual treatment leans into
// "boring is good" — this is the screen a compliance officer uses to
// reconstruct what happened, not a marketing surface.

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, ChevronRight, ShieldAlert, ShieldCheck } from "lucide-react";

import { api, ApiError, type AuditEvent } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

type VerifyResult = {
  ok: boolean;
  events_verified: number;
  support_message: string;
  checked_at: string;
};

export default function AuditLogPage() {
  const router = useRouter();
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [actionTypes, setActionTypes] = useState<string[]>([]);
  const [filterAction, setFilterAction] = useState<string>("");
  const [total, setTotal] = useState<number>(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);

  // Load initial page + action-type filter list.
  useEffect(() => {
    let cancelled = false;
    setEvents(null);
    setError(null);
    api
      .listAuditEvents({
        actionType: filterAction || undefined,
        limit: PAGE_SIZE,
      })
      .then((response) => {
        if (cancelled) return;
        setEvents(response.results);
        setTotal(response.total);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/sign-in");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load audit log.");
        setEvents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [filterAction, router]);

  // Action-type dropdown is independent of the current filter — populate once.
  useEffect(() => {
    api
      .listAuditActionTypes()
      .then(setActionTypes)
      .catch(() => setActionTypes([]));
  }, []);

  async function onLoadMore() {
    if (!events || events.length === 0) return;
    setLoadingMore(true);
    try {
      const cursor = events[events.length - 1].sequence;
      const response = await api.listAuditEvents({
        actionType: filterAction || undefined,
        limit: PAGE_SIZE,
        beforeSequence: cursor,
      });
      setEvents((prev) => [...(prev ?? []), ...response.results]);
      setTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load more.");
    } finally {
      setLoadingMore(false);
    }
  }

  function toggleExpanded(id: string) {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  async function onVerifyChain() {
    setVerifying(true);
    setError(null);
    try {
      const result = await api.verifyAuditChain();
      setVerifyResult({
        ok: result.ok,
        events_verified: result.events_verified,
        support_message: result.support_message,
        checked_at: new Date().toISOString(),
      });
      // The verify call itself produces an audit event — refresh the list
      // and total so the user sees their verification request appear.
      const fresh = await api.listAuditEvents({
        actionType: filterAction || undefined,
        limit: PAGE_SIZE,
      });
      setEvents(fresh.results);
      setTotal(fresh.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed.");
    } finally {
      setVerifying(false);
    }
  }

  const hasMore = useMemo(() => {
    if (!events) return false;
    if (filterAction) return events.length > 0 && events.length % PAGE_SIZE === 0;
    return events.length < total;
  }, [events, total, filterAction]);

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header className="flex items-end justify-between">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">
              Audit log
            </h1>
            <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
              Every business action, hash-chained, append-only
            </p>
          </div>
          <ChainStatus
            total={total}
            result={verifyResult}
            verifying={verifying}
            onVerify={onVerifyChain}
          />
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
          actionTypes={actionTypes}
          value={filterAction}
          onChange={setFilterAction}
        />

        {events === null ? (
          <Empty>Loading…</Empty>
        ) : events.length === 0 ? (
          <EmptyState filtered={!!filterAction} />
        ) : (
          <>
            <EventTable
              events={events}
              expanded={expanded}
              onToggle={toggleExpanded}
            />
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

function ChainStatus({
  total,
  result,
  verifying,
  onVerify,
}: {
  total: number;
  result: VerifyResult | null;
  verifying: boolean;
  onVerify: () => void;
}) {
  const verified = result?.ok === true;
  const tampered = result?.ok === false;

  // Tone: success after a clean verify, error after a tamper detection,
  // muted-but-informative before any verify has been attempted.
  const Icon = tampered ? ShieldAlert : ShieldCheck;
  const containerCls = cn(
    "flex flex-col items-end gap-1 rounded-md px-3 py-1.5 text-2xs",
    verified && "bg-success/10 text-success",
    tampered && "bg-error/10 text-error",
    !result && "bg-slate-100 text-slate-600",
  );

  return (
    <div className="flex flex-col items-end gap-2">
      <div className={containerCls}>
        <span className="inline-flex items-center gap-1.5">
          <Icon className="h-3.5 w-3.5" />
          <span className="font-medium">{total.toLocaleString()}</span>
          <span>event{total === 1 ? "" : "s"} on the chain</span>
        </span>
        {result && (
          <span className="text-[10px] opacity-80">
            {result.support_message}
          </span>
        )}
      </div>
      <button
        type="button"
        onClick={onVerify}
        disabled={verifying}
        className="text-[11px] font-medium text-slate-600 underline-offset-4 hover:text-ink hover:underline disabled:opacity-50"
      >
        {verifying
          ? "Verifying chain integrity…"
          : result
            ? "Re-verify"
            : "Verify chain integrity"}
      </button>
    </div>
  );
}

function FilterBar({
  actionTypes,
  value,
  onChange,
}: {
  actionTypes: string[];
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        Filter by action
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink"
      >
        <option value="">All actions</option>
        {actionTypes.map((t) => (
          <option key={t} value={t}>
            {t}
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

function EventTable({
  events,
  expanded,
  onToggle,
}: {
  events: AuditEvent[];
  expanded: Record<string, boolean>;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-100 bg-white">
      <table className="w-full text-2xs">
        <thead className="bg-slate-50 text-slate-400">
          <tr>
            <th className="w-10 px-3 py-2" />
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              #
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              When
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Action
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Actor
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Affected
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {events.map((event) => {
            const isOpen = !!expanded[event.id];
            return (
              <EventRow
                key={event.id}
                event={event}
                isOpen={isOpen}
                onToggle={() => onToggle(event.id)}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function EventRow({
  event,
  isOpen,
  onToggle,
}: {
  event: AuditEvent;
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
        <td className="px-3 py-3 font-mono text-slate-400">{event.sequence}</td>
        <td className="px-3 py-3 text-slate-600">
          {new Date(event.timestamp).toLocaleString()}
        </td>
        <td className="px-3 py-3">
          <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
            {event.action_type}
          </code>
        </td>
        <td className="px-3 py-3 text-slate-600">
          <span className="text-slate-400">{event.actor_type}</span>
          {event.actor_id && (
            <span className="ml-1 font-mono text-[11px]">
              {truncate(event.actor_id, 16)}
            </span>
          )}
        </td>
        <td className="px-3 py-3 text-slate-600">
          {event.affected_entity_type ? (
            <>
              <span className="text-slate-400">{event.affected_entity_type}</span>
              {event.affected_entity_id && (
                <span className="ml-1 font-mono text-[11px]">
                  {truncate(event.affected_entity_id, 12)}
                </span>
              )}
            </>
          ) : (
            <span className="text-slate-400">—</span>
          )}
        </td>
      </tr>
      {isOpen && (
        <tr className="bg-slate-50">
          <td />
          <td colSpan={5} className="px-3 py-3">
            <ExpandedDetails event={event} />
          </td>
        </tr>
      )}
    </>
  );
}

function ExpandedDetails({ event }: { event: AuditEvent }) {
  return (
    <div className="flex flex-col gap-3">
      <DetailField label="Payload">
        <pre className="overflow-auto rounded-md border border-slate-200 bg-white p-3 font-mono text-[11px] leading-relaxed text-slate-700">
          {JSON.stringify(event.payload, null, 2)}
        </pre>
      </DetailField>
      <details className="rounded-md border border-slate-200 bg-white px-3 py-2">
        <summary className="cursor-pointer select-none text-2xs font-medium uppercase tracking-wider text-slate-400">
          Technical details · hash chain
        </summary>
        <dl className="mt-2 grid gap-1 text-[11px]">
          <DetailRow label="Schema version">{event.payload_schema_version}</DetailRow>
          <DetailRow label="Sequence">{event.sequence}</DetailRow>
          <DetailRow label="Content hash">
            <code className="break-all font-mono text-[10px] text-slate-700">
              {event.content_hash}
            </code>
          </DetailRow>
          <DetailRow label="Chain hash">
            <code className="break-all font-mono text-[10px] text-slate-700">
              {event.chain_hash}
            </code>
          </DetailRow>
        </dl>
      </details>
    </div>
  );
}

function DetailField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-slate-400">
        {label}
      </div>
      {children}
    </div>
  );
}

function DetailRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-slate-400">{label}:</dt>
      <dd className="flex-1">{children}</dd>
    </div>
  );
}

function EmptyState({ filtered }: { filtered: boolean }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-slate-100 bg-white p-12 text-center",
      )}
    >
      <ShieldCheck className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
      <h2 className="mt-4 font-display text-xl font-semibold">
        {filtered ? "No events for this action" : "No events yet"}
      </h2>
      <p className="mx-auto mt-2 max-w-md text-2xs text-slate-500">
        {filtered
          ? "Try a different filter, or clear it to see the full log."
          : "Audit events appear here as soon as anything happens — sign-ins, uploads, validation, edits. Every event is hash-chained and immutable."}
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

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return value.slice(0, max - 1) + "…";
}
