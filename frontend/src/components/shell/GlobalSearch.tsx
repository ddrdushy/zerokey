"use client";

// Slice 101 — global search input for the topbar.
//
// Debounced (250ms) search across invoices + customers + audit
// events for the active org. Results render in a popover beneath
// the input. Click → navigate to the relevant detail surface.
// Press / to focus, Esc to clear.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { FileText, ScrollText, Search, Users } from "lucide-react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type Hit = { type: "invoice" | "customer" | "audit"; id: string; primary: string; secondary: string; href: string };

export function GlobalSearch() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Debounce. The state machine here is small enough that a manual
  // setTimeout is clearer than pulling in lodash.
  useEffect(() => {
    if (q.trim().length < 2) {
      setHits(null);
      return;
    }
    setLoading(true);
    const handle = setTimeout(async () => {
      try {
        const r = await api.globalSearch(q.trim());
        setHits([
          ...r.invoices.map((inv) => ({
            type: "invoice" as const,
            id: inv.id,
            primary:
              inv.invoice_number ||
              `${inv.supplier_legal_name || "—"} → ${inv.buyer_legal_name || "—"}`,
            secondary: `${inv.status} · ${inv.currency_code} ${inv.grand_total || "0"}`,
            href: inv.ingestion_job_id
              ? `/dashboard/jobs/${inv.ingestion_job_id}`
              : `/dashboard/invoices`,
          })),
          ...r.customers.map((c) => ({
            type: "customer" as const,
            id: c.id,
            primary: c.legal_name,
            secondary: `TIN ${c.tin}`,
            href: `/dashboard/customers/${c.id}`,
          })),
          ...r.audit.map((e) => ({
            type: "audit" as const,
            id: e.id,
            primary: e.action_type,
            secondary: `${e.affected_entity_type} ${e.affected_entity_id.slice(0, 12)}`,
            href: `/dashboard/audit?action_type=${encodeURIComponent(e.action_type)}`,
          })),
        ]);
      } catch {
        setHits([]);
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => clearTimeout(handle);
  }, [q]);

  // Click-outside closes the popover.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  // Press "/" anywhere to focus.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName;
      if (e.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div ref={containerRef} className="relative flex flex-1 items-center gap-2">
      <Search className="h-4 w-4 text-slate-400" aria-hidden />
      <input
        ref={inputRef}
        type="search"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setQ("");
            setOpen(false);
            inputRef.current?.blur();
          }
        }}
        placeholder="Search invoices, customers, audit log…  (press /)"
        aria-label="Search"
        className="h-9 max-w-md flex-1 bg-transparent text-sm text-ink placeholder-slate-400 outline-none"
      />
      {open && q.trim().length >= 2 && (
        <div className="absolute left-0 top-full z-50 mt-2 max-h-[480px] w-full max-w-xl overflow-y-auto rounded-xl border border-slate-100 bg-white shadow-lg">
          {loading && hits === null ? (
            <div className="px-4 py-6 text-center text-2xs text-slate-400">Searching…</div>
          ) : hits === null || hits.length === 0 ? (
            <div className="px-4 py-6 text-center text-2xs text-slate-400">
              No matches for &ldquo;{q}&rdquo;.
            </div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {hits.map((hit) => {
                const Icon =
                  hit.type === "invoice"
                    ? FileText
                    : hit.type === "customer"
                      ? Users
                      : ScrollText;
                return (
                  <li key={`${hit.type}-${hit.id}`}>
                    <Link
                      href={hit.href}
                      onClick={() => setOpen(false)}
                      className="flex items-start gap-3 px-4 py-3 text-2xs hover:bg-slate-50"
                    >
                      <Icon className="mt-0.5 h-4 w-4 text-slate-400" />
                      <div className="flex-1">
                        <div className="font-medium text-ink">{hit.primary || "—"}</div>
                        <div className="text-slate-500">{hit.secondary}</div>
                      </div>
                      <span
                        className={cn(
                          "rounded-sm px-1.5 py-0.5 text-[10px] uppercase tracking-wider",
                          hit.type === "invoice"
                            ? "bg-success/10 text-success"
                            : hit.type === "customer"
                              ? "bg-signal/10 text-ink"
                              : "bg-slate-100 text-slate-500",
                        )}
                      >
                        {hit.type}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
