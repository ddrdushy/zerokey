"use client";

// Platform-wide audit log — every tenant's events in one
// chronologically-ordered table. Distinct from the customer audit log
// page (which is tenant-scoped) because:
//   1. Each row exposes the organization_id so the operator can see
//      WHICH tenant generated the event.
//   2. The action-type dropdown is populated from EVERY action ever
//      recorded across the platform, not just the operator's own org.
//   3. There's a "filter to one tenant" affordance for chasing an
//      incident without leaving the surface.
//
// Cross-tenant reads are themselves audited — each page load emits an
// admin.platform_audit_listed event with the filters used. The
// operator's own actions on this page are visible at the top of their
// own queries, which is the intended self-monitoring loop.

import { ChevronDown, ChevronRight, ScrollText } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  api,
  type PlatformAuditEvent,
} from "@/lib/api";
import { AdminShell } from "@/components/admin/AdminShell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

export default function PlatformAuditPage() {
  const [events, setEvents] = useState<PlatformAuditEvent[] | null>(null);
  const [actionTypes, setActionTypes] = useState<string[]>([]);
  const [filterAction, setFilterAction] = useState("");
  const [filterOrgId, setFilterOrgId] = useState("");
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    setEvents(null);
    setError(null);
    api
      .adminListPlatformAuditEvents({
        actionType: filterAction || undefined,
        organizationId: filterOrgId || undefined,
        limit: PAGE_SIZE,
      })
      .then((response) => {
        if (cancelled) return;
        setEvents(response.results);
        setTotal(response.total);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load.");
        setEvents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [filterAction, filterOrgId]);

  useEffect(() => {
    api
      .adminListPlatformActionTypes()
      .then(setActionTypes)
      .catch(() => setActionTypes([]));
  }, []);

  async function onLoadMore() {
    if (!events || events.length === 0) return;
    setLoadingMore(true);
    try {
      const cursor = events[events.length - 1].sequence;
      const response = await api.adminListPlatformAuditEvents({
        actionType: filterAction || undefined,
        organizationId: filterOrgId || undefined,
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

  const hasMore = useMemo(() => {
    if (!events) return false;
    if (filterAction || filterOrgId)
      return events.length > 0 && events.length % PAGE_SIZE === 0;
    return events.length < total;
  }, [events, total, filterAction, filterOrgId]);

  return (
    <AdminShell>
      <div className="flex flex-col gap-6">
        <header className="flex items-end justify-between">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">
              Platform audit log
            </h1>
            <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
              Every tenant · cross-tenant · hash-chained
            </p>
          </div>
          <div className="flex flex-col items-end gap-1 rounded-md bg-slate-100 px-3 py-1.5 text-2xs text-slate-600">
            <span className="inline-flex items-center gap-1.5">
              <ScrollText className="h-3.5 w-3.5" />
              <span className="font-medium">{total.toLocaleString()}</span>
              <span>event{total === 1 ? "" : "s"} on the chain</span>
            </span>
            <span className="text-[10px] opacity-80">
              Listing this page is itself audited.
            </span>
          </div>
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
          filterAction={filterAction}
          onFilterAction={setFilterAction}
          filterOrgId={filterOrgId}
          onFilterOrgId={setFilterOrgId}
        />

        {events === null ? (
          <Empty>Loading…</Empty>
        ) : events.length === 0 ? (
          <EmptyState filtered={!!(filterAction || filterOrgId)} />
        ) : (
          <>
            <EventTable
              events={events}
              expanded={expanded}
              onToggle={toggleExpanded}
              onPickOrg={(orgId) => setFilterOrgId(orgId)}
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
    </AdminShell>
  );
}

function FilterBar({
  actionTypes,
  filterAction,
  onFilterAction,
  filterOrgId,
  onFilterOrgId,
}: {
  actionTypes: string[];
  filterAction: string;
  onFilterAction: (next: string) => void;
  filterOrgId: string;
  onFilterOrgId: (next: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        Action
      </label>
      <select
        value={filterAction}
        onChange={(e) => onFilterAction(e.target.value)}
        className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink"
      >
        <option value="">All actions</option>
        {actionTypes.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <label className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        Tenant
      </label>
      <input
        type="text"
        placeholder="Organization UUID…"
        value={filterOrgId}
        onChange={(e) => onFilterOrgId(e.target.value.trim())}
        className="rounded-md border border-slate-200 bg-white px-3 py-1.5 font-mono text-[11px] text-ink focus:outline-none focus:ring-1 focus:ring-ink"
        size={36}
      />
      {(filterAction || filterOrgId) && (
        <button
          type="button"
          onClick={() => {
            onFilterAction("");
            onFilterOrgId("");
          }}
          className="text-2xs text-slate-500 underline-offset-4 hover:text-ink hover:underline"
        >
          Clear filters
        </button>
      )}
    </div>
  );
}

function EventTable({
  events,
  expanded,
  onToggle,
  onPickOrg,
}: {
  events: PlatformAuditEvent[];
  expanded: Record<string, boolean>;
  onToggle: (id: string) => void;
  onPickOrg: (orgId: string) => void;
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
              Tenant
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Action
            </th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
              Actor
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
                onPickOrg={() =>
                  event.organization_id && onPickOrg(event.organization_id)
                }
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
  onPickOrg,
}: {
  event: PlatformAuditEvent;
  isOpen: boolean;
  onToggle: () => void;
  onPickOrg: () => void;
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
          {event.organization_id ? (
            <button
              type="button"
              onClick={onPickOrg}
              className="font-mono text-[11px] text-slate-700 underline-offset-4 hover:text-ink hover:underline"
              title="Filter to this tenant"
            >
              {event.organization_id.slice(0, 8)}…
            </button>
          ) : (
            <span className="rounded-sm bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-slate-500">
              system
            </span>
          )}
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

function ExpandedDetails({ event }: { event: PlatformAuditEvent }) {
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
          <DetailRow label="Schema version">
            {event.payload_schema_version}
          </DetailRow>
          <DetailRow label="Sequence">{event.sequence}</DetailRow>
          <DetailRow label="Organization">
            <code className="break-all font-mono text-[10px] text-slate-700">
              {event.organization_id ?? "—"}
            </code>
          </DetailRow>
          <DetailRow label="Affected entity">
            {event.affected_entity_type ? (
              <span>
                {event.affected_entity_type}{" "}
                {event.affected_entity_id && (
                  <code className="font-mono text-[10px] text-slate-700">
                    {event.affected_entity_id}
                  </code>
                )}
              </span>
            ) : (
              "—"
            )}
          </DetailRow>
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
      <ScrollText className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
      <h2 className="mt-4 font-display text-xl font-semibold">
        {filtered ? "No events for these filters" : "Nothing on the chain yet"}
      </h2>
      <p className="mx-auto mt-2 max-w-md text-2xs text-slate-500">
        {filtered
          ? "Try a different filter or clear them to see the full log."
          : "Events appear here as soon as anything happens platform-wide."}
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
