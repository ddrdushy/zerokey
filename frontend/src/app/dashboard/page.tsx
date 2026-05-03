"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Activity, CircleCheck, Inbox, ScrollText } from "lucide-react";

import {
  api,
  type AuditStats,
  type IngestionJob,
  type Me,
  type Throughput,
  ApiError,
} from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { DropZone } from "@/components/DropZone";
import { HeroCard } from "@/components/dashboard/HeroCard";
import { OnboardingChecklist } from "@/components/dashboard/OnboardingChecklist";
import { StatsStrip, type Stat } from "@/components/dashboard/StatsStrip";
import { ThroughputChart } from "@/components/dashboard/ThroughputChart";
import { CompliancePosture } from "@/components/dashboard/CompliancePosture";
import { UsageMeter } from "@/components/dashboard/UsageMeter";

export default function DashboardPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [auditStats, setAuditStats] = useState<AuditStats | null>(null);
  const [throughput, setThroughput] = useState<Throughput | null>(null);
  const [loading, setLoading] = useState(true);

  async function refreshDashboardData() {
    const [list, stats, tput] = await Promise.all([
      api.listJobs().catch(() => []),
      api.auditStats().catch(() => null),
      api.throughput().catch(() => null),
    ]);
    setJobs(list);
    if (stats) setAuditStats(stats);
    if (tput) setThroughput(tput);
  }

  useEffect(() => {
    api
      .me()
      .then(async (data) => {
        setMe(data);
        await refreshDashboardData();
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
    const handle = setInterval(() => {
      refreshDashboardData();
    }, 2000);
    return () => clearInterval(handle);
  }, [jobs]);

  function onUploaded(job: IngestionJob) {
    // Slice 101 — ZIP uploads return a BUNDLE parent. The parent
    // never enters the extraction pipeline; the children do. Stay
    // on the dashboard in that case so the user sees the unpacked
    // entries land in "recent uploads".
    if (job.status === "bundle") {
      refreshDashboardData();
      return;
    }
    // Single-file upload: drop the user straight into the review
    // surface — the dashboard is for monitoring, but the moment
    // after an upload they want to see the extracted fields. The
    // review page polls until the job settles, so it works whether
    // structuring takes 1s or 30s.
    router.push(`/dashboard/jobs/${job.id}`);
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

  const validated = jobs.filter((j) => j.status === "validated").length;
  const inFlight = jobs.filter(
    (j) => j.status !== "validated" && j.status !== "rejected" && j.status !== "error",
  ).length;
  const errored = jobs.filter((j) => j.status === "error" || j.status === "rejected").length;
  const needsReview = jobs.filter((j) => j.status === "ready_for_review").length;

  const auditSpark = auditStats?.sparkline.map((p) => p.count) ?? undefined;
  const uploadsSpark = throughput?.series.map((p) => p.validated + p.review) ?? undefined;

  const stats: Stat[] = [
    {
      label: "Total uploads",
      value: String(jobs.length),
      icon: Inbox,
      tone: "neutral",
      spark: uploadsSpark,
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
      value: auditStats ? String(auditStats.total) : "—",
      icon: ScrollText,
      tone: "neutral",
      spark: auditSpark,
    },
  ];

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <HeroCard organizationName={orgName} validatedThisMonth={validated} />

        {/* Onboarding checklist hides itself once dismissed or when
            its endpoint fails. Returning-user dashboards never see it. */}
        <OnboardingChecklist />

        {/* DropZone right after the hero so the action lives next to the
            invitation. Stats + charts are monitoring views and belong
            below the call-to-action — for a fresh user, four zero
            counters before the upload UI was friction. */}
        <DropZone onUploaded={onUploaded} />

        <StatsStrip stats={stats} />

        <UsageMeter />

        <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
          <ThroughputChart data={throughput?.series} />
          <CompliancePosture validated={validated} needsReview={needsReview} failed={errored} />
        </div>

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
                  <Link
                    href={`/dashboard/jobs/${j.id}`}
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
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </AppShell>
  );
}
