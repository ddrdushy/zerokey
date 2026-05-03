"use client";

// Slice 99 — Feature flag administration.
//
// Lists every declared FeatureFlag with its global default. Toggling
// the default takes effect immediately for every tenant that has no
// per-org override. Per-org overrides are managed from
// /admin/tenants/[id] (the override panel lives next to the
// subscription editor).

import { useEffect, useMemo, useState } from "react";
import { Flag, ToggleLeft, ToggleRight } from "lucide-react";

import { api, ApiError, type AdminFeatureFlag } from "@/lib/api";
import { AdminShell } from "@/components/admin/AdminShell";
import { cn } from "@/lib/utils";

export default function AdminFlagsPage() {
  const [flags, setFlags] = useState<AdminFeatureFlag[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busySlug, setBusySlug] = useState<string | null>(null);

  async function refresh() {
    try {
      setFlags(await api.adminListFeatureFlags());
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) return;
      setError(err instanceof Error ? err.message : "Failed to load.");
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  async function toggle(flag: AdminFeatureFlag) {
    setBusySlug(flag.slug);
    try {
      await api.adminUpdateFeatureFlag(flag.slug, {
        default_enabled: !flag.default_enabled,
      });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed.");
    } finally {
      setBusySlug(null);
    }
  }

  // Group by category so the long list reads as a few sections, not a wall.
  const grouped = useMemo(() => {
    if (!flags) return null;
    const map = new Map<string, AdminFeatureFlag[]>();
    for (const f of flags) {
      const key = f.category || "uncategorised";
      const arr = map.get(key) ?? [];
      arr.push(f);
      map.set(key, arr);
    }
    return Array.from(map.entries()).sort();
  }, [flags]);

  return (
    <AdminShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">Feature flags</h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            Resolution: per-org override → plan default → global default
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
            {grouped.map(([cat, rows]) => (
              <section key={cat}>
                <h2 className="text-2xs font-medium uppercase tracking-wider text-slate-400">
                  {cat}
                </h2>
                <div className="mt-2 overflow-hidden rounded-xl border border-slate-100 bg-white">
                  <table className="w-full text-2xs">
                    <thead className="bg-slate-50 text-slate-400">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Flag</th>
                        <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Description</th>
                        <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">Overrides</th>
                        <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">Default</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {rows.map((f) => (
                        <tr key={f.id} className="hover:bg-slate-50">
                          <td className="px-3 py-3">
                            <div className="font-medium text-ink">{f.display_name}</div>
                            <code className="text-[10px] text-slate-400">{f.slug}</code>
                          </td>
                          <td className="px-3 py-3 text-slate-600">{f.description}</td>
                          <td className="px-3 py-3 text-right text-slate-500">
                            {f.override_count > 0 ? `${f.override_count} org${f.override_count === 1 ? "" : "s"}` : "—"}
                          </td>
                          <td className="px-3 py-3 text-right">
                            <button
                              type="button"
                              onClick={() => toggle(f)}
                              disabled={busySlug === f.slug}
                              className={cn(
                                "inline-flex items-center gap-1 rounded-md px-2 py-1 text-2xs font-medium",
                                f.default_enabled
                                  ? "bg-success/10 text-success hover:bg-success/15"
                                  : "bg-slate-100 text-slate-500 hover:bg-slate-200",
                              )}
                            >
                              {f.default_enabled ? (
                                <>
                                  <ToggleRight className="h-3.5 w-3.5" />
                                  on
                                </>
                              ) : (
                                <>
                                  <ToggleLeft className="h-3.5 w-3.5" />
                                  off
                                </>
                              )}
                            </button>
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

        {grouped !== null && grouped.length === 0 && (
          <div className="grid place-items-center rounded-xl border border-slate-100 bg-white py-12 text-2xs text-slate-400">
            <Flag className="h-6 w-6" />
            <p className="mt-2">No flags declared. Run the seed migration.</p>
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
        <div key={i} className="h-40 animate-pulse rounded-xl border border-slate-100 bg-slate-50" />
      ))}
    </div>
  );
}
