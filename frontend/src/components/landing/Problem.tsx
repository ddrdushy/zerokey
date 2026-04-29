// Section 3 — the problem. Specific, factual, brief.

export function Problem() {
  return (
    <section className="border-b border-slate-100 bg-slate-50">
      <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
        <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
          From January 2027, every non-compliant invoice has a price tag.
        </h2>
        <div className="mt-8 space-y-6 text-lg text-slate-600">
          <p>
            LHDN begins enforcing penalties on Phase 4 taxpayers (RM 1M–5M annual turnover) for
            invoices that fail MyInvois requirements. Penalties run from RM 200 to RM 20,000 per
            invoice.
          </p>
          <p>
            Most accounting systems were not built for MyInvois. The technical specification is
            detailed, the field requirements exacting, the validation rules subtle, and the
            cancellation window only 72 hours. Doing this manually is feasible for one or two
            invoices a month — not for fifty or two hundred.
          </p>
          <p>
            You are choosing between three paths: build it yourself, wait for your accounting vendor
            to catch up, or use a tool built specifically for MyInvois.
          </p>
        </div>
      </div>
    </section>
  );
}
