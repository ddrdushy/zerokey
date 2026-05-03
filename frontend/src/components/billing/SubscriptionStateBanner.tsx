"use client";

// Slice 100 — global banner for past_due / suspended / cancelled
// organizations. Renders nothing for trialing + active.
//
// Per PRD Domain 10: "the account remains accessible in read-only
// mode for fourteen additional days, after which it is suspended
// and after another thirty days its data is purged" — this banner
// is what makes that state machine visible to the user.

import Link from "next/link";
import { AlertTriangle, ShieldAlert } from "lucide-react";

import type { Me } from "@/lib/api";

export function SubscriptionStateBanner({ me }: { me: Me | null }) {
  if (!me) return null;
  const active = me.memberships.find((m) => m.organization.id === me.active_organization_id);
  const state = active?.organization.subscription_state ?? "active";

  if (state === "active" || state === "trialing") return null;

  // Past-due (post-trial grace) / suspended / cancelled all share
  // copy + treatment but the headline + CTA differ.
  const tone = state === "suspended" ? "error" : "warning";
  const Icon = state === "suspended" ? ShieldAlert : AlertTriangle;
  const headline =
    state === "past_due"
      ? "Trial ended — read-only mode."
      : state === "suspended"
        ? "Account suspended."
        : "Subscription cancelled.";
  const subtext =
    state === "past_due"
      ? "Pick a plan to keep submitting. We'll suspend access in 14 days if no plan is selected."
      : state === "suspended"
        ? "Pick a plan to restore access. Your data is retained for 30 days before purge."
        : "Your subscription is cancelled. Pick a plan to start again at any time.";

  return (
    <div
      className={
        tone === "error"
          ? "border-b border-error/30 bg-error/5 px-4 py-2 text-2xs"
          : "border-b border-warning/30 bg-warning/5 px-4 py-2 text-2xs"
      }
      role="alert"
    >
      <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center gap-3">
        <Icon
          className={tone === "error" ? "h-4 w-4 text-error" : "h-4 w-4 text-warning"}
        />
        <span className="font-medium text-ink">{headline}</span>
        <span className="text-slate-600">{subtext}</span>
        <Link
          href="/dashboard/settings/billing"
          className="ml-auto rounded-md bg-ink px-3 py-1 text-[10px] font-medium uppercase tracking-wider text-paper hover:opacity-90"
        >
          Pick a plan
        </Link>
      </div>
    </div>
  );
}
