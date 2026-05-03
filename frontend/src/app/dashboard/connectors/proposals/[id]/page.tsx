"use client";

// Slice 77b — Sync preview screen.
//
// Shows what a sync would do (or what it did, post-apply / post-
// revert). Three tabs:
//   - Will add: net-new master rows the sync proposes to create.
//   - Will update: existing rows + per-field auto / conflict markers.
//   - Conflicts: links into the conflict queue.
// Plus skipped-locked + skipped-verified rows in a collapsed
// section so customers see "we noticed but couldn't auto-resolve".
//
// Buttons:
//   - Apply: writes auto-resolvable changes (would_add + would_update).
//     Available only while status === proposed.
//   - Revert: undoes a previously-applied proposal within the
//     14-day window.
//   - Cancel: nothing today (placeholder for explicit cancellation).

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, CheckCircle2, Loader2, XCircle } from "lucide-react";

import { api, ApiError, type SyncDiff, type SyncDiffEntry, type SyncProposalRow } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Tab = "add" | "update" | "conflicts" | "skipped";

export default function ProposalDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [proposal, setProposal] = useState<SyncProposalRow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"applying" | "reverting" | null>(null);
  const [tab, setTab] = useState<Tab>("add");

  async function refresh() {
    try {
      setProposal(await api.getProposal(params.id));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setError("Proposal not found.");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load.");
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  async function onApply() {
    if (!proposal) return;
    setBusy("applying");
    setError(null);
    try {
      const updated = await api.applyProposal(proposal.id);
      setProposal(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Apply failed.");
    } finally {
      setBusy(null);
    }
  }

  async function onRevert() {
    if (!proposal) return;
    const reason = window.prompt("Reason for reverting? (recorded in the audit log)");
    if (reason === null) return;
    setBusy("reverting");
    setError(null);
    try {
      const updated = await api.revertProposal(proposal.id, reason || "");
      setProposal(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Revert failed.");
    } finally {
      setBusy(null);
    }
  }

  // Compute hooks unconditionally — react-hooks/rules-of-hooks.
  // The early return below for the loading state happens after.
  const expiresIn = useMemo(() => {
    if (!proposal?.applied_at) return null;
    const ms = new Date(proposal.expires_at).getTime() - Date.now();
    if (ms < 0) return "expired";
    const days = Math.floor(ms / 86_400_000);
    return days <= 0 ? "today" : `${days}d`;
  }, [proposal?.applied_at, proposal?.expires_at]);

  if (!proposal) {
    return (
      <AppShell>
        {error ? (
          <div className="grid place-items-center py-24 text-2xs text-error">{error}</div>
        ) : (
          <div className="grid place-items-center py-24 text-2xs uppercase tracking-wider text-slate-400">
            Loading proposal…
          </div>
        )}
      </AppShell>
    );
  }

  const tabs: { key: Tab; label: string; count: number }[] = [
    {
      key: "add",
      label: "Will add",
      count: proposal.diff.customers.would_add.length + proposal.diff.items.would_add.length,
    },
    {
      key: "update",
      label: "Will update",
      count: proposal.diff.customers.would_update.length + proposal.diff.items.would_update.length,
    },
    {
      key: "conflicts",
      label: "Conflicts",
      count: proposal.diff.customers.conflicts.length + proposal.diff.items.conflicts.length,
    },
    {
      key: "skipped",
      label: "Skipped",
      count:
        proposal.diff.customers.skipped_locked.length +
        proposal.diff.customers.skipped_verified.length +
        proposal.diff.items.skipped_locked.length +
        proposal.diff.items.skipped_verified.length,
    },
  ];

  const isProposed = proposal.status === "proposed";
  const isApplied = proposal.status === "applied";

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
          <div className="mt-2 flex flex-wrap items-baseline justify-between gap-3">
            <div>
              <h1 className="font-display text-2xl font-bold tracking-tight">Sync proposal</h1>
              <div className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
                Proposed {new Date(proposal.proposed_at).toLocaleString()} ·{" "}
                <StatusPill status={proposal.status} />
                {expiresIn && <span className="ml-2">Revertable for {expiresIn}</span>}
              </div>
            </div>
            <div className="flex gap-2">
              {isProposed && (
                <>
                  <Link
                    href="/dashboard/connectors"
                    className="inline-flex items-center rounded-md px-3 py-1.5 text-2xs font-medium text-slate-500 hover:bg-slate-100 hover:text-ink"
                  >
                    Cancel
                  </Link>
                  <Button size="sm" onClick={onApply} disabled={busy !== null}>
                    {busy === "applying" ? (
                      <>
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        Applying…
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
                        Apply
                      </>
                    )}
                  </Button>
                </>
              )}
              {isApplied && (
                <Button size="sm" variant="ghost" onClick={onRevert} disabled={busy !== null}>
                  {busy === "reverting" ? (
                    <>
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      Reverting…
                    </>
                  ) : (
                    <>
                      <XCircle className="mr-1.5 h-3.5 w-3.5" />
                      Undo this sync
                    </>
                  )}
                </Button>
              )}
            </div>
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

        {/* Tab strip */}
        <div className="flex gap-1 self-start rounded-md bg-slate-100 p-0.5">
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={cn(
                "rounded px-3 py-1 text-2xs font-medium transition",
                tab === t.key
                  ? "bg-white text-ink shadow-sm"
                  : "text-slate-500 hover:text-slate-700",
              )}
            >
              {t.label}
              <span className="ml-1.5 rounded-sm bg-slate-200 px-1 py-0.5 text-[10px]">
                {t.count}
              </span>
            </button>
          ))}
        </div>

        {tab === "add" && <WouldAdd diff={proposal.diff} />}
        {tab === "update" && <WouldUpdate diff={proposal.diff} />}
        {tab === "conflicts" && <Conflicts diff={proposal.diff} />}
        {tab === "skipped" && <Skipped diff={proposal.diff} />}
      </div>
    </AppShell>
  );
}

function WouldAdd({ diff }: { diff: SyncDiff }) {
  const customers = diff.customers.would_add;
  const items = diff.items.would_add;
  if (customers.length === 0 && items.length === 0) {
    return <Empty>No new records to add.</Empty>;
  }
  return (
    <>
      {customers.length > 0 && (
        <Section title={`${customers.length} new customer${customers.length === 1 ? "" : "s"}`}>
          <RecordList entries={customers} />
        </Section>
      )}
      {items.length > 0 && (
        <Section title={`${items.length} new item${items.length === 1 ? "" : "s"}`}>
          <RecordList entries={items} />
        </Section>
      )}
    </>
  );
}

function WouldUpdate({ diff }: { diff: SyncDiff }) {
  const customers = diff.customers.would_update;
  const items = diff.items.would_update;
  if (customers.length === 0 && items.length === 0) {
    return <Empty>No existing records will change.</Empty>;
  }
  return (
    <>
      {customers.length > 0 && (
        <Section title={`${customers.length} customer update${customers.length === 1 ? "" : "s"}`}>
          <UpdateList entries={customers} />
        </Section>
      )}
      {items.length > 0 && (
        <Section title={`${items.length} item update${items.length === 1 ? "" : "s"}`}>
          <UpdateList entries={items} />
        </Section>
      )}
    </>
  );
}

function Conflicts({ diff }: { diff: SyncDiff }) {
  const conflicts = [...diff.customers.conflicts, ...diff.items.conflicts];
  if (conflicts.length === 0) {
    return <Empty>No conflicts — every change is auto-resolvable.</Empty>;
  }
  return (
    <Section
      title={`${conflicts.length} conflict${conflicts.length === 1 ? "" : "s"} need your decision`}
    >
      <p className="text-2xs text-slate-500">
        Conflicts don&apos;t block apply — auto-resolvable changes still land. Resolve these in the
        conflict queue when you&apos;re ready.
      </p>
      <Link
        href="/dashboard/connectors/conflicts"
        className="inline-flex w-fit items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-2xs font-medium text-ink hover:border-slate-300"
      >
        Open conflict queue →
      </Link>
      <div className="overflow-x-auto rounded-xl border border-slate-100 bg-white">
        <table className="w-full text-2xs">
          <thead className="bg-slate-50 text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Field</th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Existing</th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Incoming</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {conflicts.map((entry, idx) => (
              <tr key={idx}>
                <td className="px-3 py-3 font-medium text-ink">{entry.field}</td>
                <td className="px-3 py-3 text-slate-600">{entry.existing_value || "—"}</td>
                <td className="px-3 py-3 text-slate-600">{entry.incoming_value || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function Skipped({ diff }: { diff: SyncDiff }) {
  const locked = [...diff.customers.skipped_locked, ...diff.items.skipped_locked];
  const verified = [...diff.customers.skipped_verified, ...diff.items.skipped_verified];
  if (locked.length === 0 && verified.length === 0) {
    return <Empty>Nothing was skipped.</Empty>;
  }
  return (
    <>
      {locked.length > 0 && (
        <Section title={`${locked.length} locked field${locked.length === 1 ? "" : "s"}`}>
          <p className="text-2xs text-slate-500">
            These fields are pinned. Future syncs always route to the conflict queue rather than
            auto-overwriting them.
          </p>
          <RawList entries={locked} />
        </Section>
      )}
      {verified.length > 0 && (
        <Section
          title={`${verified.length} authority-verified field${verified.length === 1 ? "" : "s"}`}
        >
          <p className="text-2xs text-slate-500">
            Verified by LHDN — authoritative, syncs can&apos;t override.
          </p>
          <RawList entries={verified} />
        </Section>
      )}
    </>
  );
}

function RecordList({ entries }: { entries: SyncDiffEntry[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-100 bg-white">
      <table className="w-full text-2xs">
        <thead className="bg-slate-50 text-slate-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Source row</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Fields</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {entries.map((e, idx) => (
            <tr key={idx}>
              <td className="px-3 py-3 font-medium text-ink">
                {e.source_record_id || `#${idx + 1}`}
              </td>
              <td className="px-3 py-3 text-slate-600">
                {Object.entries(e.fields ?? {})
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(" · ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UpdateList({ entries }: { entries: SyncDiffEntry[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-100 bg-white">
      <table className="w-full text-2xs">
        <thead className="bg-slate-50 text-slate-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Source row</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Field</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Current</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Proposed</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {entries.flatMap((entry, idx) => {
            const changes = Object.entries(entry.changes ?? {});
            return changes.map(([fname, change], cidx) => (
              <tr key={`${idx}-${cidx}`}>
                <td className="px-3 py-3 font-medium text-ink">
                  {cidx === 0 ? entry.source_record_id || entry.existing_id : ""}
                </td>
                <td className="px-3 py-3">{fname}</td>
                <td className="px-3 py-3 text-slate-500 line-through">{change.current || "—"}</td>
                <td className="px-3 py-3 text-ink">{change.proposed || "—"}</td>
              </tr>
            ));
          })}
        </tbody>
      </table>
    </div>
  );
}

function RawList({ entries }: { entries: SyncDiffEntry[] }) {
  return (
    <ul className="rounded-xl border border-slate-100 bg-white p-3 text-2xs">
      {entries.map((e, idx) => (
        <li
          key={idx}
          className="flex justify-between border-b border-slate-100 py-1.5 last:border-b-0"
        >
          <span className="font-medium text-ink">{e.field}</span>
          <span className="text-slate-500">{e.incoming_value}</span>
        </li>
      ))}
    </ul>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white px-5 py-8 text-center text-2xs text-slate-500">
      {children}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function StatusPill({ status }: { status: SyncProposalRow["status"] }) {
  const tone =
    status === "applied"
      ? "bg-success/15 text-success"
      : status === "reverted"
        ? "bg-warning/15 text-warning"
        : status === "expired" || status === "cancelled"
          ? "bg-slate-100 text-slate-500"
          : "bg-signal/15 text-ink";
  return (
    <span
      className={cn(
        "inline-flex rounded-sm px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider",
        tone,
      )}
    >
      {status}
    </span>
  );
}
