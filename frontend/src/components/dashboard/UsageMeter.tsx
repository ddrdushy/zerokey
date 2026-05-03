"use client";

// Slice 100 — current-period usage meter on the main dashboard.
//
// Per PRD Domain 10 ("usage meter"): "The customer's current
// month's usage against their quota is visible on the dashboard
// with appropriate amber and red thresholds. Approaching-limit
// notifications are sent at 80%, 90%, and 100%."
//
// Reads /billing/overview/. If the org has no subscription the
// component renders nothing — the trial bootstrap fills this in
// for fresh signups; existing tenants without one fall back to
// the billing settings page.

import Link from "next/link";
import { useEffect, useState } from "react";
import { CreditCard } from "lucide-react";

import { api, type BillingSubscription, type BillingUsage } from "@/lib/api";
import { cn } from "@/lib/utils";

type Overview = {
  subscription: BillingSubscription | null;
  usage: BillingUsage;
};

export function UsageMeter() {
  const [data, setData] = useState<Overview | null>(null);

  useEffect(() => {
    api
      .getBillingOverview()
      .then((d) =>
        setData({
          subscription: d.subscription,
          usage: d.usage,
        }),
      )
      .catch(() => setData(null));
  }, []);

  if (!data || !data.subscription) return null;

  const plan = data.subscription.plan;
  const usage = data.usage;
  const limit = plan.included_invoices_per_month;
  const pct = limit > 0 ? Math.min(100, Math.round((usage.count / limit) * 100)) : 0;

  // Amber at 80%, red at 100% per PRD.
  const tone =
    limit === 0
      ? "neutral"
      : pct >= 100
        ? "error"
        : pct >= 80
          ? "warning"
          : "ok";

  return (
    <Link
      href="/dashboard/settings/billing"
      className="group flex items-center gap-4 rounded-xl border border-slate-100 bg-white px-5 py-4 transition hover:border-ink/30 hover:shadow-sm"
    >
      <div className="grid h-10 w-10 place-items-center rounded-md bg-ink/5">
        <CreditCard className="h-4 w-4 text-ink" />
      </div>
      <div className="flex-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="text-2xs font-medium uppercase tracking-wider text-slate-400">
            {plan.name} · this period
          </span>
          {data.subscription.cancel_at_period_end && (
            <span className="rounded-sm bg-warning/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-warning">
              Cancels at period end
            </span>
          )}
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="font-display text-xl font-bold text-ink">
            {usage.count.toLocaleString()}
          </span>
          <span className="text-2xs text-slate-500">
            {limit > 0 ? `/ ${limit.toLocaleString()} invoices` : "no limit"}
          </span>
          {usage.overage_count > 0 && (
            <span className="text-2xs text-warning">
              · {usage.overage_count.toLocaleString()} overage
            </span>
          )}
        </div>
        {limit > 0 && (
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-slate-100">
            <div
              className={cn(
                "h-full transition-all",
                tone === "error"
                  ? "bg-error"
                  : tone === "warning"
                    ? "bg-warning"
                    : "bg-success",
              )}
              style={{ width: `${pct}%` }}
            />
          </div>
        )}
      </div>
    </Link>
  );
}
