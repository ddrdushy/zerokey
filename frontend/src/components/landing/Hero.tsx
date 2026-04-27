// Section 2 — hero. Headline (8–12 words, customer outcome), tagline with the
// italics device, subhead naming pain + audience + timing + scope, dual CTAs,
// trust strip. Hero visual placeholder on the right; replaced with a real
// product screenshot later.

import { Button } from "@/components/ui/button";

const TRUST_LABELS = [
  "A product of Symprio Sdn Bhd",
  "MDEC accredited",
  "LHDN registered software intermediary",
];

export function Hero() {
  return (
    <section className="border-b border-slate-100">
      <div className="mx-auto grid max-w-7xl gap-12 px-4 py-16 md:grid-cols-2 md:px-8 md:py-24">
        <div className="flex flex-col items-start gap-6">
          <h1 className="font-display text-4xl font-bold leading-[1.1] tracking-tight md:text-5xl lg:text-6xl">
            LHDN e-invoicing without the headaches.
          </h1>
          <p className="font-display text-lg text-slate-600">
            Drop the PDF. <em className="not-italic text-ink">Drop the Keys.</em>
          </p>
          <p className="max-w-xl text-lg text-slate-600">
            Malaysian SMEs face penalties up to RM 20,000 per non-compliant invoice from January
            2027. ZeroKey handles every invoice from upload to LHDN — accurate, audited, and fast.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" size="lg">
              Start free trial
            </Button>
            <Button variant="outline" size="lg">
              Book a demo
            </Button>
          </div>
          <ul className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-2xs uppercase tracking-wider text-slate-400">
            {TRUST_LABELS.map((label) => (
              <li key={label}>{label}</li>
            ))}
          </ul>
        </div>
        <div className="flex items-center justify-center">
          <div
            aria-hidden="true"
            className="flex aspect-[4/5] w-full max-w-md items-center justify-center rounded-xl border border-slate-100 bg-white p-8 shadow-sm"
          >
            <div className="flex w-full flex-col gap-3 text-2xs">
              <div className="flex items-center justify-between">
                <span className="font-mono text-slate-400">INV-2026-0418</span>
                <span className="rounded-full bg-signal px-2 py-0.5 font-medium text-ink">
                  Validated
                </span>
              </div>
              <div className="h-2 w-3/4 rounded bg-slate-100" />
              <div className="h-2 w-1/2 rounded bg-slate-100" />
              <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="rounded-md border border-slate-100 p-3">
                  <div className="text-2xs uppercase tracking-wider text-slate-400">UUID</div>
                  <div className="mt-1 truncate font-mono text-2xs">a3f9…7d21</div>
                </div>
                <div className="flex items-center justify-center rounded-md border border-slate-100 p-3">
                  <div className="grid h-12 w-12 grid-cols-4 grid-rows-4 gap-px bg-slate-100">
                    {Array.from({ length: 16 }).map((_, i) => (
                      <div key={i} className={i % 3 === 0 ? "bg-ink" : "bg-paper"} />
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
