// Section 6 — Built for Malaysian businesses. Short, structural. Languages,
// regional regulatory facts, accounting integrations. Tamil treated with the
// same care as the others per BRAND_KIT.md.

import { Reveal } from "./Reveal";
import { staggerDelay } from "./stagger";

const LANGUAGES = [
  { code: "EN", name: "English" },
  { code: "BM", name: "Bahasa Malaysia" },
  { code: "中文", name: "简体中文" },
  { code: "தமிழ்", name: "தமிழ்" },
];

const REGIONAL_FACTS = [
  {
    title: "MSIC code library",
    detail: "Built-in. Stays current with MyInvois catalog refreshes.",
  },
  {
    title: "BNM reference rates",
    detail: "Daily FX from Bank Negara for multi-currency invoices.",
  },
  {
    title: "FPX subscription billing",
    detail: "Pay in MYR with the local rails customers actually use.",
  },
  {
    title: "ap-southeast-5 hosting",
    detail: "Customer data lives in AWS Malaysia. DR replica in Singapore.",
  },
];

const ACCOUNTING = [
  { name: "SQL Account", mark: "SQL" },
  { name: "AutoCount", mark: "AC" },
  { name: "Sage UBS", mark: "SAGE" },
];

export function BuiltForMalaysia() {
  return (
    <section className="border-b border-slate-100 bg-slate-50">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <div className="grid gap-12 md:grid-cols-2 md:gap-16">
          <Reveal direction="left">
            <div>
              <span className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                Built for Malaysian businesses
              </span>
              <h2 className="mt-3 font-display text-3xl font-bold tracking-tight md:text-4xl">
                Not an international product translated. <em>Malaysian.</em>
              </h2>
              <p className="mt-6 text-lg text-slate-600">
                MyInvois has Malaysia-shaped requirements. The MSIC codes, the cancellation window,
                the regional languages, the local accounting systems. We started from those.
              </p>

              <div className="mt-8 flex flex-wrap gap-2">
                {LANGUAGES.map((lang) => (
                  <span
                    key={lang.code}
                    className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-ink"
                  >
                    {lang.code} <span className="text-slate-400">· {lang.name}</span>
                  </span>
                ))}
              </div>

              <div className="mt-10">
                <div className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                  Connects to the accounting systems you already use
                </div>
                <div className="mt-3 flex flex-wrap gap-3">
                  {ACCOUNTING.map((sys) => (
                    <div
                      key={sys.name}
                      className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2"
                    >
                      <span className="rounded bg-ink px-1.5 py-0.5 font-mono text-2xs text-paper">
                        {sys.mark}
                      </span>
                      <span className="text-sm font-medium text-ink">{sys.name}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </Reveal>

          <div className="grid gap-4 sm:grid-cols-2">
            {REGIONAL_FACTS.map((fact, i) => (
              <Reveal key={fact.title} delay={staggerDelay(i)}>
                <div className="rounded-xl border border-slate-100 bg-white p-6">
                  <h3 className="text-base font-semibold text-ink">{fact.title}</h3>
                  <p className="mt-2 text-sm text-slate-600">{fact.detail}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
