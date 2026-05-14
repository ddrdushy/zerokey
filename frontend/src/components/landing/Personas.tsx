"use client";

// Section 10 — Personas. Four cards covering the four audiences from
// USER_PERSONAS.md. SME owner leads (largest segment + most time-sensitive),
// then finance/ops, then tech, then BFSI/enterprise on the right.

import { Reveal } from "./Reveal";
import { staggerDelay } from "./stagger";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

type Persona = {
  badge: string;
  headline: string;
  description: string;
  bullets: string[];
  cta: { label: string; variant: "primary" | "outline" | "signal" };
};

const PERSONAS: Persona[] = [
  {
    badge: "SME owner",
    headline: "For owners who just want this handled.",
    description:
      "You run the business. Your accountant manages the books. You need this to stop being your problem.",
    bullets: [
      "Forward an email or WhatsApp — done",
      "Pricing that fits your invoice volume",
      "Support in your language",
    ],
    cta: { label: "Start free trial", variant: "primary" },
  },
  {
    badge: "Finance & ops",
    headline: "For finance and operations leading the rollout.",
    description:
      "You own compliance. Your team handles dozens of invoices weekly. The tool has to land without disruption.",
    bullets: [
      "Connects to SQL Account / AutoCount / Sage UBS",
      "Audit-grade record keeping, exportable",
      "Role-based permissions, multi-user",
    ],
    cta: { label: "Start free trial", variant: "primary" },
  },
  {
    badge: "Technical team",
    headline: "For engineers integrating ZeroKey into a wider workflow.",
    description:
      "You care about API quality, sandboxes, webhooks, and what happens when LHDN is down.",
    bullets: [
      "REST API with OpenAPI spec",
      "Sandbox environment for development",
      "Webhooks for async integration",
    ],
    cta: { label: "View API docs", variant: "outline" },
  },
  {
    badge: "Enterprise / BFSI",
    headline: "For compliance teams in large enterprises.",
    description:
      "You need enterprise security posture, retention controls, and a dedicated technical contact.",
    bullets: [
      "SSO + audit log integration",
      "Custom retention and data residency",
      "Dedicated solution architect",
    ],
    cta: { label: "Talk to sales", variant: "outline" },
  },
];

export function Personas() {
  const t = useT();
  return (
    <section className="border-b border-slate-100 bg-slate-50">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <div className="max-w-2xl">
            <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
              {t("landing.personas.headline_a")}
              <em>{t("landing.personas.headline_em")}</em>
            </h2>
            <p className="mt-4 text-lg text-slate-600">{t("landing.personas.sub")}</p>
          </div>
        </Reveal>

        <ul className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {PERSONAS.map((p, i) => (
            <Reveal key={p.badge} as="li" delay={staggerDelay(i)}>
              <div className="flex h-full flex-col gap-4 rounded-xl border border-slate-100 bg-white p-6 transition-transform duration-panel ease-zk hover:-translate-y-1 hover:shadow-lg">
                <span className="self-start rounded-full bg-ink/5 px-2.5 py-0.5 text-2xs font-semibold uppercase tracking-wider text-ink">
                  {p.badge}
                </span>
                <h3 className="font-display text-lg font-bold leading-snug tracking-tight text-ink">
                  {p.headline}
                </h3>
                <p className="text-sm text-slate-600">{p.description}</p>
                <ul className="space-y-2 text-sm text-slate-600">
                  {p.bullets.map((b) => (
                    <li key={b} className="flex items-start gap-2">
                      <span className="mt-1.5 inline-block h-1 w-1 shrink-0 rounded-full bg-signal" />
                      <span>{b}</span>
                    </li>
                  ))}
                </ul>
                <Button variant={p.cta.variant} size="sm" className="mt-auto self-start">
                  {p.cta.label}
                </Button>
              </div>
            </Reveal>
          ))}
        </ul>
      </div>
    </section>
  );
}
