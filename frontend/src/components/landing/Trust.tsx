// Section 7 — trust and security. Four pillars; calm, specific, no marketing
// brochure tone. Cards lift on hover (subtle), fade in on scroll.

import { Reveal } from "./Reveal";
import { staggerDelay } from "./stagger";

const PILLARS = [
  {
    title: "Your signing keys are not our keys.",
    body: "Your LHDN certificate is sealed in hardware-grade storage we cannot read. We sign on your behalf — we never carry the key around.",
  },
  {
    title: "Every action is auditable.",
    body: "Every invoice action, every login, every settings change is captured in a tamper-evident log. Export it any time for your auditor.",
  },
  {
    title: "Malaysia-hosted, Malaysia-resident.",
    body: "Your data lives in a Malaysian datacentre. Disaster recovery in Singapore. Nothing leaves the region without your consent.",
  },
  {
    title: "Honest about certifications.",
    body: "PDPA-compliant from launch. ISO 27001 in progress (target Q2 2027). SOC 2 Type II to follow. We don't claim badges we haven't earned.",
  },
];

export function Trust() {
  return (
    <section className="border-b border-slate-100 bg-ink text-paper">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <div className="max-w-2xl">
            <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
              Built to BFSI standards. <em className="text-signal">Sold for SMEs.</em>
            </h2>
          </div>
        </Reveal>
        <div className="mt-12 grid gap-8 md:grid-cols-2">
          {PILLARS.map((pillar, i) => (
            <Reveal key={pillar.title} delay={staggerDelay(i)}>
              <div className="group rounded-xl border border-slate-800 p-8 transition-colors duration-panel ease-zk hover:border-signal/40">
                <h3 className="text-xl font-semibold text-paper transition-colors duration-panel ease-zk group-hover:text-signal">
                  {pillar.title}
                </h3>
                <p className="mt-3 text-base text-slate-400">{pillar.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
