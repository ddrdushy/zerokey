"use client";

// Section 11 — FAQ. Native <details>/<summary> for the accordion (no JS
// needed, keyboard-accessible, screen-reader-friendly out of the box).
// Whole section fades in on scroll; each row fades with a tiny stagger.

import { Reveal } from "./Reveal";
import { staggerDelay } from "./stagger";
import { useT } from "@/lib/i18n";

const FAQS: { q: string; a: string }[] = [
  {
    q: "Do I need to be registered with LHDN before signing up?",
    a: "Yes. ZeroKey signs invoices using your LHDN-issued certificate, so you need an active MyInvois registration first. We can guide you through the registration during onboarding if you have not started.",
  },
  {
    q: "Can I switch from another e-invoicing tool to ZeroKey?",
    a: "Yes. We import your customer master and recent invoice history during onboarding, and our extraction learns from your historical data to reduce review effort from day one.",
  },
  {
    q: "What happens to my data if I cancel?",
    a: "You can export your full invoice history and audit log at any time. After cancellation we retain your data for the period required by Malaysian tax law and then delete it.",
  },
  {
    q: "Is my data stored in Malaysia?",
    a: "Yes. Your data lives in a Malaysian datacentre. We replicate to Singapore for disaster recovery only — failover, not regular operation. Nothing leaves the region without your consent.",
  },
  {
    q: "How does pricing work if I have an unusually high invoice month?",
    a: "Overages bill per invoice at the rate for your tier. There is no plan auto-upgrade. You can move tiers any time.",
  },
  {
    q: "Which accounting systems do you integrate with?",
    a: "SQL Account, AutoCount and Sage UBS at launch. Additional connectors are added as customers request them; our public connector roadmap lives in the documentation.",
  },
  {
    q: "What happens if LHDN's MyInvois system is down?",
    a: "We queue signed submissions locally and retry until LHDN accepts them. Your audit log shows the queued state, the retry timeline, and the final acceptance UUID — nothing is lost.",
  },
];

export function Faq() {
  const t = useT();
  return (
    <section id="faq" className="border-b border-slate-100">
      <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
            {t("landing.faq.headline")}
          </h2>
        </Reveal>
        <div className="mt-8 divide-y divide-slate-100 border-y border-slate-100">
          {FAQS.map((faq, i) => (
            <Reveal key={faq.q} delay={staggerDelay(i, 0.04)}>
              <details className="group py-5">
                <summary className="flex cursor-pointer list-none items-center justify-between text-left text-base font-medium text-ink transition-colors duration-ack ease-zk hover:text-slate-600">
                  <span>{faq.q}</span>
                  <span
                    aria-hidden="true"
                    className="ml-4 text-2xl text-slate-400 transition-transform duration-panel ease-zk group-open:rotate-45"
                  >
                    +
                  </span>
                </summary>
                <p className="mt-3 text-base text-slate-600">{faq.a}</p>
              </details>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
