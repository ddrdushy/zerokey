// Section 5 — Why ZeroKey. Comparative framing without naming competitors.
// Three alternatives + our position; closes with 4 outcome-shaped
// differentiators (per LANDING_PAGE.md §"Why ZeroKey").

import { Reveal } from "./Reveal";
import { staggerDelay } from "./stagger";

const ALTERNATIVES = [
  {
    label: "Build it yourself",
    pain: "Fast for one company — but the calendar cost is real and the tool needs maintenance every time LHDN evolves.",
    ours: "We maintain the LHDN integration so you can focus on your business.",
  },
  {
    label: "Wait for your accounting system",
    pain: "Your vendor may add e-invoicing — but the deadline is fixed and the timing is theirs, not yours.",
    ours: "We connect to SQL Account, AutoCount and Sage UBS today, so you do not have to switch or wait.",
  },
  {
    label: "Generic e-invoicing from outside Malaysia",
    pain: "These exist — but they were not built for MyInvois. MSIC codes, the 72-hour cancellation window, four languages: a Malaysia-shaped tool fits a Malaysia-shaped problem.",
    ours: "Built in Malaysia for the Malaysian regulatory framework, with English, BM, 中文 and தமிழ் first-class.",
  },
];

const DIFFERENTIATORS = [
  {
    headline: "Fastest extraction for Malaysian formats",
    detail: "Tuned on real LHDN field requirements — not a global model translated.",
  },
  {
    headline: "Every action cryptographically auditable",
    detail: "Hash-chained audit log, exportable as a tamper-evident bundle.",
  },
  {
    headline: "Your signing keys stay yours",
    detail: "Customer certificates live in KMS-encrypted blobs; we never hold the plain key.",
  },
  {
    headline: "Malaysian support that understands your accountant",
    detail: "Same time zone, same vocabulary, same regulator.",
  },
];

export function WhyZerokey() {
  return (
    <section className="border-b border-slate-100 bg-paper">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <div className="max-w-2xl">
            <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
              Three alternatives, three trade-offs. <em>Here is where we fit.</em>
            </h2>
          </div>
        </Reveal>

        <ol className="mt-12 grid gap-6 md:grid-cols-3">
          {ALTERNATIVES.map((alt, i) => (
            <Reveal key={alt.label} as="li" delay={staggerDelay(i)}>
              <div className="flex h-full flex-col rounded-xl border border-slate-100 bg-white p-8">
                <div className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                  Option {String.fromCharCode(65 + i)}
                </div>
                <h3 className="mt-2 text-xl font-semibold text-ink">{alt.label}</h3>
                <p className="mt-3 text-base text-slate-600">{alt.pain}</p>
                <div className="mt-6 flex items-start gap-3 border-t border-slate-100 pt-6">
                  <span className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full bg-signal" />
                  <p className="text-base font-medium text-ink">{alt.ours}</p>
                </div>
              </div>
            </Reveal>
          ))}
        </ol>

        <Reveal delay={0.12}>
          <div className="mt-16 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {DIFFERENTIATORS.map((d) => (
              <div key={d.headline} className="rounded-xl border border-slate-100 bg-white p-6">
                <h4 className="text-base font-semibold text-ink">{d.headline}</h4>
                <p className="mt-2 text-sm text-slate-600">{d.detail}</p>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
