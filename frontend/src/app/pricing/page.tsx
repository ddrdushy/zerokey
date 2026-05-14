// /pricing — standalone pricing page. Reuses the home Pricing grid as the
// centerpiece and surrounds it with the supporting material that doesn't
// fit on the home page: a feature matrix, an FAQ snippet, and a money-back
// guarantee callout.

import { Header } from "@/components/landing/Header";
import { Footer } from "@/components/landing/Footer";
import { Pricing } from "@/components/landing/Pricing";
import { Faq } from "@/components/landing/Faq";
import { FinalCta } from "@/components/landing/FinalCta";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";
import { Button } from "@/components/ui/button";
import { Check, X } from "lucide-react";

type Row = {
  feature: string;
  tiers: ("✓" | "—" | string)[];
};

// Tier order matches the Pricing grid: Trial, Starter, Growth, Scale, Pro, Custom
const FEATURE_MATRIX: Row[] = [
  { feature: "LHDN MyInvois submission", tiers: ["✓", "✓", "✓", "✓", "✓", "✓"] },
  { feature: "Multi-format ingestion", tiers: ["✓", "✓", "✓", "✓", "✓", "✓"] },
  { feature: "Email & WhatsApp inbox", tiers: ["—", "✓", "✓", "✓", "✓", "✓"] },
  { feature: "SQL/AutoCount/Sage UBS connectors", tiers: ["—", "—", "✓", "✓", "✓", "✓"] },
  { feature: "API + webhooks", tiers: ["—", "—", "✓", "✓", "✓", "✓"] },
  { feature: "SSO (OIDC / SAML)", tiers: ["—", "—", "—", "✓", "✓", "✓"] },
  { feature: "Custom retention windows", tiers: ["—", "—", "—", "—", "✓", "✓"] },
  { feature: "Dedicated solution architect", tiers: ["—", "—", "—", "—", "—", "✓"] },
];

const TIER_HEADERS = ["Trial", "Starter", "Growth", "Scale", "Pro", "Custom"];

export default function PricingPage() {
  return (
    <>
      <Header />
      <main>
        <PageHero />
        <Pricing />
        <FeatureMatrix />
        <Guarantee />
        <Faq />
        <FinalCta />
      </main>
      <Footer />
    </>
  );
}

function PageHero() {
  return (
    <section className="border-b border-slate-100">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <span className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
            Pricing
          </span>
        </Reveal>
        <Reveal delay={0.06}>
          <h1 className="mt-3 max-w-3xl font-display text-4xl font-bold leading-[1.1] tracking-tight md:text-5xl">
            Fair pricing, in Ringgit. <em>No surprise invoices.</em>
          </h1>
        </Reveal>
        <Reveal delay={0.12}>
          <p className="mt-6 max-w-2xl text-lg text-slate-600">
            Pick the tier that fits the invoices you actually send. Move up, move down, cancel —
            all self-serve, all the time.
          </p>
        </Reveal>
      </div>
    </section>
  );
}

function FeatureMatrix() {
  return (
    <section className="border-b border-slate-100 bg-slate-50">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
            What you get at each tier.
          </h2>
        </Reveal>

        <Reveal delay={0.08}>
          <div className="mt-10 overflow-x-auto rounded-xl border border-slate-100 bg-white">
            <table className="w-full min-w-[720px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  <th className="px-6 py-4 text-left text-2xs font-semibold uppercase tracking-wider text-slate-400">
                    Feature
                  </th>
                  {TIER_HEADERS.map((t) => (
                    <th
                      key={t}
                      className="px-6 py-4 text-left text-2xs font-semibold uppercase tracking-wider text-slate-400"
                    >
                      {t}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {FEATURE_MATRIX.map((row) => (
                  <tr key={row.feature} className="border-b border-slate-100 last:border-0">
                    <td className="px-6 py-4 font-medium text-ink">{row.feature}</td>
                    {row.tiers.map((value, i) => (
                      <td key={i} className="px-6 py-4">
                        {value === "✓" ? (
                          <Check size={16} className="text-ink" aria-label="included" />
                        ) : value === "—" ? (
                          <X size={16} className="text-slate-200" aria-label="not included" />
                        ) : (
                          <span className="text-ink">{value}</span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function Guarantee() {
  const PROMISES = [
    { title: "14-day free trial", body: "20 invoices. No credit card. Full product." },
    {
      title: "30-day money back",
      body: "If you decide ZeroKey isn't the right fit in the first month, we refund.",
    },
    { title: "Cancel any time", body: "Self-serve from your billing settings. No retention calls." },
  ];
  return (
    <section className="border-b border-slate-100 bg-ink text-paper">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <div className="grid gap-12 md:grid-cols-2 md:items-center">
          <Reveal direction="left">
            <div>
              <h2 className="font-display text-3xl font-bold leading-tight tracking-tight md:text-4xl">
                Money back if it doesn&apos;t fit. <em className="text-signal">No drama.</em>
              </h2>
              <p className="mt-4 max-w-md text-lg text-slate-400">
                Three commitments we are happy to be held to.
              </p>
              <div className="mt-6">
                <Button variant="signal" size="lg">
                  Start free trial
                </Button>
              </div>
            </div>
          </Reveal>
          <div className="grid gap-4">
            {PROMISES.map((p, i) => (
              <Reveal key={p.title} delay={staggerDelay(i)}>
                <div className="rounded-xl border border-slate-800 p-6">
                  <h3 className="text-base font-semibold text-paper">{p.title}</h3>
                  <p className="mt-2 text-sm text-slate-400">{p.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
