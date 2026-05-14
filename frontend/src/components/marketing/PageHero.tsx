// Standard hero block used at the top of every marketing route. Keeps the
// visual rhythm consistent across /product, /pricing, /integrations, /about,
// the legal pages, etc. so the marketing site reads as one site, not a
// collection of one-off page templates.

import type { ReactNode } from "react";

import { Reveal } from "@/components/landing/Reveal";

type PageHeroProps = {
  eyebrow: string;
  headline: ReactNode;
  description?: ReactNode;
};

export function PageHero({ eyebrow, headline, description }: PageHeroProps) {
  return (
    <section className="border-b border-slate-100">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <span className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
            {eyebrow}
          </span>
        </Reveal>
        <Reveal delay={0.06}>
          <h1 className="mt-3 max-w-3xl font-display text-4xl font-bold leading-[1.1] tracking-tight md:text-5xl">
            {headline}
          </h1>
        </Reveal>
        {description ? (
          <Reveal delay={0.12}>
            <p className="mt-6 max-w-2xl text-lg text-slate-600">{description}</p>
          </Reveal>
        ) : null}
      </div>
    </section>
  );
}
