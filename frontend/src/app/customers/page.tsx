// /customers — at launch this is mostly forward-looking. Industries served,
// the persona cards, and an honest "no testimonials yet" panel that links to
// the beta program. Replaced with case studies as they accumulate.

import { Building2, FileCog, ShoppingBag, Stethoscope, Truck, Wrench } from "lucide-react";

import { Header } from "@/components/landing/Header";
import { Footer } from "@/components/landing/Footer";
import { Personas } from "@/components/landing/Personas";
import { CustomerVoices } from "@/components/landing/CustomerVoices";
import { FinalCta } from "@/components/landing/FinalCta";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";
import { Button } from "@/components/ui/button";

const INDUSTRIES = [
  { icon: ShoppingBag, name: "Retail & wholesale", detail: "High-volume B2B invoicing across SKUs." },
  { icon: Wrench, name: "Manufacturing", detail: "Mixed Excel + supplier PDF inboxes, hourly." },
  { icon: Truck, name: "Logistics & forwarding", detail: "Cross-border invoices, multiple currencies." },
  { icon: Stethoscope, name: "Healthcare & clinics", detail: "Self-billed invoices to insurers, recurring." },
  { icon: Building2, name: "Professional services", detail: "Recurring billing, project milestones." },
  { icon: FileCog, name: "Accounting firms", detail: "Multi-entity, multi-client, audit-grade trail." },
];

const BETA_BULLETS = [
  "Quarterly office-hours with the founder",
  "Direct line to the engineering team via Slack",
  "Early access to integrations on the roadmap",
];

export default function CustomersPage() {
  return (
    <>
      <Header />
      <main>
        <PageHero />
        <Industries />
        <CustomerVoices />
        <Personas />
        <BetaCallout />
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
            Customers
          </span>
        </Reveal>
        <Reveal delay={0.06}>
          <h1 className="mt-3 max-w-3xl font-display text-4xl font-bold leading-[1.1] tracking-tight md:text-5xl">
            The kinds of businesses we are built for.
          </h1>
        </Reveal>
        <Reveal delay={0.12}>
          <p className="mt-6 max-w-2xl text-lg text-slate-600">
            Malaysian SMEs from RM 1M turnover up through enterprise BFSI teams. The shape of the
            invoice flow looks different in each one — the LHDN regulator does not.
          </p>
        </Reveal>
      </div>
    </section>
  );
}

function Industries() {
  return (
    <section className="border-b border-slate-100 bg-slate-50">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
            Industries we already understand.
          </h2>
        </Reveal>
        <ul className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {INDUSTRIES.map((ind, i) => {
            const Icon = ind.icon;
            return (
              <Reveal key={ind.name} as="li" delay={staggerDelay(i)}>
                <div className="flex h-full items-start gap-4 rounded-xl border border-slate-100 bg-white p-6 transition-transform duration-panel ease-zk hover:-translate-y-1 hover:shadow-lg">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-ink/5 text-ink">
                    <Icon size={20} />
                  </span>
                  <div>
                    <h3 className="text-base font-semibold text-ink">{ind.name}</h3>
                    <p className="mt-1 text-sm text-slate-600">{ind.detail}</p>
                  </div>
                </div>
              </Reveal>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

function BetaCallout() {
  return (
    <section className="border-b border-slate-100 bg-paper">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <div className="grid gap-12 rounded-xl border border-slate-100 bg-white p-8 md:grid-cols-2 md:items-center md:p-12">
          <Reveal direction="left">
            <div>
              <span className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                Beta program
              </span>
              <h2 className="mt-3 font-display text-3xl font-bold leading-tight tracking-tight md:text-4xl">
                Be one of the customers we name here.
              </h2>
              <p className="mt-4 max-w-md text-base text-slate-600">
                We are accepting a small Phase 4 cohort. You get pricing that reflects the
                trade-off; we get the feedback that shapes the product before scale arrives.
              </p>
              <div className="mt-6">
                <Button variant="primary" size="lg">
                  Apply to the beta
                </Button>
              </div>
            </div>
          </Reveal>
          <Reveal direction="right" delay={0.1}>
            <ul className="space-y-3">
              {BETA_BULLETS.map((b) => (
                <li key={b} className="flex items-start gap-3 text-base text-slate-600">
                  <span className="mt-2 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-signal" />
                  <span>{b}</span>
                </li>
              ))}
            </ul>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
