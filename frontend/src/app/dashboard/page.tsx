"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { api, type Me, type IngestionJob, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { DropZone } from "@/components/DropZone";

export default function DashboardPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .me()
      .then(async (data) => {
        setMe(data);
        const list = await api.listJobs().catch(() => []);
        setJobs(list);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/sign-in");
        }
      })
      .finally(() => setLoading(false));
  }, [router]);

  // Poll while any job is still in flight. Stops once everything is terminal.
  useEffect(() => {
    const TERMINAL = new Set(["validated", "rejected", "cancelled", "error", "ready_for_review"]);
    const inFlight = jobs.some((j) => !TERMINAL.has(j.status));
    if (!inFlight) return;
    const handle = setInterval(async () => {
      const list = await api.listJobs().catch(() => null);
      if (list) setJobs(list);
    }, 2000);
    return () => clearInterval(handle);
  }, [jobs]);

  function onUploaded(job: IngestionJob) {
    setJobs((prev) => [job, ...prev]);
  }

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
        <Card label="Total uploads" value={String(jobs.length)} />
        <Card
          label="Awaiting extraction"
          value={String(jobs.filter((j) => j.status === "received").length)}
        />
        <Card
          label="Submitted to LHDN"
          value={String(jobs.filter((j) => j.status === "validated").length)}
        />
      </section>

      <DropZone onUploaded={onUploaded} />

      <section>
        <h2 className="text-xl font-semibold">Recent uploads</h2>
        {jobs.length === 0 ? (
          <p className="mt-3 text-base text-slate-400">
            No uploads yet. Drop a file above to get started.
          </p>
        ) : (
          <ul className="mt-4 divide-y divide-slate-100 border-y border-slate-100">
            {jobs.map((j) => (
              <li key={j.id}>
                <button
                  type="button"
                  onClick={() => router.push(`/dashboard/jobs/${j.id}`)}
                  className="flex w-full items-center justify-between py-3 text-left hover:bg-slate-50"
                >
                  <div>
                    <div className="text-base font-medium">{j.original_filename}</div>
                    <div className="text-2xs uppercase tracking-wider text-slate-400">
                      {j.source_channel} · {(j.file_size / 1024).toFixed(1)} KB ·{" "}
                      {new Date(j.upload_timestamp).toLocaleString()}
                    </div>
                  </div>
                  <span
                    className={[
                      "rounded-full px-3 py-1 text-2xs font-medium",
                      j.status === "validated" || j.status === "ready_for_review"
                        ? "bg-success/10 text-success"
                        : j.status === "error" || j.status === "rejected"
                          ? "bg-error/10 text-error"
                          : "bg-slate-100 text-slate-600",
                    ].join(" ")}
                  >
                    {j.status.replace(/_/g, " ")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
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
