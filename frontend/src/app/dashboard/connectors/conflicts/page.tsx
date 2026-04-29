"use client";

// Slice 77b — Conflict queue page.
//
// Surfaces every open MasterFieldConflict the merge classifier
// kicked back during a propose run. Each row gets four
// resolution buttons:
//   - Keep existing (provenance flips to manually_resolved)
//   - Take incoming (master adopts the connector's value)
//   - Keep both as aliases (only valid for legal_name /
//     canonical_name fields)
//   - Enter custom value (operator types a third value)
//
// Cognitive task: "did the connector or my prior data have it
// right?" — different from the invoice review queue, which is
// "did we extract this correctly?". Different lane, different
// page, per the spec doc.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Loader2 } from "lucide-react";

import {
  api,
  ApiError,
  type ConflictResolution,
  type FieldProvenanceEntry,
  type MasterFieldConflictRow,
} from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { ProvenancePill } from "@/components/review/ProvenancePill";
import { cn } from "@/lib/utils";

type StateFilter = "open" | "resolved" | "all";

export default function ConflictQueuePage() {
  const [conflicts, setConflicts] = useState<MasterFieldConflictRow[] | null>(null);
  const [filter, setFilter] = useState<StateFilter>("open");
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function refresh(state: StateFilter = filter) {
    try {
      setConflicts(await api.listConflicts(state));
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError("Not authorised.");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load.");
      setConflicts([]);
    }
  }

  useEffect(() => {
    refresh(filter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  async function onResolve(conflict: MasterFieldConflictRow, resolution: ConflictResolution) {
    let custom_value: string | undefined;
    if (resolution === "enter_custom_value") {
      const v = window.prompt(
        `Enter custom value for ${conflict.field_name}:`,
        conflict.existing_value,
      );
      if (v === null) return;
      custom_value = v;
    }
    setBusyId(conflict.id);
    setError(null);
    try {
      await api.resolveConflict(conflict.id, { resolution, custom_value });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Resolve failed.");
    } finally {
      setBusyId(null);
    }
  }

  const counts = useMemo(() => {
    if (!conflicts) return { open: 0, resolved: 0 };
    return {
      open: conflicts.filter((c) => c.is_open).length,
      resolved: conflicts.filter((c) => !c.is_open).length,
    };
  }, [conflicts]);

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header>
          <Link
            href="/dashboard/connectors"
            className="inline-flex items-center gap-1 text-2xs font-medium text-slate-500 hover:text-ink"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to connectors
          </Link>
          <h1 className="mt-2 font-display text-2xl font-bold tracking-tight">Conflict queue</h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            Per-field decisions the merge classifier left to a human
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

        <div className="flex gap-1 self-start rounded-md bg-slate-100 p-0.5">
          {(["open", "resolved", "all"] as StateFilter[]).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setFilter(s)}
              className={cn(
                "rounded px-3 py-1 text-2xs font-medium capitalize transition",
                filter === s
                  ? "bg-white text-ink shadow-sm"
                  : "text-slate-500 hover:text-slate-700",
              )}
            >
              {s}
              {s !== "all" && (
                <span className="ml-1.5 rounded-sm bg-slate-200 px-1 py-0.5 text-[10px]">
                  {s === "open" ? counts.open : counts.resolved}
                </span>
              )}
            </button>
          ))}
        </div>

        {conflicts === null ? (
          <Loading />
        ) : conflicts.length === 0 ? (
          <Empty filter={filter} />
        ) : (
          <div className="flex flex-col gap-3">
            {conflicts.map((conflict) => (
              <ConflictCard
                key={conflict.id}
                conflict={conflict}
                busy={busyId === conflict.id}
                onResolve={onResolve}
              />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}

function ConflictCard({
  conflict,
  busy,
  onResolve,
}: {
  conflict: MasterFieldConflictRow;
  busy: boolean;
  onResolve: (conflict: MasterFieldConflictRow, resolution: ConflictResolution) => void;
}) {
  const isAliasable =
    (conflict.master_type === "customer" && conflict.field_name === "legal_name") ||
    (conflict.master_type === "item" && conflict.field_name === "canonical_name");

  return (
    <div
      className={cn(
        "rounded-xl border bg-white p-4",
        conflict.is_open ? "border-slate-200" : "border-slate-100 opacity-70",
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="text-2xs uppercase tracking-wider text-slate-400">
            {conflict.master_type === "customer" ? "Customer" : "Item"} · {conflict.field_name}
          </div>
          <Link
            href={
              conflict.master_type === "customer"
                ? `/dashboard/customers/${conflict.master_id}`
                : `/dashboard/connectors`
            }
            className="text-base font-medium text-ink hover:underline"
          >
            View record →
          </Link>
        </div>
        {!conflict.is_open && conflict.resolution && (
          <span className="rounded-sm bg-success/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-success">
            {conflict.resolution.replace(/_/g, " ")}
          </span>
        )}
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <ValueCard
          label="Existing"
          value={conflict.existing_value}
          provenance={conflict.existing_provenance}
        />
        <ValueCard
          label="Incoming"
          value={conflict.incoming_value}
          provenance={conflict.incoming_provenance}
        />
      </div>

      {conflict.is_open && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onResolve(conflict, "keep_existing")}
            disabled={busy}
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Keep existing"}
          </Button>
          <Button size="sm" onClick={() => onResolve(conflict, "take_incoming")} disabled={busy}>
            Take incoming
          </Button>
          {isAliasable && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onResolve(conflict, "keep_both_as_aliases")}
              disabled={busy}
            >
              Keep both (alias)
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onResolve(conflict, "enter_custom_value")}
            disabled={busy}
          >
            Enter custom value
          </Button>
        </div>
      )}
    </div>
  );
}

function ValueCard({
  label,
  value,
  provenance,
}: {
  label: string;
  value: string;
  provenance: FieldProvenanceEntry | null | undefined;
}) {
  return (
    <div className="rounded-md border border-slate-100 bg-slate-50 p-3">
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-1 break-words text-sm font-medium text-ink">
        {value || <span className="text-slate-400">empty</span>}
      </div>
      <ProvenancePill entry={provenance} />
    </div>
  );
}

function Loading() {
  return (
    <div className="grid place-items-center px-5 py-12 text-2xs uppercase tracking-wider text-slate-400">
      Loading conflicts…
    </div>
  );
}

function Empty({ filter }: { filter: StateFilter }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white px-5 py-12 text-center text-2xs text-slate-500">
      {filter === "open"
        ? "No open conflicts. Every sync change has been auto-resolved or already decided."
        : filter === "resolved"
          ? "No resolved conflicts in history yet."
          : "No conflicts in this organization."}
    </div>
  );
}
