// Section 7 — trust and security. Four pillars; calm, specific, no marketing
// brochure tone.

const PILLARS = [
  {
    title: "Your signing keys are not our keys.",
    body: "Customer signing certificates live in hardware-backed key management infrastructure. We are custodians, not owners. Even our highest-privileged staff cannot extract a customer's private key.",
  },
  {
    title: "Every action is auditable.",
    body: "An immutable, hash-chained audit log captures every invoice action, every authentication event, every settings change. Customers can export and verify integrity independently.",
  },
  {
    title: "Malaysia-hosted, Malaysia-residency.",
    body: "Customer data lives in AWS ap-southeast-5 (Malaysia). Disaster recovery to ap-southeast-1 (Singapore). No customer data leaves the region without explicit consent.",
  },
  {
    title: "Honest about certifications.",
    body: "PDPA-compliant from launch. ISO 27001 in progress (target Q2 2027). SOC 2 Type II to follow. We do not claim what we have not earned.",
  },
];

export function Trust() {
  return (
    <section className="border-b border-slate-100 bg-ink text-paper">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <div className="max-w-2xl">
          <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
            Built to BFSI standards. <em className="text-signal">Sold for SMEs.</em>
          </h2>
        </div>
        <div className="mt-12 grid gap-8 md:grid-cols-2">
          {PILLARS.map((pillar) => (
            <div key={pillar.title} className="rounded-xl border border-slate-800 p-8">
              <h3 className="text-xl font-semibold text-paper">{pillar.title}</h3>
              <p className="mt-3 text-base text-slate-400">{pillar.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
