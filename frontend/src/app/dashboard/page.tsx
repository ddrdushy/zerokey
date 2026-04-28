"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, CircleCheck, Inbox, ScrollText } from "lucide-react";

import { api, type IngestionJob, type Me, ApiError } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { DropZone } from "@/components/DropZone";
import { HeroCard } from "@/components/dashboard/HeroCard";
import { StatsStrip, type Stat } from "@/components/dashboard/StatsStrip";
import { ThroughputChart } from "@/components/dashboard/ThroughputChart";
import { CompliancePosture } from "@/components/dashboard/CompliancePosture";

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

  // Poll while in-flight jobs exist.
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

  if (loading || !me) {
    return (
      <AppShell>
        <div className="grid place-items-center py-24 text-slate-400">Loading…</div>
      </AppShell>
    );
  }

  const activeMembership = me.memberships.find(
    (m) => m.organization.id === me.active_organization_id,
  );
  const orgName = activeMembership?.organization.legal_name ?? "your organization";
  const localPart = me.email.split("@")[0].split(/[._-]/)[0] || "there";
  const firstName = localPart.charAt(0).toUpperCase() + localPart.slice(1);

  const validated = jobs.filter((j) => j.status === "validated").length;
  const inFlight = jobs.filter(
    (j) => j.status !== "validated" && j.status !== "rejected" && j.status !== "error",
  ).length;
  const errored = jobs.filter((j) => j.status === "error" || j.status === "rejected").length;
  const needsReview = jobs.filter((j) => j.status === "ready_for_review").length;

  const stats: Stat[] = [
    {
      label: "Total uploads",
      value: String(jobs.length),
      icon: Inbox,
      tone: "neutral",
    },
    {
      label: "In flight",
      value: String(inFlight),
      icon: Activity,
      tone: "info",
    },
    {
      label: "Validated by LHDN",
      value: String(validated),
      icon: CircleCheck,
      tone: "success",
    },
    {
      label: "Audit events",
      // Proxy: each job emits roughly four chain events. Replaced by the
      // real audit-log count once that endpoint lands.
      value: String(jobs.length * 4 + 5),
      icon: ScrollText,
      tone: "neutral",
    },
  ];

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <HeroCard
          firstName={firstName}
          organizationName={orgName}
          validatedThisMonth={validated}
        />

        <StatsStrip stats={stats} />

        <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
          <ThroughputChart />
          <CompliancePosture
            validated={validated}
            needsReview={needsReview}
            failed={errored}
          />
        </div>

        <DropZone onUploaded={onUploaded} />

        <section>
          <div className="flex items-baseline justify-between">
            <h2 className="text-base font-semibold">Recent uploads</h2>
            {jobs.length > 0 && (
              <span className="text-2xs uppercase tracking-wider text-slate-400">
                {jobs.length} total
              </span>
            )}
          </div>
          {jobs.length === 0 ? (
            <p className="mt-3 text-base text-slate-400">
              No uploads yet. Drop a file above to get started.
            </p>
          ) : (
            <ul className="mt-4 divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-100 bg-white">
              {jobs.map((j) => (
                <li key={j.id}>
                  <button
                    type="button"
                    onClick={() => router.push(`/dashboard/jobs/${j.id}`)}
                    className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-slate-50"
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
      </div>
    </AppShell>
  );
}
