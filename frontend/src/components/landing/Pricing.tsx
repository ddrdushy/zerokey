"use client";

// Section 8 — pricing.
//
// DESKTOP_PIVOT_PLAN reshapes this from a SaaS subscription grid into
// three annual desktop licenses tracking apps/licensing/services.py
// PLAN_FEATURES. One license = one LHDN TIN. Numbers below are
// placeholders until BUSINESS_MODEL.md is updated; CTAs all point at
// /download.

import Link from "next/link";
import { Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Reveal } from "./Reveal";
import { staggerDelay } from "./stagger";
import { useT } from "@/lib/i18n";

type Tier = {
  name: string;
  price: string;
  cadence: string;
  pitch: string;
  features: string[];
  highlight?: boolean;
  cta: string;
  ctaVariant?: "primary" | "outline" | "signal";
};

const TIERS: Tier[] = [
  {
    name: "Starter",
    price: "RM 599",
    cadence: "per company / year",
    pitch: "For SMEs that send invoices by hand or from spreadsheets.",
    features: [
      "Manual + CSV invoice entry",
      "Symprio intermediary signs for you",
      "LHDN MyInvois submission",
      "Monthly consolidation view",
      "30-day offline grace",
    ],
    cta: "Get Starter",
  },
  {
    name: "Professional",
    price: "RM 1,499",
    cadence: "per company / year",
    pitch: "For SMEs running SQL Account, AutoCount or Sage UBS.",
    features: [
      "Everything in Starter",
      "ERP connectors (SQL Account / AutoCount / Sage UBS)",
      "Auto-submit after validation passes",
      "Consolidated B2C bundling",
      "Bring-your-own LHDN cert (optional)",
    ],
    highlight: true,
    cta: "Get Professional",
    ctaVariant: "signal",
  },
  {
    name: "Enterprise",
    price: "From RM 3,999",
    cadence: "per company / year",
    pitch: "Multi-user, approval workflow, dedicated support.",
    features: [
      "Everything in Professional",
      "Two-step approval workflow",
      "Audit log export",
      "Priority support + SLA",
      "Volume discounts for 3+ TINs",
    ],
    cta: "Talk to sales",
    ctaVariant: "outline",
  },
];

export function Pricing() {
  const t = useT();
  return (
    <section id="pricing" className="border-b border-slate-100">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <div className="max-w-2xl">
            <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
              {t("landing.pricing.headline")}
            </h2>
            <p className="mt-4 text-lg text-slate-600">{t("landing.pricing.sub")}</p>
          </div>
        </Reveal>
        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {TIERS.map((tier, i) => (
            <Reveal key={tier.name} delay={staggerDelay(i, 0.06)}>
              <div
                className={[
                  "flex h-full flex-col gap-4 rounded-xl border p-6 transition-all duration-panel ease-zk hover:-translate-y-1 hover:shadow-lg",
                  tier.highlight
                    ? "border-ink bg-ink text-paper ring-2 ring-signal/40"
                    : "border-slate-100 bg-white",
                ].join(" ")}
              >
                <div className="flex items-center justify-between">
                  <div className="text-2xs font-medium uppercase tracking-wider opacity-70">
                    {tier.name}
                  </div>
                  {tier.highlight ? (
                    <span className="rounded-full bg-signal px-2 py-0.5 text-2xs font-semibold text-ink">
                      Most popular
                    </span>
                  ) : null}
                </div>
                <div>
                  <div className="font-display text-3xl font-bold">{tier.price}</div>
                  <div className="text-2xs opacity-70">{tier.cadence}</div>
                </div>
                <p className="text-2xs leading-relaxed opacity-80">{tier.pitch}</p>
                <ul className="flex flex-1 flex-col gap-2 text-2xs">
                  {tier.features.map((f) => (
                    <li key={f} className="flex items-start gap-2">
                      <Check
                        className={[
                          "mt-0.5 h-3.5 w-3.5 shrink-0",
                          tier.highlight ? "text-signal" : "text-success",
                        ].join(" ")}
                      />
                      <span className="opacity-90">{f}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href={tier.name === "Enterprise" ? "/contact" : "/download"}
                  className="mt-2"
                >
                  <Button
                    variant={tier.ctaVariant ?? (tier.highlight ? "signal" : "outline")}
                    size="sm"
                    className="w-full"
                  >
                    {tier.cta}
                  </Button>
                </Link>
              </div>
            </Reveal>
          ))}
        </div>
        <Reveal delay={0.16}>
          <p className="mt-8 text-xs text-slate-400">{t("landing.pricing.note")}</p>
        </Reveal>
      </div>
    </section>
  );
}
