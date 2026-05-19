"use client";

// Section 11 — FAQ. Native <details>/<summary> for the accordion (no JS
// needed, keyboard-accessible, screen-reader-friendly out of the box).
// Whole section fades in on scroll; each row fades with a tiny stagger.

import { Reveal } from "./Reveal";
import { staggerDelay } from "./stagger";
import { useT } from "@/lib/i18n";

const FAQS: { q: string; a: string }[] = [
  {
    q: "Where does my invoice data live?",
    a: "On your own computer. ZeroKey installs as a desktop application and stores everything in an encrypted local database. The only thing the cloud sees is your license check — never your invoice contents.",
  },
  {
    q: "Do I need to have my own LHDN certificate?",
    a: "No. Symprio is a registered LHDN intermediary, so we can sign invoices on your behalf — you skip the cert paperwork entirely. If you already have your own LHDN-issued certificate (or your security policy requires it), Professional and Enterprise plans let you bring your own and sign locally.",
  },
  {
    q: "What if my internet goes down?",
    a: "The app keeps working for 30 days on a cached entitlement. After that it drops to read-only until you reconnect for a heartbeat. You won't lose any data or be locked out unexpectedly.",
  },
  {
    q: "Can I move ZeroKey to a new computer?",
    a: "Yes. Export your data, regenerate your license key from the portal, and re-activate on the new machine. There's no extra fee — one license stays with one company TIN for the year, wherever you run it.",
  },
  {
    q: "How does pricing work?",
    a: "One annual license per Malaysian company (one LHDN TIN). No subscription, no per-invoice fees. Three tiers — Starter for manual entry, Professional for ERP connectors and auto-submit, Enterprise for multi-user approval workflows.",
  },
  {
    q: "Which accounting systems do you integrate with?",
    a: "SQL Account, AutoCount and Sage UBS via CSV import on Professional and Enterprise. Live polling via an on-prem agent is on the roadmap. Tell us what you use — additional connectors are added on customer request.",
  },
  {
    q: "What happens if LHDN's MyInvois system is down?",
    a: "Your desktop queues signed submissions locally and retries until LHDN accepts them. Your audit log shows the queued state, the retry timeline, and the final acceptance UUID — nothing is lost.",
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
