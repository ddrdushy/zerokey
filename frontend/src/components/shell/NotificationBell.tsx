"use client";

// Notification bell + popover.
//
// Aggregates the two ambient trust signals the operator already has on
// dedicated pages — open exception-inbox count and latest chain
// verification — into a single header surface. The badge count is the
// number of open inbox items; clicking the bell opens a popover that
// shows the chain status and the first few open items with deep links
// to their full pages.
//
// No real-time / WebSocket subscription — the popover refetches on
// open and the badge polls every minute. That's a deliberate choice for
// dev velocity: the poll cost is negligible (two cheap GETs), and
// real-time delivery doesn't earn its complexity until customers ask
// to be paged within seconds.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Bell, ShieldAlert, ShieldCheck } from "lucide-react";

import { api, type InboxItem, type LatestVerification } from "@/lib/api";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 60_000;

const REASON_LABEL: Record<InboxItem["reason"], string> = {
  validation_failure: "Validation failure",
  structuring_skipped: "Structuring skipped",
  low_confidence_extraction: "Low-confidence extraction",
  lhdn_rejection: "LHDN rejection",
  manual_review_requested: "Manual review requested",
};

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [inboxItems, setInboxItems] = useState<InboxItem[]>([]);
  const [inboxTotal, setInboxTotal] = useState(0);
  const [latest, setLatest] = useState<LatestVerification | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const cancelledRef = useRef(false);

  async function refresh() {
    try {
      const [inboxResp, latestResp] = await Promise.all([
        api.listInbox({ limit: 5 }),
        api.latestAuditVerification(),
      ]);
      if (cancelledRef.current) return;
      setInboxItems(inboxResp.results);
      setInboxTotal(inboxResp.total);
      setLatest(latestResp);
    } catch {
      // Stay silent — the bell is a glanceable surface, errors here
      // shouldn't disrupt the page. The dedicated pages surface real
      // errors when the user navigates there.
    }
  }

  // Refetch on mount + every minute. The summary view only needs the
  // first few items; the dedicated /dashboard/inbox page paginates the
  // full list.
  useEffect(() => {
    cancelledRef.current = false;
    refresh();
    const interval = setInterval(refresh, POLL_INTERVAL_MS);
    return () => {
      cancelledRef.current = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Refetch on open so the badge + list reflect current truth at the
  // moment the user looks. Without this the popover serves whatever was
  // cached from the last poll (up to a minute stale) — fine in steady
  // state but jarring right after an upload completes.
  useEffect(() => {
    if (open) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Close on click-outside + Escape so the popover behaves like every
  // other dropdown in the shell (the avatar menu uses the same trick).
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const hasChainAlert = latest && latest.ok === false;
  // The badge surfaces "you have things to look at" — open items are the
  // primary signal; chain alerts are escalated to a separate red dot.
  const badgeCount = inboxTotal;

  return (
    <div className="relative" ref={popoverRef}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-label="Notifications"
        aria-expanded={open}
        className="relative rounded-md p-2 text-slate-400 hover:bg-slate-50 hover:text-ink"
      >
        <Bell className="h-4 w-4" />
        {badgeCount > 0 && (
          <span
            aria-hidden
            className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-signal px-1 text-[10px] font-semibold text-paper"
          >
            {badgeCount > 9 ? "9+" : badgeCount}
          </span>
        )}
        {hasChainAlert && (
          <span
            aria-hidden
            className="absolute -left-0.5 -top-0.5 h-2 w-2 rounded-full bg-error ring-2 ring-paper"
          />
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Notifications"
          className="absolute right-0 top-full z-50 mt-2 w-80 overflow-hidden rounded-md border border-slate-100 bg-white shadow-lg"
        >
          <div className="border-b border-slate-100 px-3 py-2 text-2xs font-medium uppercase tracking-wider text-slate-400">
            Notifications
          </div>
          <ChainStatusRow latest={latest} />
          <InboxSection items={inboxItems} total={inboxTotal} onClose={() => setOpen(false)} />
        </div>
      )}
    </div>
  );
}

function ChainStatusRow({ latest }: { latest: LatestVerification | null }) {
  const ok = latest?.ok === true;
  const tampered = latest && latest.ok === false;
  const Icon = tampered ? ShieldAlert : ShieldCheck;

  const body = !latest
    ? "No verification yet — first run within six hours."
    : tampered
      ? "Tampering detected. Operations notified."
      : `Chain verified ${formatRelative(latest.started_at)}.`;

  return (
    <Link
      href="/dashboard/audit"
      className={cn(
        "flex items-start gap-2 border-b border-slate-100 px-3 py-2.5 hover:bg-slate-50",
        tampered && "bg-error/5",
        ok && "bg-success/5",
      )}
    >
      <Icon
        className={cn(
          "mt-0.5 h-4 w-4 flex-shrink-0",
          tampered ? "text-error" : ok ? "text-success" : "text-slate-400",
        )}
        aria-hidden
      />
      <div className="flex-1 text-2xs">
        <div className="font-medium text-ink">Chain integrity</div>
        <div className="text-slate-500">{body}</div>
      </div>
    </Link>
  );
}

function InboxSection({
  items,
  total,
  onClose,
}: {
  items: InboxItem[];
  total: number;
  onClose: () => void;
}) {
  if (items.length === 0) {
    return (
      <Link
        href="/dashboard/inbox"
        onClick={onClose}
        className="flex items-start gap-2 px-3 py-2.5 hover:bg-slate-50"
      >
        <div className="mt-0.5 h-4 w-4 flex-shrink-0 rounded-full bg-success/15" aria-hidden />
        <div className="flex-1 text-2xs">
          <div className="font-medium text-ink">Inbox</div>
          <div className="text-slate-500">Inbox zero — nothing waiting on you.</div>
        </div>
      </Link>
    );
  }
  return (
    <div>
      <div className="px-3 py-2 text-2xs font-medium text-ink">
        {total} open item{total === 1 ? "" : "s"}
      </div>
      <ul className="divide-y divide-slate-100">
        {items.map((item) => (
          <li key={item.id}>
            <Link
              href={`/dashboard/jobs/${item.ingestion_job_id}`}
              onClick={onClose}
              className="flex items-start gap-2 px-3 py-2 hover:bg-slate-50"
            >
              <div className="flex-1 text-2xs">
                <div className="font-medium text-ink">{REASON_LABEL[item.reason]}</div>
                <div className="truncate text-slate-500">
                  {item.invoice_number || "Untitled invoice"}
                  {item.buyer_legal_name && ` · ${item.buyer_legal_name}`}
                </div>
              </div>
              <div className="text-[10px] text-slate-400">{formatRelative(item.created_at)}</div>
            </Link>
          </li>
        ))}
      </ul>
      <Link
        href="/dashboard/inbox"
        onClick={onClose}
        className="block border-t border-slate-100 px-3 py-2 text-center text-2xs font-medium text-ink hover:bg-slate-50"
      >
        View all in inbox →
      </Link>
    </div>
  );
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "recently";
  const diffSec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (diffSec < 60) return "just now";
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  return `${diffDay}d ago`;
}
