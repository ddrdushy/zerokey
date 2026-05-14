// Section 9 — Customer voices. At launch we ship Option B from
// LANDING_PAGE.md: a short founder note explaining why ZeroKey exists.
// Real customer quotes slot in here as beta customers agree to be named.

import { Reveal } from "./Reveal";

export function CustomerVoices() {
  return (
    <section className="border-b border-slate-100 bg-paper">
      <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <span className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
            From our team
          </span>
        </Reveal>
        <Reveal delay={0.08}>
          <blockquote className="mt-6">
            <p className="font-display text-2xl font-medium leading-snug tracking-tight text-ink md:text-3xl">
              &ldquo;I watched too many friends running real businesses spend their evenings
              fighting MyInvois forms instead of running their business. ZeroKey is the tool I
              wanted them to have when the deadline arrived. <em>Calm software for an anxious
              regulator.</em>&rdquo;
            </p>
          </blockquote>
        </Reveal>
        <Reveal delay={0.16}>
          <figcaption className="mt-6 flex items-center gap-4">
            <div
              aria-hidden="true"
              className="grid h-12 w-12 place-items-center rounded-full bg-ink font-display text-lg font-bold text-paper"
            >
              D
            </div>
            <div>
              <div className="text-sm font-semibold text-ink">Dushy</div>
              <div className="text-2xs text-slate-400">Founder · Symprio Sdn Bhd</div>
            </div>
          </figcaption>
        </Reveal>
        <Reveal delay={0.24}>
          <p className="mt-12 border-t border-slate-100 pt-6 text-xs text-slate-400">
            Customer testimonials will appear here as our beta cohort agrees to be named.
            We&apos;d rather show you a real face than rent one.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
