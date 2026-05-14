// /about — the story, the why, and the parent company. Honest about being
// founder-driven and pre-customer-testimonial.

import { Building2, Compass, Heart } from "lucide-react";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { CustomerVoices } from "@/components/landing/CustomerVoices";
import { FinalCta } from "@/components/landing/FinalCta";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";

const VALUES = [
  {
    icon: Compass,
    title: "Calm software for an anxious regulator",
    body: "MyInvois is a nervous topic for our customers. Our job is to make the software feel like the most relaxed part of their day.",
  },
  {
    icon: Heart,
    title: "Respect the small business",
    body: "Small businesses are not 'smaller enterprises'. They have their own shape. We build for that shape, not for a slimmed-down enterprise pitch.",
  },
  {
    icon: Building2,
    title: "Malaysian by intention",
    body: "Four launch languages. Real Malaysian datacentre. Real Malaysian support. The product is Malaysian because Malaysia deserves the best version of it.",
  },
];

export default function AboutPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="About"
        headline={
          <>
            We build the boring infrastructure <em>so the country can keep moving</em>.
          </>
        }
        description="ZeroKey is a product of Symprio Sdn Bhd, a Malaysian software company building tools that quietly solve big regulatory problems for small teams."
      />

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
          <Reveal>
            <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
              Why ZeroKey exists.
            </h2>
          </Reveal>
          <div className="mt-8 space-y-6 text-lg text-slate-600">
            <Reveal delay={0.06}>
              <p>
                LHDN&apos;s MyInvois rollout is one of the largest regulatory shifts Malaysian
                businesses have faced in a decade. The fine-print is detailed. The deadlines are
                fixed. The penalties are steep. The accounting industry was not prepared.
              </p>
            </Reveal>
            <Reveal delay={0.12}>
              <p>
                We watched friends running real businesses spend evenings fighting forms instead of
                running their business. We watched accountants juggle dozens of invoices a day on
                tools that were not built for it. We saw the gap between what LHDN expected and
                what most software could deliver.
              </p>
            </Reveal>
            <Reveal delay={0.18}>
              <p>
                ZeroKey is the tool we wanted those friends to have when the deadline arrived. It
                is not a checkbox. It is not an add-on. It is a careful, calm, regulator-grade
                tool for a regulator-grade problem.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      <section className="border-b border-slate-100 bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
          <Reveal>
            <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
              What we hold ourselves to.
            </h2>
          </Reveal>
          <ul className="mt-12 grid gap-4 md:grid-cols-3">
            {VALUES.map((v, i) => {
              const Icon = v.icon;
              return (
                <Reveal key={v.title} as="li" delay={staggerDelay(i)}>
                  <div className="flex h-full flex-col gap-4 rounded-xl border border-slate-100 bg-white p-6">
                    <span className="grid h-10 w-10 place-items-center rounded-md bg-ink/5 text-ink">
                      <Icon size={20} />
                    </span>
                    <h3 className="text-base font-semibold text-ink">{v.title}</h3>
                    <p className="text-sm text-slate-600">{v.body}</p>
                  </div>
                </Reveal>
              );
            })}
          </ul>
        </div>
      </section>

      <CustomerVoices />

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
          <Reveal>
            <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
              The Symprio relationship.
            </h2>
          </Reveal>
          <div className="mt-8 space-y-6 text-lg text-slate-600">
            <Reveal delay={0.06}>
              <p>
                ZeroKey is a product of <strong className="text-ink">Symprio Sdn Bhd</strong>, a
                Malaysian software company. Symprio has shipped enterprise software for
                regulated industries for years; ZeroKey is its first dedicated SME product.
              </p>
            </Reveal>
            <Reveal delay={0.12}>
              <p>
                Operationally that means ZeroKey gets the same engineering, security and support
                discipline Symprio applies to its enterprise work — at SME prices and SME speed.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      <FinalCta />
    </MarketingPage>
  );
}
