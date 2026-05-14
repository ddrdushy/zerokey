// /changelog — what shipped, when, and what it changed. Reads from a tiny
// hand-curated list at launch; moves to a generated feed once we have a
// stable cadence and a way to author entries without code changes.

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";

type ChangeKind = "new" | "improved" | "fixed";

type Entry = {
  date: string;
  title: string;
  kind: ChangeKind;
  detail: string;
};

const ENTRIES: Entry[] = [
  {
    date: "May 2026",
    title: "Soft-delete for organizations",
    kind: "improved",
    detail: "Restore a deleted organization within 30 days. No more accidental wipes.",
  },
  {
    date: "May 2026",
    title: "LHDN TIN lookup from BRN",
    kind: "new",
    detail: "Type your business registration number — we fetch the matching LHDN TIN for you.",
  },
  {
    date: "May 2026",
    title: "Auto-fill supplier details from tenant",
    kind: "improved",
    detail: "New invoices pre-populate the supplier block from your organization profile.",
  },
  {
    date: "Apr 2026",
    title: "Scheduled submission",
    kind: "new",
    detail: "Schedule an invoice to submit at a future date — perfect for end-of-month batches.",
  },
  {
    date: "Apr 2026",
    title: "Encrypted PII at rest",
    kind: "improved",
    detail: "Phone numbers, addresses, and ID numbers are now individually encrypted on disk.",
  },
  {
    date: "Mar 2026",
    title: "Audit log export bundle",
    kind: "new",
    detail: "Generate a tamper-evident audit bundle for your auditor in one click.",
  },
  {
    date: "Mar 2026",
    title: "Sage UBS connector — read-only",
    kind: "new",
    detail: "Pull your customer master and invoice history from Sage UBS into ZeroKey.",
  },
  {
    date: "Feb 2026",
    title: "WhatsApp ingestion",
    kind: "new",
    detail: "Forward an invoice photo from WhatsApp; we extract and route it like any other channel.",
  },
];

const PILL: Record<ChangeKind, { label: string; cls: string }> = {
  new: { label: "New", cls: "bg-signal/30 text-ink" },
  improved: { label: "Improved", cls: "bg-ink/5 text-ink" },
  fixed: { label: "Fixed", cls: "bg-slate-100 text-slate-600" },
};

export default function ChangelogPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Changelog"
        headline={
          <>
            What shipped, <em>and what it changed for you</em>.
          </>
        }
        description="Material changes only. We don't list patch-version bumps; you don't care."
      />

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
          <ol className="space-y-10 border-l border-slate-100 pl-8 md:pl-10">
            {ENTRIES.map((e, i) => (
              <Reveal key={e.title + e.date} as="li" delay={staggerDelay(i, 0.04)}>
                <div className="relative">
                  <span
                    aria-hidden="true"
                    className="absolute -left-[37px] top-2 grid h-2 w-2 place-items-center rounded-full bg-signal md:-left-[45px]"
                  />
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                      {e.date}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 text-2xs font-semibold ${PILL[e.kind].cls}`}>
                      {PILL[e.kind].label}
                    </span>
                  </div>
                  <h3 className="mt-2 font-display text-lg font-bold tracking-tight text-ink">
                    {e.title}
                  </h3>
                  <p className="mt-1 text-base text-slate-600">{e.detail}</p>
                </div>
              </Reveal>
            ))}
          </ol>

          <Reveal delay={0.2}>
            <p className="mt-12 border-t border-slate-100 pt-6 text-xs text-slate-400">
              Subscribe to changelog updates from your account settings → notifications.
            </p>
          </Reveal>
        </div>
      </section>
    </MarketingPage>
  );
}
