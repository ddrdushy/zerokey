// Section 8 — pricing. Comparative grid scannable in 10 seconds. Numbers here
// are placeholders; canonical values live in BUSINESS_MODEL.md and are wired
// from the backend Plan catalog once Phase 5 lands. Cards stagger-fade-in;
// highlight tier lifts on hover.

import { Button } from "@/components/ui/button";
import { Reveal } from "./Reveal";
import { staggerDelay } from "./stagger";

type Tier = {
  name: string;
  price: string;
  invoices: string;
  seats: string;
  highlight?: boolean;
  cta: string;
  ctaVariant?: "primary" | "outline" | "signal";
};

const TIERS: Tier[] = [
  { name: "Free Trial", price: "RM 0", invoices: "20 / 14 days", seats: "1", cta: "Start free" },
  { name: "Starter", price: "RM 99", invoices: "50 / mo", seats: "2", cta: "Choose Starter" },
  {
    name: "Growth",
    price: "RM 299",
    invoices: "250 / mo",
    seats: "5",
    highlight: true,
    cta: "Choose Growth",
    ctaVariant: "signal",
  },
  { name: "Scale", price: "RM 699", invoices: "1,000 / mo", seats: "15", cta: "Choose Scale" },
  { name: "Pro", price: "RM 1,499", invoices: "5,000 / mo", seats: "50", cta: "Choose Pro" },
  {
    name: "Custom",
    price: "From RM 5,000",
    invoices: "Negotiated",
    seats: "Unlimited",
    cta: "Talk to sales",
    ctaVariant: "outline",
  },
];

export function Pricing() {
  return (
    <section id="pricing" className="border-b border-slate-100">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <div className="max-w-2xl">
            <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
              Pricing that fits the invoices you actually send.
            </h2>
            <p className="mt-4 text-lg text-slate-600">
              All plans include LHDN MyInvois submission. Free trial requires no credit card.
              Switch plans any time.
            </p>
          </div>
        </Reveal>
        <div className="mt-12 grid gap-4 md:grid-cols-3 lg:grid-cols-6">
          {TIERS.map((tier, i) => (
            <Reveal key={tier.name} delay={staggerDelay(i, 0.05)}>
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
                      Popular
                    </span>
                  ) : null}
                </div>
                <div className="font-display text-2xl font-bold">{tier.price}</div>
                <dl className="space-y-2 text-2xs opacity-80">
                  <div>
                    <dt className="opacity-70">Invoices</dt>
                    <dd>{tier.invoices}</dd>
                  </div>
                  <div>
                    <dt className="opacity-70">Seats</dt>
                    <dd>{tier.seats}</dd>
                  </div>
                </dl>
                <Button
                  variant={tier.ctaVariant ?? (tier.highlight ? "signal" : "outline")}
                  size="sm"
                  className="mt-auto"
                >
                  {tier.cta}
                </Button>
              </div>
            </Reveal>
          ))}
        </div>
        <Reveal delay={0.16}>
          <p className="mt-8 text-xs text-slate-400">
            All prices in MYR. 30-day money-back guarantee. Annual billing saves 15%.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
