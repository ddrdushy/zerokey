"use client";

// Slice 99 — Plans + pricing administration.
//
// Lists every Plan row (every tier × every version). Edit-in-place is
// disabled by design: a plan revision creates a new version row so
// historical Subscriptions keep resolving to the price they signed up
// at. The "Revise" button publishes a new version and deactivates the
// previous one for new sign-ups.

import { useEffect, useMemo, useState } from "react";

import { api, ApiError, type AdminPlan } from "@/lib/api";
import { AdminShell } from "@/components/admin/AdminShell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function AdminPlansPage() {
  const [plans, setPlans] = useState<AdminPlan[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<AdminPlan | null>(null);

  async function refresh() {
    try {
      setPlans(await api.adminListPlans());
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) return;
      setError(err instanceof Error ? err.message : "Failed to load plans.");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  // Group by slug so we render one block per plan-family with version
  // history beneath, instead of one flat list mixing tiers.
  const grouped = useMemo(() => {
    if (!plans) return null;
    const map = new Map<string, AdminPlan[]>();
    for (const p of plans) {
      const arr = map.get(p.slug) ?? [];
      arr.push(p);
      map.set(p.slug, arr);
    }
    return Array.from(map.entries()).map(([slug, rows]) => ({
      slug,
      rows: rows.sort((a, b) => b.version - a.version),
    }));
  }, [plans]);

  return (
    <AdminShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Plans + pricing
          </h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            Per BUSINESS_MODEL — versioned, effective-dated, never edited in place
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
            {grouped.map((group) => (
              <PlanFamilyCard
                key={group.slug}
                rows={group.rows}
                onEdit={(plan) => setEditing(plan)}
              />
            ))}
          </div>
        )}

        {editing && (
          <RevisePlanDialog
            plan={editing}
            onClose={() => setEditing(null)}
            onSaved={async () => {
              setEditing(null);
              await refresh();
            }}
          />
        )}
      </div>
    </AdminShell>
  );
}

function PlanFamilyCard({
  rows,
  onEdit,
}: {
  rows: AdminPlan[];
  onEdit: (p: AdminPlan) => void;
}) {
  const current = rows.find((r) => r.is_active) ?? rows[0];
  const history = rows.filter((r) => r.id !== current.id);

  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <div className="flex items-start justify-between border-b border-slate-100 px-5 py-4">
        <div>
          <div className="flex items-baseline gap-2">
            <h2 className="text-base font-semibold text-ink">{current.name}</h2>
            <span className="text-2xs uppercase tracking-wider text-slate-400">
              v{current.version}
            </span>
            {!current.is_active && (
              <span className="rounded-sm bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-slate-500">
                inactive
              </span>
            )}
            {current.is_public && current.is_active && (
              <span className="rounded-sm bg-success/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-success">
                public
              </span>
            )}
          </div>
          <p className="mt-1 max-w-2xl text-2xs text-slate-500">{current.description}</p>
        </div>
        <Button size="sm" variant="outline" onClick={() => onEdit(current)}>
          Revise (new version)
        </Button>
      </div>
      <div className="grid gap-4 px-5 py-4 sm:grid-cols-2 md:grid-cols-4">
        <Stat label="Monthly" value={`${current.billing_currency} ${(current.monthly_price_cents / 100).toFixed(0)}`} />
        <Stat label="Annual" value={`${current.billing_currency} ${(current.annual_price_cents / 100).toFixed(0)}`} />
        <Stat label="Invoices/mo" value={current.included_invoices_per_month === 0 ? "∞" : current.included_invoices_per_month.toLocaleString()} />
        <Stat label="Overage / inv" value={`${current.billing_currency} ${(current.per_overage_cents / 100).toFixed(2)}`} />
        <Stat label="Users" value={current.included_users === 0 ? "∞" : current.included_users} />
        <Stat label="API keys" value={current.included_api_keys === 0 ? "∞" : current.included_api_keys} />
        <Stat label="Tier" value={current.tier} />
        <Stat label="Stripe (mo)" value={current.stripe_price_id_monthly || "—"} />
      </div>
      <div className="border-t border-slate-100 px-5 py-3">
        <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">
          Features
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {Object.entries(current.features).length === 0 ? (
            <span className="text-2xs text-slate-400">No plan-level overrides — falls back to flag defaults.</span>
          ) : (
            Object.entries(current.features).map(([slug, enabled]) => (
              <span
                key={slug}
                className={cn(
                  "rounded-sm px-1.5 py-0.5 text-[10px] uppercase tracking-wider",
                  enabled ? "bg-success/10 text-success" : "bg-slate-100 text-slate-500",
                )}
              >
                {slug}: {enabled ? "on" : "off"}
              </span>
            ))
          )}
        </div>
      </div>
      {history.length > 0 && (
        <details className="border-t border-slate-100 px-5 py-3">
          <summary className="cursor-pointer text-2xs uppercase tracking-wider text-slate-400">
            Version history ({history.length})
          </summary>
          <ul className="mt-2 space-y-1 text-2xs text-slate-600">
            {history.map((h) => (
              <li key={h.id}>
                v{h.version} · {h.billing_currency} {(h.monthly_price_cents / 100).toFixed(0)}/mo · {h.included_invoices_per_month} invoices ·{" "}
                {h.created_at ? new Date(h.created_at).toLocaleDateString() : "—"}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-0.5 text-sm font-medium text-ink">{value}</div>
    </div>
  );
}

function RevisePlanDialog({
  plan,
  onClose,
  onSaved,
}: {
  plan: AdminPlan;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState({
    name: plan.name,
    description: plan.description,
    monthly_price_cents: plan.monthly_price_cents,
    annual_price_cents: plan.annual_price_cents,
    included_invoices_per_month: plan.included_invoices_per_month,
    per_overage_cents: plan.per_overage_cents,
    included_users: plan.included_users,
    included_api_keys: plan.included_api_keys,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      await api.adminRevisePlan(plan.id, draft);
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-ink/40 px-4">
      <div className="w-full max-w-lg rounded-xl bg-white p-6">
        <h3 className="text-base font-semibold text-ink">Revise {plan.name}</h3>
        <p className="mt-1 text-2xs text-slate-500">
          Publishes v{plan.version + 1}. Existing customers stay on v{plan.version}.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <Field label="Name">
            <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
          </Field>
          <Field label="Monthly (cents)">
            <input type="number" value={draft.monthly_price_cents} onChange={(e) => setDraft({ ...draft, monthly_price_cents: Number(e.target.value) })} className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
          </Field>
          <Field label="Annual (cents)">
            <input type="number" value={draft.annual_price_cents} onChange={(e) => setDraft({ ...draft, annual_price_cents: Number(e.target.value) })} className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
          </Field>
          <Field label="Invoices/month">
            <input type="number" value={draft.included_invoices_per_month} onChange={(e) => setDraft({ ...draft, included_invoices_per_month: Number(e.target.value) })} className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
          </Field>
          <Field label="Overage / inv (cents)">
            <input type="number" value={draft.per_overage_cents} onChange={(e) => setDraft({ ...draft, per_overage_cents: Number(e.target.value) })} className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
          </Field>
          <Field label="Users">
            <input type="number" value={draft.included_users} onChange={(e) => setDraft({ ...draft, included_users: Number(e.target.value) })} className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
          </Field>
          <Field label="API keys">
            <input type="number" value={draft.included_api_keys} onChange={(e) => setDraft({ ...draft, included_api_keys: Number(e.target.value) })} className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
          </Field>
          <Field label="Description" full>
            <textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} rows={2} className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
          </Field>
        </div>
        {err && <div className="mt-3 rounded-md border border-error bg-error/5 px-3 py-2 text-2xs text-error">{err}</div>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button size="sm" onClick={save} disabled={busy}>{busy ? "Publishing…" : "Publish revision"}</Button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, full, children }: { label: string; full?: boolean; children: React.ReactNode }) {
  return (
    <label className={cn("flex flex-col gap-1", full && "sm:col-span-2")}>
      <span className="text-[10px] uppercase tracking-wider text-slate-400">{label}</span>
      {children}
    </label>
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
