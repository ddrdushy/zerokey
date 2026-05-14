"use client";

// Section 12 — final CTA. Tighter restatement of the value prop on a strong
// dark surface. Reminder line removes last-minute friction.

import { Button } from "@/components/ui/button";
import { Reveal } from "./Reveal";
import { staggerDelay } from "./stagger";
import { useT } from "@/lib/i18n";

export function FinalCta() {
  const t = useT();
  return (
    <section className="relative overflow-hidden bg-ink text-paper">
      {/* Decorative signal glow — pinned bottom-right, behind content. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-32 -right-32 h-96 w-96 rounded-full bg-signal opacity-10 blur-3xl"
      />
      <div className="relative mx-auto flex max-w-7xl flex-col items-start gap-6 px-4 py-16 md:flex-row md:items-end md:justify-between md:px-8 md:py-24">
        <Reveal direction="left">
          <div className="max-w-xl">
            <h2 className="font-display text-3xl font-bold leading-tight tracking-tight md:text-4xl">
              {t("landing.cta_final.headline")}
            </h2>
            <p className="mt-3 text-lg text-slate-400">{t("landing.cta_final.sub")}</p>
          </div>
        </Reveal>
        <Reveal direction="right" delay={staggerDelay(1)}>
          <div className="flex flex-col items-start gap-3 md:items-end">
            <div className="flex gap-3">
              <Button variant="signal" size="lg">
                {t("landing.cta_final.cta_primary")}
              </Button>
              <Button variant="outline" size="lg" className="border-slate-800 text-paper">
                {t("landing.cta_final.cta_secondary")}
              </Button>
            </div>
            <p className="text-2xs uppercase tracking-wider text-slate-400">
              {t("landing.cta_final.note")}
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
