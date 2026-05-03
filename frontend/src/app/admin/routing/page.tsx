"use client";

// Slice 99 — Engine routing-rule editor.
//
// Lists every EngineRoutingRule grouped by capability (the chains
// the structurer/extractor walk in priority order) and lets the
// admin toggle is_active or change priority inline. Lower priority
// number = tried first.

import { useEffect, useMemo, useState } from "react";

import { api, type AdminRoutingRule } from "@/lib/api";
import { AdminShell } from "@/components/admin/AdminShell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function AdminRoutingPage() {
  const [rules, setRules] = useState<AdminRoutingRule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function refresh() {
    try {
      setRules(await api.adminListRoutingRules());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed.");
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  async function patch(rule: AdminRoutingRule, body: Partial<AdminRoutingRule>) {
    setBusy(rule.id);
    try {
      await api.adminUpdateRoutingRule(rule.id, body);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed.");
    } finally {
      setBusy(null);
    }
  }

  const grouped = useMemo(() => {
    if (!rules) return null;
    const map = new Map<string, AdminRoutingRule[]>();
    for (const r of rules) {
      const arr = map.get(r.capability) ?? [];
      arr.push(r);
      map.set(r.capability, arr);
    }
    return Array.from(map.entries()).map(([cap, rows]) => ({
      capability: cap,
      rows: rows.sort((a, b) => a.priority - b.priority),
    }));
  }, [rules]);

  return (
    <AdminShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">Routing rules</h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            Lower priority = tried first · inactive engines are skipped
          </p>
        </header>

        {error && (
          <div role="alert" className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error">
            {error}
          </div>
        )}

        {grouped === null ? (
          <Loading />
        ) : (
          <div className="flex flex-col gap-6">
            {grouped.map(({ capability, rows }) => (
              <section key={capability}>
                <h2 className="text-2xs font-medium uppercase tracking-wider text-slate-400">
                  {capability}
                </h2>
                <div className="mt-2 overflow-hidden rounded-xl border border-slate-100 bg-white">
                  <table className="w-full text-2xs">
                    <thead className="bg-slate-50 text-slate-400">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Priority</th>
                        <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Engine</th>
                        <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Engine status</th>
                        <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">Active in chain</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {rows.map((r) => (
                        <tr key={r.id} className="hover:bg-slate-50">
                          <td className="px-3 py-3">
                            <input
                              type="number"
                              defaultValue={r.priority}
                              onBlur={(e) => {
                                const n = Number(e.target.value);
                                if (!Number.isNaN(n) && n !== r.priority) patch(r, { priority: n });
                              }}
                              className="w-20 rounded-md border border-slate-200 px-2 py-1 text-xs"
                            />
                          </td>
                          <td className="px-3 py-3">
                            <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
                              {r.engine_name}
                            </code>
                          </td>
                          <td className="px-3 py-3">
                            <span
                              className={cn(
                                "rounded-sm px-1.5 py-0.5 text-[10px] uppercase tracking-wider",
                                r.engine_status === "active"
                                  ? "bg-success/10 text-success"
                                  : r.engine_status === "degraded"
                                    ? "bg-warning/10 text-warning"
                                    : "bg-slate-100 text-slate-500",
                              )}
                            >
                              {r.engine_status}
                            </span>
                          </td>
                          <td className="px-3 py-3 text-right">
                            <Button
                              variant={r.is_active ? "outline" : "default"}
                              size="sm"
                              disabled={busy === r.id}
                              onClick={() => patch(r, { is_active: !r.is_active })}
                            >
                              {r.is_active ? "Disable in chain" : "Enable in chain"}
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </AdminShell>
  );
}

function Loading() {
  return (
    <div className="grid gap-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="h-32 animate-pulse rounded-xl border border-slate-100 bg-slate-50" />
      ))}
    </div>
  );
}
