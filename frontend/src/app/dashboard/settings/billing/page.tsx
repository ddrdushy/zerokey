"use client";

// Settings → Billing tab. Read-only today — shows the current
// subscription, current-period usage, and the available plan
// catalog. Plan changes / payment methods land with the Stripe
// wiring slice.

import { useEffect, useState } from "react";
import {
  CreditCard,
  Download,
  ExternalLink,
  FileText,
  Loader2,
  Sparkles,
  XCircle,
} from "lucide-react";

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

  function loadOverview() {
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
  }

  useEffect(() => {
    loadOverview();
  }, []);

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">Settings</h1>
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
              onChanged={loadOverview}
              onError={setError}
            />
            <BillingInvoicesSection />
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
  onChanged,
  onError,
}: {
  subscription: BillingSubscription | null;
  usage: BillingUsage;
  onChanged: () => void;
  onError: (msg: string | null) => void;
}) {
  if (!subscription) {
    return (
      <section className="rounded-xl border border-slate-100 bg-white p-6">
        <p className="text-2xs text-slate-500">
          No active subscription on this organization. Pick a plan below to get started — or contact
          support if you think this is wrong.
        </p>
      </section>
    );
  }

  const plan = subscription.plan;
  const overagePct =
    plan.included_invoices_per_month > 0
      ? Math.min(100, Math.round((usage.count / plan.included_invoices_per_month) * 100))
      : 0;
  const isOver = usage.overage_count > 0;

  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-2">
          <CreditCard className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-semibold text-ink">Current subscription</h2>
        </div>
        <StatusBadge status={subscription.status} />
      </header>
      <div className="grid gap-5 px-5 py-4 md:grid-cols-2">
        <div>
          <div className="text-2xs uppercase tracking-wider text-slate-400">Plan</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="font-display text-2xl font-bold text-ink">{plan.name}</span>
            <span className="text-2xs text-slate-500">
              {plan.monthly_price_cents > 0
                ? `${formatPrice(plan.monthly_price_cents, plan.billing_currency)} / month`
                : "Custom pricing"}
            </span>
          </div>
          {subscription.trial_ends_at && (
            <div className="mt-2 text-2xs text-slate-500">
              Trial ends {new Date(subscription.trial_ends_at).toLocaleDateString()}
            </div>
          )}
          {subscription.current_period_end && (
            <div className="mt-1 text-2xs text-slate-500">
              Renews {new Date(subscription.current_period_end).toLocaleDateString()}
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
                className={cn("h-full", isOver ? "bg-warning" : "bg-success")}
                style={{ width: `${overagePct}%` }}
              />
            </div>
          )}
          {isOver && (
            <div className="mt-2 text-2xs text-warning">
              {usage.overage_count.toLocaleString()} overage invoice
              {usage.overage_count === 1 ? "" : "s"} ·{" "}
              {formatPrice(usage.overage_count * plan.per_overage_cents, plan.billing_currency)}{" "}
              expected
            </div>
          )}
        </div>
      </div>
      <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-5 py-3">
        <div className="text-[10px] text-slate-400">
          {subscription.cancel_at_period_end
            ? subscription.current_period_end
              ? `Cancels on ${new Date(subscription.current_period_end).toLocaleDateString()}.`
              : "Cancellation pending."
            : "Manage payment methods, plan, and invoice downloads in the Stripe portal."}
        </div>
        <SubscriptionActions
          subscription={subscription}
          onChanged={onChanged}
          onError={onError}
        />
      </footer>
    </section>
  );
}

function SubscriptionActions({
  subscription,
  onChanged,
  onError,
}: {
  subscription: BillingSubscription;
  onChanged: () => void;
  onError: (msg: string | null) => void;
}) {
  const [cancelling, setCancelling] = useState(false);
  const [openingPortal, setOpeningPortal] = useState(false);
  const [reactivating, setReactivating] = useState(false);

  async function openPortal() {
    setOpeningPortal(true);
    onError(null);
    try {
      const { url } = await api.openBillingPortal(window.location.href);
      window.location.href = url;
    } catch (err) {
      onError(err instanceof Error ? err.message : "Couldn't open Stripe portal.");
    } finally {
      setOpeningPortal(false);
    }
  }

  async function reactivate() {
    setReactivating(true);
    onError(null);
    try {
      await api.reactivateSubscription();
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Couldn't reactivate.");
    } finally {
      setReactivating(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {subscription.stripe_customer_id && (
        <Button size="sm" variant="outline" disabled={openingPortal} onClick={openPortal}>
          {openingPortal ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
          )}
          Manage in Stripe
        </Button>
      )}
      {subscription.cancel_at_period_end ? (
        <Button size="sm" disabled={reactivating} onClick={reactivate}>
          {reactivating ? "Reactivating…" : "Resume subscription"}
        </Button>
      ) : (
        <Button
          size="sm"
          variant="ghost"
          className="text-error hover:bg-error/5"
          onClick={() => setCancelling(true)}
        >
          <XCircle className="mr-1.5 h-3.5 w-3.5" />
          Cancel
        </Button>
      )}
      {cancelling && (
        <CancelDialog
          subscription={subscription}
          onClose={() => setCancelling(false)}
          onCancelled={() => {
            setCancelling(false);
            onChanged();
          }}
          onError={onError}
        />
      )}
    </div>
  );
}

function CancelDialog({
  subscription,
  onClose,
  onCancelled,
  onError,
}: {
  subscription: BillingSubscription;
  onClose: () => void;
  onCancelled: () => void;
  onError: (msg: string | null) => void;
}) {
  // Three-click flow per PRD Domain 10: Cancel → pick mode → confirm.
  // No retention dialogue, no friction beyond the mode pick.
  const [mode, setMode] = useState<"period_end" | "immediate">("period_end");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function confirm() {
    setSubmitting(true);
    onError(null);
    try {
      await api.cancelSubscription({ mode, reason });
      onCancelled();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Couldn't cancel.");
    } finally {
      setSubmitting(false);
    }
  }

  const periodEnd = subscription.current_period_end
    ? new Date(subscription.current_period_end).toLocaleDateString()
    : null;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-ink/40 px-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6">
        <h3 className="text-base font-semibold text-ink">Cancel subscription</h3>
        <p className="mt-1 text-2xs text-slate-500">
          We&apos;ll stop billing you. Your data is retained per the deletion schedule.
        </p>
        <div className="mt-4 flex flex-col gap-2 text-2xs">
          <label className="flex items-start gap-2 rounded-md border border-slate-100 p-3 hover:bg-slate-50">
            <input
              type="radio"
              name="cancel-mode"
              checked={mode === "period_end"}
              onChange={() => setMode("period_end")}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium text-ink">End of current period</span>
              <span className="block text-slate-500">
                Keep using until {periodEnd ?? "the end of the cycle"}. No refund needed.
              </span>
            </span>
          </label>
          <label className="flex items-start gap-2 rounded-md border border-slate-100 p-3 hover:bg-slate-50">
            <input
              type="radio"
              name="cancel-mode"
              checked={mode === "immediate"}
              onChange={() => setMode("immediate")}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium text-ink">Cancel immediately</span>
              <span className="block text-slate-500">
                Access ends now. Prorated refund per terms.
              </span>
            </span>
          </label>
          <input
            type="text"
            placeholder="Optional — what made you leave?"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="rounded-md border border-slate-200 px-2 py-1.5 text-2xs"
          />
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={submitting}>
            Keep subscription
          </Button>
          <Button
            size="sm"
            disabled={submitting}
            onClick={confirm}
            className="bg-error hover:bg-error/90"
          >
            {submitting ? "Cancelling…" : "Cancel subscription"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function BillingInvoicesSection() {
  const [rows, setRows] = useState<import("@/lib/api").BillingInvoiceRow[] | null>(null);

  useEffect(() => {
    api.listBillingInvoices().then(setRows).catch(() => setRows([]));
  }, []);

  if (rows === null) return null;
  if (rows.length === 0) return null;

  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <header className="flex items-center gap-2 border-b border-slate-100 px-5 py-4">
        <FileText className="h-4 w-4 text-slate-400" />
        <h2 className="text-sm font-semibold text-ink">Invoices + receipts</h2>
      </header>
      <table className="w-full text-2xs">
        <thead className="bg-slate-50 text-slate-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Number</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Date</th>
            <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">Amount</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Status</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => (
            <tr key={row.id} className="hover:bg-slate-50">
              <td className="px-3 py-2 font-mono text-ink">{row.number || row.id.slice(0, 12)}</td>
              <td className="px-3 py-2 text-slate-500">
                {row.created
                  ? new Date(row.created * 1000).toLocaleDateString()
                  : "—"}
              </td>
              <td className="px-3 py-2 text-right text-slate-600">
                {row.currency} {(row.amount_paid_cents / 100).toFixed(2)}
              </td>
              <td className="px-3 py-2">
                <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-700">
                  {row.status}
                </code>
              </td>
              <td className="px-3 py-2 text-right">
                {row.invoice_pdf && (
                  <a
                    href={row.invoice_pdf}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-2xs font-medium text-ink hover:underline"
                  >
                    <Download className="h-3 w-3" />
                    PDF
                  </a>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function PlanCatalog({ plans, currentSlug }: { plans: BillingPlan[]; currentSlug: string | null }) {
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
      setError(err instanceof Error ? err.message : "Couldn't start checkout.");
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
                isCurrent ? "border-ink/30 bg-slate-50" : "border-slate-100",
              )}
            >
              <div className="flex items-baseline justify-between">
                <span className="font-display text-base font-semibold text-ink">{plan.name}</span>
                {isCurrent && (
                  <span className="rounded-sm bg-ink px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-paper">
                    Current
                  </span>
                )}
              </div>
              <div className="text-2xs text-slate-500">{plan.description}</div>
              <div className="mt-1 font-display text-2xl font-bold text-ink">
                {isPaid ? formatPrice(plan.monthly_price_cents, plan.billing_currency) : "Custom"}
                {isPaid && <span className="text-2xs font-normal text-slate-400"> / mo</span>}
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
                  <strong>{plan.included_users > 0 ? plan.included_users : "∞"}</strong> users
                </li>
                <li>
                  <strong>{plan.included_api_keys > 0 ? plan.included_api_keys : "∞"}</strong> API
                  keys
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
