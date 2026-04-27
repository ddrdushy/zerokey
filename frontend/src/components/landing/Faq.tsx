// Section 11 — FAQ. Native <details>/<summary> for the accordion (no JS needed,
// keyboard-accessible, screen-reader-friendly out of the box).

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
    a: "Yes. Primary hosting is in AWS ap-southeast-5 (Malaysia). Disaster recovery replicas are in ap-southeast-1 (Singapore). No customer data leaves the region without explicit consent.",
  },
  {
    q: "How does pricing work if I have an unusually high invoice month?",
    a: "Overages bill per invoice at the rate for your tier. There is no plan auto-upgrade. You can move tiers any time.",
  },
];

export function Faq() {
  return (
    <section className="border-b border-slate-100">
      <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
        <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
          Frequently asked questions
        </h2>
        <div className="mt-8 divide-y divide-slate-100 border-y border-slate-100">
          {FAQS.map((faq) => (
            <details key={faq.q} className="group py-5">
              <summary className="flex cursor-pointer list-none items-center justify-between text-left text-base font-medium text-ink">
                {faq.q}
                <span
                  aria-hidden="true"
                  className="ml-4 text-2xl text-slate-400 transition-transform duration-ack ease-zk group-open:rotate-45"
                >
                  +
                </span>
              </summary>
              <p className="mt-3 text-base text-slate-600">{faq.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
