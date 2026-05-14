"use client";

// Phase 4 of PORTAL_PLAN.md — per-org monthly consolidation view.
//
// Mirrors the Invoici-style monthly buckets. Each calendar month gets
// one row carrying:
//   - month label
//   - status pill (Complete / In Progress / Needs action / No activity)
//   - count + total amount
//   - drill-in link to /dashboard/invoices filtered to that month
//
// The page itself doesn't trigger any submissions — it's a triage
// surface. The customer clicks through into the existing invoices list
// to act on what's outstanding.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { AlertTriangle, ArrowLeft, CheckCircle2, Clock, Layers, Loader2, Minus } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { useRouter as useRouterNav } from "next/navigation";

type Bucket = Awaited<ReturnType<typeof api.getMonthlyBuckets>>["results"][number];

const STATUS_COPY: Record<Bucket["pill"], { label: string; tone: string; icon: any }> = {
  complete: {
    label: "Complete",
    tone: "bg-success/10 text-success",
    icon: CheckCircle2,
  },
  in_progress: {
    label: "In progress",
    tone: "bg-info/10 text-info",
    icon: Clock,
  },
  needs_action: {
    label: "Needs action",
    tone: "bg-warning/10 text-warning",
    icon: AlertTriangle,
  },
  no_activity: {
    label: "No activity",
    tone: "bg-slate-100 text-slate-500",
    icon: Minus,
  },
};

export default function MonthlyBucketsPage() {
  const params = useParams<{ orgId: string }>();
  const router = useRouter();
  const [buckets, setBuckets] = useState<Bucket[] | null>(null);
  const [orgName, setOrgName] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setBuckets(null);

    // Two parallel fetches — the buckets and the org name from the portal summary.
    Promise.all([
      api.getMonthlyBuckets({ organizationId: params.orgId, months: 12 }),
      api.getPortalSummary(),
    ])
      .then(([bucketResp, portal]) => {
        if (cancelled) return;
        setBuckets(bucketResp.results);
        const match = portal.results.find((r) => r.organization_id === params.orgId);
        setOrgName(match?.legal_name ?? "");
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/portal");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load monthly buckets.");
        setBuckets([]);
      });
    return () => {
      cancelled = true;
    };
  }, [params.orgId, router]);

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <Link
          href="/portal"
          className="inline-flex items-center gap-1 text-2xs font-medium text-slate-500 hover:text-ink"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to organisations
        </Link>

        <header className="flex flex-col gap-1">
          <h1 className="font-display text-2xl font-bold tracking-tight">
            {orgName || "Monthly consolidation"}
          </h1>
          <p className="text-2xs text-slate-500">
            Each month rolls up every Invoice / CN / DN issued in that period. Drill into a
            month to see the documents and act on anything outstanding.
          </p>
        </header>

        {error && (
          <div role="alert" className="rounded-md border border-error/30 bg-error/5 px-3 py-2 text-2xs text-error">
            {error}
          </div>
        )}

        {buckets === null ? (
          <div className="flex items-center gap-2 rounded-md border border-slate-100 bg-white p-6 text-2xs text-slate-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading…
          </div>
        ) : (
          <BucketGrid buckets={buckets} />
        )}
      </div>
    </AppShell>
  );
}

function BucketGrid({ buckets }: { buckets: Bucket[] }) {
  // Group into Needs Action / Current month / Completed sections.
  const now = new Date();
  const currentKey = `${now.getFullYear()}-${now.getMonth() + 1}`;
  const needsAction = buckets.filter((b) => b.pill === "needs_action");
  const current = buckets.find(
    (b) => `${b.year}-${b.month}` === currentKey && b.pill !== "needs_action",
  );
  const completed = buckets.filter(
    (b) =>
      b.pill !== "needs_action" &&
      !(b.year === now.getFullYear() && b.month === now.getMonth() + 1),
  );

  return (
    <div className="flex flex-col gap-8">
      {needsAction.length > 0 && (
        <Section title="Needs your attention" subtitle="Months with one or more outstanding documents">
          <ul className="grid gap-2">
            {needsAction.map((b) => (
              <BucketRow key={`${b.year}-${b.month}`} bucket={b} />
            ))}
          </ul>
        </Section>
      )}

      {current && (
        <Section title="Current month" subtitle="">
          <BucketRow bucket={current} />
        </Section>
      )}

      <Section title="Earlier months" subtitle="Settled or in-flight months from the past year">
        <ul className="grid gap-2">
          {completed.map((b) => (
            <BucketRow key={`${b.year}-${b.month}`} bucket={b} />
          ))}
        </ul>
      </Section>
    </div>
  );
}

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="font-display text-base font-semibold text-ink">{title}</h2>
      {subtitle && <p className="mt-0.5 text-2xs text-slate-500">{subtitle}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function BucketRow({ bucket }: { bucket: Bucket }) {
  const copy = STATUS_COPY[bucket.pill];
  const Icon = copy.icon;
  // Date range for the drill-in filter — first day inclusive,
  // last day inclusive.
  const from = `${bucket.year}-${String(bucket.month).padStart(2, "0")}-01`;
  const lastDay = new Date(bucket.year, bucket.month, 0).getDate();
  const to = `${bucket.year}-${String(bucket.month).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`;

  return (
    <li className="rounded-md border border-slate-100 bg-white">
      <Link
        href={`/dashboard/invoices?from=${from}&to=${to}`}
        className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-slate-50"
      >
        <div className="flex items-center gap-3">
          <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-md ${copy.tone}`}>
            <Icon size={14} />
          </span>
          <div>
            <div className="text-sm font-semibold text-ink">{bucket.month_label}</div>
            <div className="text-2xs text-slate-500">
              {bucket.total_count} doc{bucket.total_count === 1 ? "" : "s"}
              {bucket.total_amount > 0 && (
                <>
                  {" · "}
                  RM {bucket.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {bucket.pill === "needs_action" && (
            <span className="text-2xs font-medium text-warning">
              {bucket.needs_action_count} pending
            </span>
          )}
          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${copy.tone}`}>
            {copy.label}
          </span>
        </div>
      </Link>
      {bucket.total_count > 0 && (
        <B2CConsolidationPanel year={bucket.year} month={bucket.month} />
      )}
    </li>
  );
}

function B2CConsolidationPanel({ year, month }: { year: number; month: number }) {
  const [preview, setPreview] = useState<{
    eligible_count: number;
    eligible_total: string;
    has_existing_parent: boolean;
    existing_parent_invoice_number: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  async function fetchPreview() {
    setError(null);
    try {
      const r = await api.previewConsolidatedB2C(year, month);
      setPreview({
        eligible_count: r.eligible_count,
        eligible_total: r.eligible_total,
        has_existing_parent: r.has_existing_parent,
        existing_parent_invoice_number: r.existing_parent_invoice_number,
      });
    } catch (err) {
      // 403 from the feature gate means consolidated_b2c is off for
      // this org — just hide the panel quietly.
      if (err instanceof ApiError && err.status === 403) {
        setUnavailable(true);
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load preview.");
    }
  }

  useEffect(() => {
    let cancelled = false;
    api
      .previewConsolidatedB2C(year, month)
      .then((r) => {
        if (cancelled) return;
        setPreview({
          eligible_count: r.eligible_count,
          eligible_total: r.eligible_total,
          has_existing_parent: r.has_existing_parent,
          existing_parent_invoice_number: r.existing_parent_invoice_number,
        });
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) setUnavailable(true);
      });
    return () => {
      cancelled = true;
    };
  }, [year, month]);

  if (unavailable) return null;
  if (preview === null) return null;
  // Nothing to do for this month — no parent, no eligibles.
  if (preview.eligible_count === 0 && !preview.has_existing_parent) return null;

  async function onBuild() {
    setBusy(true);
    setError(null);
    try {
      await api.buildConsolidatedB2C(year, month);
      await fetchPreview();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Build failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 border-t border-slate-100 bg-slate-50/50 px-4 py-3 md:flex-row md:items-center md:justify-between">
      <div className="flex items-start gap-2 text-2xs text-slate-600">
        <Layers size={13} className="mt-0.5 shrink-0 text-slate-400" />
        {preview.has_existing_parent ? (
          <span>
            Consolidated B2C parent already built:{" "}
            <span className="font-mono text-ink">{preview.existing_parent_invoice_number}</span>
            . The {preview.eligible_count > 0 ? `${preview.eligible_count} additional ` : ""}eligible
            invoice{preview.eligible_count === 1 ? "" : "s"} can be left for next month, or you can
            cancel the existing parent first and rebuild.
          </span>
        ) : (
          <span>
            {preview.eligible_count} B2C invoice{preview.eligible_count === 1 ? "" : "s"} eligible
            for consolidation · RM{" "}
            {Number(preview.eligible_total).toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
            . Roll them up into a single LHDN submission.
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        {!preview.has_existing_parent && preview.eligible_count > 0 && (
          <button
            type="button"
            onClick={onBuild}
            disabled={busy}
            className="inline-flex items-center justify-center rounded-md bg-ink px-3 py-1.5 text-2xs font-medium text-paper hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Building…" : "Build consolidated"}
          </button>
        )}
      </div>
      {error && (
        <span className="text-2xs text-error">{error}</span>
      )}
    </div>
  );
}
