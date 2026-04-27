"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { api, type Me, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";

export default function DashboardPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .me()
      .then((data) => setMe(data))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/sign-in");
          return;
        }
        // Other errors leave us on the page so the message is visible in the console.
      })
      .finally(() => setLoading(false));
  }, [router]);

  async function onLogout() {
    await api.logout();
    router.replace("/sign-in");
  }

  if (loading) {
    return (
      <main className="mx-auto flex min-h-screen max-w-3xl items-center justify-center px-4">
        <p className="text-slate-400">Loading…</p>
      </main>
    );
  }

  if (!me) {
    return (
      <main className="mx-auto flex min-h-screen max-w-3xl items-center justify-center px-4">
        <p className="text-slate-400">You are not signed in.</p>
      </main>
    );
  }

  const activeMembership = me.memberships.find(
    (m) => m.organization.id === me.active_organization_id,
  );

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-8 px-4 py-12 md:px-8">
      <header className="flex items-center justify-between">
        <div className="font-display text-xl font-bold tracking-tight">ZeroKey</div>
        <div className="flex items-center gap-4">
          <span className="text-2xs uppercase tracking-wider text-slate-400">{me.email}</span>
          <Button variant="ghost" size="sm" onClick={onLogout}>
            Sign out
          </Button>
        </div>
      </header>

      <section className="flex flex-col gap-2">
        <h1 className="font-display text-3xl font-bold tracking-tight">
          {activeMembership ? activeMembership.organization.legal_name : "No active organization"}
        </h1>
        {activeMembership && (
          <p className="text-base text-slate-600">
            Signed in as <span className="font-medium text-ink">{activeMembership.role}</span> ·
            TIN <span className="font-mono text-2xs">{activeMembership.organization.tin}</span>
          </p>
        )}
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <Card label="Invoices this month" value="0" />
        <Card label="Pending review" value="0" />
        <Card label="Submitted to LHDN" value="0" />
      </section>

      <section className="rounded-xl border border-slate-100 bg-white p-8">
        <h2 className="text-xl font-semibold">Drop your first invoice</h2>
        <p className="mt-2 max-w-2xl text-base text-slate-600">
          Phase 1 stops here. Ingestion, extraction, validation, and submission land in the
          subsequent phases per the roadmap.
        </p>
        <div className="mt-6 flex h-40 items-center justify-center rounded-lg border-2 border-dashed border-slate-200 bg-slate-50 text-slate-400">
          File drop will land here
        </div>
      </section>

      <section>
        <h2 className="text-xl font-semibold">Memberships</h2>
        <ul className="mt-4 divide-y divide-slate-100 border-y border-slate-100">
          {me.memberships.map((m) => (
            <li key={m.id} className="flex items-center justify-between py-3">
              <div>
                <div className="text-base font-medium">{m.organization.legal_name}</div>
                <div className="text-2xs uppercase tracking-wider text-slate-400">
                  Role: {m.role} · TIN {m.organization.tin}
                </div>
              </div>
              {m.organization.id === me.active_organization_id && (
                <span className="rounded-full bg-signal px-3 py-1 text-2xs font-medium text-ink">
                  Active
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-6">
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-2 font-display text-3xl font-bold tracking-tight">{value}</div>
    </div>
  );
}
