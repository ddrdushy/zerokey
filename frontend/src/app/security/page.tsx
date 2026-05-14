// /security — customer-facing trust posture. Reads as commitments, not
// a security marketing brochure. Engine names, protocols and infra acronyms
// stay out — this page talks in commitments.

import { Eye, FileSearch, KeySquare, Lock, MapPin, ShieldCheck, Users } from "lucide-react";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { FinalCta } from "@/components/landing/FinalCta";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";

const PILLARS = [
  {
    icon: KeySquare,
    title: "Your signing keys stay yours",
    body: "Your LHDN certificate is sealed in hardware-grade storage we cannot read. We sign on your behalf — we never carry the key around.",
  },
  {
    icon: FileSearch,
    title: "Every action is auditable",
    body: "Every invoice action, every login, every settings change is captured in a tamper-evident log. Export it any time for your auditor.",
  },
  {
    icon: MapPin,
    title: "Malaysia-hosted, Malaysia-resident",
    body: "Your data lives in a Malaysian datacenter. Disaster recovery in Singapore. Nothing leaves the region without your consent.",
  },
  {
    icon: Lock,
    title: "Encrypted at rest and in transit",
    body: "Customer PII is encrypted at the row level. Connections use modern TLS. Backups inherit the same protection.",
  },
  {
    icon: Users,
    title: "Least-privilege by default",
    body: "Multi-user roles, fine-grained permissions, and break-glass elevation are logged and reviewed. Nobody on our team can read your data without leaving a trail.",
  },
  {
    icon: Eye,
    title: "Honest about what we have",
    body: "PDPA-compliant from launch. ISO 27001 certification in progress (target Q2 2027). SOC 2 Type II to follow. We don't claim badges we haven't earned.",
  },
];

const COMMITMENTS = [
  {
    title: "Breach disclosure",
    body: "If we detect a breach affecting your data, you hear from us within 72 hours — same window LHDN expects.",
  },
  {
    title: "Vulnerability disclosure",
    body: "contact@symprio.com is monitored. Responsible disclosure gets a thank-you and a tracked fix.",
  },
  {
    title: "Data export and deletion",
    body: "Export every byte we hold about you, any time. Delete on request — subject to Malaysian tax retention rules.",
  },
  {
    title: "Sub-processor transparency",
    body: "We publish the list of vendors that touch your data and notify you before adding new ones.",
  },
];

export default function SecurityPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Security & compliance"
        headline={
          <>
            Built to BFSI standards. <em>Sold for SMEs.</em>
          </>
        }
        description="The security posture of a regulated-finance product, written in the language of the people who actually use it."
      />

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
          <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {PILLARS.map((p, i) => {
              const Icon = p.icon;
              return (
                <Reveal key={p.title} as="li" delay={staggerDelay(i)}>
                  <div className="flex h-full flex-col gap-4 rounded-xl border border-slate-100 bg-white p-6 transition-transform duration-panel ease-zk hover:-translate-y-1 hover:shadow-lg">
                    <span className="grid h-10 w-10 place-items-center rounded-md bg-ink/5 text-ink">
                      <Icon size={20} />
                    </span>
                    <h3 className="text-base font-semibold text-ink">{p.title}</h3>
                    <p className="text-sm text-slate-600">{p.body}</p>
                  </div>
                </Reveal>
              );
            })}
          </ul>
        </div>
      </section>

      <section className="border-b border-slate-100 bg-ink text-paper">
        <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
          <Reveal>
            <div className="max-w-2xl">
              <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
                Promises we put in writing.
              </h2>
              <p className="mt-4 text-lg text-slate-400">
                Specific, time-bounded, and the same wording our contracts use.
              </p>
            </div>
          </Reveal>
          <div className="mt-12 grid gap-4 md:grid-cols-2">
            {COMMITMENTS.map((c, i) => (
              <Reveal key={c.title} delay={staggerDelay(i)}>
                <div className="rounded-xl border border-slate-800 p-8 transition-colors duration-panel ease-zk hover:border-signal/40">
                  <h3 className="text-lg font-semibold text-paper">{c.title}</h3>
                  <p className="mt-2 text-base text-slate-400">{c.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
          <Reveal>
            <div className="flex flex-col items-start gap-6 rounded-xl border border-slate-100 bg-white p-8 md:flex-row md:items-center md:justify-between md:p-12">
              <div className="flex items-start gap-4">
                <span className="grid h-12 w-12 shrink-0 place-items-center rounded-md bg-signal/30 text-ink">
                  <ShieldCheck size={22} />
                </span>
                <div>
                  <h3 className="font-display text-xl font-bold tracking-tight text-ink">
                    Want the deep dive?
                  </h3>
                  <p className="mt-2 max-w-md text-sm text-slate-600">
                    We share an in-depth security questionnaire with prospects under NDA.
                    Suitable for IT and procurement reviews.
                  </p>
                </div>
              </div>
              <a
                href="/contact"
                className="inline-flex shrink-0 items-center justify-center rounded-md bg-ink px-5 py-2.5 text-sm font-medium text-paper transition-colors duration-ack ease-zk hover:bg-slate-800"
              >
                Request the security pack
              </a>
            </div>
          </Reveal>
        </div>
      </section>

      <FinalCta />
    </MarketingPage>
  );
}
