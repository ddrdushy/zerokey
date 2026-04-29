"use client";

// Settings → Billing tab. Read-only today — shows the current
// subscription, current-period usage, and the available plan
// catalog. Plan changes / payment methods land with the Stripe
// wiring slice.

import { useEffect, useState } from "react";
import { CreditCard, Loader2, Sparkles } from "lucide-react";

import {
  api,
  ApiError,
  type BillingPlan,
  type BillingSubscription,
  type BillingUsage,
} from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { SettingsTabs } from "@/components/settings/SettingsTabs";
import { cn } from "@/lib/utils";

type Overview = {
  subscription: BillingSubscription | null;
  usage: BillingUsage;
  available_plans: BillingPlan[];
};

export default function BillingSettingsPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getBillingOverview()
      .then(setOverview)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          setError("You are not a member of this organization.");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load.");
      });
  }, []);

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Settings
          </h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            Organization, members, and platform integrations
          </p>
        </header>
        <SettingsTabs />

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error"
          >
            {error}
          </div>
        )}

        {overview === null && !error ? (
          <Loading />
        ) : overview === null ? null : (
          <>
            <CurrentSubscription
              subscription={overview.subscription}
              usage={overview.usage}
            />
            <PlanCatalog
              plans={overview.available_plans}
              currentSlug={overview.subscription?.plan.slug ?? null}
            />
          </>
        )}
      </div>
    </AppShell>
  );
}

function CurrentSubscription({
  subscription,
  usage,
}: {
  subscription: BillingSubscription | null;
  usage: BillingUsage;
}) {
  if (!subscription) {
    return (
      <section className="rounded-xl border border-slate-100 bg-white p-6">
        <p className="text-2xs text-slate-500">
          No active subscription on this organization. Pick a plan below
          to get started — or contact support if you think this is
          wrong.
        </p>
      </section>
    );
  }

  const plan = subscription.plan;
  const overagePct =
    plan.included_invoices_per_month > 0
      ? Math.min(
          100,
          Math.round((usage.count / plan.included_invoices_per_month) * 100),
        )
      : 0;
  const isOver = usage.overage_count > 0;

  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-2">
          <CreditCard className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-semibold text-ink">
            Current subscription
          </h2>
        </div>
        <StatusBadge status={subscription.status} />
      </header>
      <div className="grid gap-5 px-5 py-4 md:grid-cols-2">
        <div>
          <div className="text-2xs uppercase tracking-wider text-slate-400">
            Plan
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="font-display text-2xl font-bold text-ink">
              {plan.name}
            </span>
            <span className="text-2xs text-slate-500">
              {plan.monthly_price_cents > 0
                ? `${formatPrice(plan.monthly_price_cents, plan.billing_currency)} / month`
                : "Custom pricing"}
            </span>
          </div>
          {subscription.trial_ends_at && (
            <div className="mt-2 text-2xs text-slate-500">
              Trial ends{" "}
              {new Date(subscription.trial_ends_at).toLocaleDateString()}
            </div>
          )}
          {subscription.current_period_end && (
            <div className="mt-1 text-2xs text-slate-500">
              Renews{" "}
              {new Date(
                subscription.current_period_end,
              ).toLocaleDateString()}
            </div>
          )}
        </div>
        <div>
          <div className="text-2xs uppercase tracking-wider text-slate-400">
            Invoices this period
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="font-display text-2xl font-bold text-ink">
              {usage.count.toLocaleString()}
            </span>
            <span className="text-2xs text-slate-500">
              {plan.included_invoices_per_month > 0
                ? ` / ${plan.included_invoices_per_month.toLocaleString()} included`
                : "no limit"}
            </span>
          </div>
          {plan.included_invoices_per_month > 0 && (
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-slate-100">
              <div
                className={cn(
                  "h-full",
                  isOver ? "bg-warning" : "bg-success",
                )}
                style={{ width: `${overagePct}%` }}
              />
            </div>
          )}
          {isOver && (
            <div className="mt-2 text-2xs text-warning">
              {usage.overage_count.toLocaleString()} overage invoice
              {usage.overage_count === 1 ? "" : "s"} ·{" "}
              {formatPrice(
                usage.overage_count * plan.per_overage_cents,
                plan.billing_currency,
              )}{" "}
              expected
            </div>
          )}
        </div>
      </div>
      <footer className="border-t border-slate-100 px-5 py-3 text-[10px] text-slate-400">
        Pick a plan below to subscribe through Stripe checkout.
      </footer>
    </section>
  );
}

function PlanCatalog({
  plans,
  currentSlug,
}: {
  plans: BillingPlan[];
  currentSlug: string | null;
}) {
  // Slice 65 — Subscribe button. Posts to /billing/checkout/ and
  // redirects the browser to Stripe-hosted checkout. Per-plan
  // local pending state so the user sees which one is loading
  // when several are visible simultaneously.
  const [pendingPlanId, setPendingPlanId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubscribe(planId: string) {
    setError(null);
    setPendingPlanId(planId);
    try {
      const here = window.location.origin;
      const res = await api.startCheckout({
        plan_id: planId,
        billing_cycle: "monthly",
        success_url: `${here}/dashboard/settings/billing?checkout=success`,
        cancel_url: `${here}/dashboard/settings/billing?checkout=cancel`,
      });
      // Hard redirect to Stripe — they manage the checkout from
      // here; we re-enter via webhook + the success_url redirect.
      window.location.href = res.checkout_url;
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Couldn't start checkout.",
      );
      setPendingPlanId(null);
    }
  }

  if (plans.length === 0) return null;
  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-semibold text-ink">Available plans</h2>
        </div>
      </header>
      {error && (
        <div
          role="alert"
          className="mx-5 mt-4 rounded-md border border-error bg-error/5 px-3 py-2 text-2xs text-error"
        >
          {error}
        </div>
      )}
      <div className="grid gap-3 px-5 py-4 md:grid-cols-2 lg:grid-cols-4">
        {plans.map((plan) => {
          const isCurrent = plan.slug === currentSlug;
          const features = plan.features as Record<string, boolean>;
          const isPaid = plan.monthly_price_cents > 0;
          const isCustom = !isPaid;
          const isPending = pendingPlanId === plan.id;
          return (
            <div
              key={plan.id}
              className={cn(
                "flex flex-col gap-2 rounded-md border p-4",
                isCurrent
                  ? "border-ink/30 bg-slate-50"
                  : "border-slate-100",
              )}
            >
              <div className="flex items-baseline justify-between">
                <span className="font-display text-base font-semibold text-ink">
                  {plan.name}
                </span>
                {isCurrent && (
                  <span className="rounded-sm bg-ink px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-paper">
                    Current
                  </span>
                )}
              </div>
              <div className="text-2xs text-slate-500">{plan.description}</div>
              <div className="mt-1 font-display text-2xl font-bold text-ink">
                {isPaid
                  ? formatPrice(plan.monthly_price_cents, plan.billing_currency)
                  : "Custom"}
                {isPaid && (
                  <span className="text-2xs font-normal text-slate-400">
                    {" "}/ mo
                  </span>
                )}
              </div>
              <ul className="mt-1 flex flex-col gap-1 text-2xs text-slate-600">
                <li>
                  <strong>
                    {plan.included_invoices_per_month > 0
                      ? plan.included_invoices_per_month.toLocaleString()
                      : "Unlimited"}
                  </strong>{" "}
                  invoices/mo
                </li>
                <li>
                  <strong>
                    {plan.included_users > 0 ? plan.included_users : "∞"}
                  </strong>{" "}
                  users
                </li>
                <li>
                  <strong>
                    {plan.included_api_keys > 0
                      ? plan.included_api_keys
                      : "∞"}
                  </strong>{" "}
                  API keys
                </li>
                {features.webhooks && <li>Webhooks</li>}
                {features.sso && <li>SSO</li>}
                {features.consolidated_b2c && <li>B2C consolidation</li>}
                {features.priority_support && <li>Priority support</li>}
              </ul>
              <div className="mt-2">
                {isCurrent ? (
                  <Button size="sm" variant="ghost" disabled className="w-full">
                    Current plan
                  </Button>
                ) : isCustom ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="w-full"
                    onClick={() =>
                      window.open(
                        "mailto:sales@zerokey.symprio.com?subject=Custom%20plan%20enquiry",
                        "_self",
                      )
                    }
                  >
                    Talk to sales
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    className="w-full"
                    onClick={() => onSubscribe(plan.id)}
                    disabled={isPending || pendingPlanId !== null}
                  >
                    {isPending ? (
                      <>
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        Redirecting…
                      </>
                    ) : (
                      "Subscribe"
                    )}
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function StatusBadge({ status }: { status: BillingSubscription["status"] }) {
  const cls =
    status === "active"
      ? "bg-success/10 text-success"
      : status === "trialing"
        ? "bg-signal/15 text-ink"
        : status === "past_due"
          ? "bg-warning/10 text-warning"
          : "bg-slate-100 text-slate-500";
  return (
    <span
      className={`inline-flex rounded-sm px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${cls}`}
    >
      {status}
    </span>
  );
}

function Loading() {
  return (
    <div className="grid place-items-center py-24 text-2xs uppercase tracking-wider text-slate-400">
      Loading billing…
    </div>
  );
}

function formatPrice(cents: number, currency: string): string {
  const amount = cents / 100;
  return `${currency} ${amount.toLocaleString(undefined, {
    minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  })}`;
}
