// /careers — honest about the size of the team at launch. The page works
// as a "we're not actively hiring but we want to hear from people who care"
// channel rather than a sea of req tiles.

import { Hammer, HeartHandshake, MessageSquare, Sparkles } from "lucide-react";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";

const PRINCIPLES = [
  {
    icon: Hammer,
    title: "Small team, clear seams",
    body: "We work in small, owned slices. Every contributor sees their work in production within days.",
  },
  {
    icon: Sparkles,
    title: "Quality over surface area",
    body: "We&apos;d rather ship one calm, dependable thing than ten loud, leaky things.",
  },
  {
    icon: HeartHandshake,
    title: "Remote-first, Malaysia-rooted",
    body: "Async by default. Same-day-feeling support for Malaysian customers is non-negotiable.",
  },
];

const OPEN_ROLES = [
  {
    title: "Future open roles will appear here",
    detail:
      "We&apos;re building the team carefully. If you see yourself helping Malaysian SMEs through the LHDN transition, we&apos;d love to know who you are — even before a formal posting exists.",
  },
];

export default function CareersPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Careers"
        headline={
          <>
            Help us build calm software <em>for an anxious regulator</em>.
          </>
        }
        description="Symprio is a small, deliberate team. We hire slowly, value craft over churn, and care about the customer outcome more than the line of code."
      />

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
          <Reveal>
            <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
              How we work.
            </h2>
          </Reveal>
          <ul className="mt-12 grid gap-4 md:grid-cols-3">
            {PRINCIPLES.map((p, i) => {
              const Icon = p.icon;
              return (
                <Reveal key={p.title} as="li" delay={staggerDelay(i)}>
                  <div className="flex h-full flex-col gap-4 rounded-xl border border-slate-100 bg-white p-6">
                    <span className="grid h-10 w-10 place-items-center rounded-md bg-ink/5 text-ink">
                      <Icon size={20} />
                    </span>
                    <h3 className="text-base font-semibold text-ink">{p.title}</h3>
                    <p className="text-sm text-slate-600">{p.body}</p>
                  </div>
                </Reveal>
              );
            })}
          </ul>
        </div>
      </section>

      <section className="border-b border-slate-100 bg-slate-50">
        <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
          <Reveal>
            <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
              Open roles.
            </h2>
          </Reveal>

          <div className="mt-10 space-y-4">
            {OPEN_ROLES.map((r) => (
              <Reveal key={r.title}>
                <div className="rounded-xl border border-slate-100 bg-white p-8">
                  <h3 className="text-lg font-semibold text-ink">{r.title}</h3>
                  <p className="mt-3 text-base text-slate-600">{r.detail}</p>
                </div>
              </Reveal>
            ))}
          </div>

          <Reveal delay={0.16}>
            <div className="mt-10 rounded-xl border border-slate-100 bg-ink p-8 text-paper md:p-10">
              <div className="flex items-start gap-4">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-signal/30">
                  <MessageSquare size={20} className="text-paper" />
                </span>
                <div>
                  <h3 className="font-display text-lg font-bold tracking-tight">
                    Send us a hello anyway.
                  </h3>
                  <p className="mt-2 text-sm text-slate-400">
                    A short note about you, what you care about, and what you&apos;d want to work
                    on goes a long way.
                  </p>
                  <a
                    href="mailto:hello@symprio.com?subject=Joining%20Symprio"
                    className="mt-4 inline-flex items-center justify-center rounded-md bg-signal px-5 py-2.5 text-sm font-semibold text-ink transition-opacity duration-ack ease-zk hover:opacity-90"
                  >
                    hello@symprio.com
                  </a>
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>
    </MarketingPage>
  );
}
