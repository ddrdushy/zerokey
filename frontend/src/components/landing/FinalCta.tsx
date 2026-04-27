// Section 12 — final CTA. Tighter restatement of the value prop on a strong
// dark surface. Reminder line removes last-minute friction.

import { Button } from "@/components/ui/button";

export function FinalCta() {
  return (
    <section className="bg-ink text-paper">
      <div className="mx-auto flex max-w-7xl flex-col items-start gap-6 px-4 py-16 md:flex-row md:items-end md:justify-between md:px-8 md:py-24">
        <div className="max-w-xl">
          <h2 className="font-display text-3xl font-bold leading-tight tracking-tight md:text-4xl">
            Stop dreading e-invoicing season.
          </h2>
          <p className="mt-3 text-lg text-slate-400">
            Drop a PDF. We sign, submit, and track. Your team keeps their day job.
          </p>
        </div>
        <div className="flex flex-col items-start gap-3 md:items-end">
          <div className="flex gap-3">
            <Button variant="signal" size="lg">
              Start free trial
            </Button>
            <Button variant="outline" size="lg" className="border-slate-800 text-paper">
              Book a demo
            </Button>
          </div>
          <p className="text-2xs uppercase tracking-wider text-slate-400">
            Free 14-day trial. No credit card. Cancel anytime.
          </p>
        </div>
      </div>
    </section>
  );
}
