// /api — developer-facing entry point for the ZeroKey API. We keep the
// marketing-page copy outcome-focused; the actual reference docs live in a
// separate sub-app once the API surface stabilises.

import { ArrowUpRight, Bell, FlaskConical, KeyRound, Plug2 } from "lucide-react";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";

const CAPABILITIES = [
  {
    icon: Plug2,
    title: "Submit invoices programmatically",
    body: "Push an invoice payload from your system. We extract, validate, sign and submit — you get the LHDN UUID back.",
  },
  {
    icon: Bell,
    title: "Get notified the moment something changes",
    body: "Subscribe to events: invoice validated, submission accepted, rejection raised, exception cleared. Your endpoint gets the call.",
  },
  {
    icon: FlaskConical,
    title: "A sandbox that mirrors production",
    body: "Test against the real LHDN sandbox, with synthetic data. Switch a flag to go live when you&apos;re ready.",
  },
  {
    icon: KeyRound,
    title: "Per-environment access keys",
    body: "Issue keys per integration, scope them to specific actions, rotate without downtime.",
  },
];

export default function ApiPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="API reference"
        headline={
          <>
            Build ZeroKey <em>into your own system</em>.
          </>
        }
        description="Everything the dashboard does, your software can do too. Ingest invoices, fetch validation results, listen to submission events, manage your team."
      />

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
          <ul className="grid gap-4 md:grid-cols-2">
            {CAPABILITIES.map((c, i) => {
              const Icon = c.icon;
              return (
                <Reveal key={c.title} as="li" delay={staggerDelay(i)}>
                  <div className="flex h-full flex-col gap-3 rounded-xl border border-slate-100 bg-white p-8">
                    <span className="grid h-10 w-10 place-items-center rounded-md bg-ink/5 text-ink">
                      <Icon size={20} />
                    </span>
                    <h3 className="text-lg font-semibold text-ink">{c.title}</h3>
                    <p className="text-base text-slate-600">{c.body}</p>
                  </div>
                </Reveal>
              );
            })}
          </ul>
        </div>
      </section>

      <section className="border-b border-slate-100 bg-ink text-paper">
        <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
          <div className="grid gap-12 md:grid-cols-2 md:items-center">
            <Reveal direction="left">
              <div>
                <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
                  Reference docs <em className="text-signal">live in the dashboard</em>.
                </h2>
                <p className="mt-4 max-w-md text-lg text-slate-400">
                  Once you have an account, you&apos;ll find the full endpoint reference,
                  request/response shapes, error catalog, and live "try it" panel inside the
                  Developer area.
                </p>
                <a
                  href="/sign-up?intent=developer"
                  className="mt-6 inline-flex items-center gap-2 rounded-md bg-signal px-5 py-2.5 text-sm font-semibold text-ink transition-opacity duration-ack ease-zk hover:opacity-90"
                >
                  Start free trial
                  <ArrowUpRight size={16} />
                </a>
              </div>
            </Reveal>
            <Reveal direction="right" delay={0.1}>
              <div className="rounded-xl border border-slate-800 bg-slate-800/50 p-6 font-mono text-2xs text-paper">
                <div className="text-slate-400"># Submit an invoice</div>
                <div className="mt-2">
                  <span className="text-signal">POST</span> /v1/invoices
                </div>
                <div className="mt-3 text-slate-400">{`{`}</div>
                <div className="ml-4">&quot;reference&quot;: &quot;INV-2026-0418&quot;,</div>
                <div className="ml-4">&quot;buyer_tin&quot;: &quot;C12345&quot;,</div>
                <div className="ml-4">&quot;total&quot;: 6696.00,</div>
                <div className="ml-4">&quot;items&quot;: [ … ]</div>
                <div className="text-slate-400">{`}`}</div>
                <div className="mt-4 text-slate-400"># Response</div>
                <div className="mt-1 text-slate-400">{`{`}</div>
                <div className="ml-4">&quot;uuid&quot;: &quot;a3f9…7d21&quot;,</div>
                <div className="ml-4">&quot;status&quot;: &quot;<span className="text-signal">validated</span>&quot;</div>
                <div className="text-slate-400">{`}`}</div>
              </div>
            </Reveal>
          </div>
        </div>
      </section>
    </MarketingPage>
  );
}
