// /help — help-center landing. Topical groupings with placeholder article
// links. The /help/[slug] sub-pages get wired as articles are written.

import { CreditCard, FileCheck, FileQuestion, Plug, Search, Settings, Users } from "lucide-react";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";

const TOPICS = [
  {
    icon: FileQuestion,
    title: "Getting started",
    items: [
      "Create your account and your first organisation",
      "Upload your LHDN certificate",
      "Send your first invoice end-to-end",
    ],
  },
  {
    icon: FileCheck,
    title: "Working with invoices",
    items: [
      "What ‘Validated’ really means",
      "Cancelling an invoice within the 72-hour window",
      "Self-billed invoices",
      "Multi-currency invoices",
    ],
  },
  {
    icon: Plug,
    title: "Connectors",
    items: [
      "Connect SQL Account",
      "Connect AutoCount",
      "Connect Sage UBS",
      "Sync rules and conflict resolution",
    ],
  },
  {
    icon: Users,
    title: "Team & permissions",
    items: ["Invite teammates", "Roles explained", "Approval flows", "Give your accountant access"],
  },
  {
    icon: CreditCard,
    title: "Billing",
    items: [
      "Change plan or cancel",
      "Overage rules and how to read your invoice",
      "Refunds and the money-back guarantee",
    ],
  },
  {
    icon: Settings,
    title: "Settings & account",
    items: ["Change languages", "Notification preferences", "Export your data", "Delete your account"],
  },
];

export default function HelpPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Help center"
        headline={
          <>
            Answers to the questions <em>customers actually ask</em>.
          </>
        }
        description="Browse by topic, or write to support@symprio.com. We'd rather respond directly than make you guess."
      />

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
          <Reveal>
            <label className="relative block max-w-2xl">
              <span className="sr-only">Search help articles</span>
              <span className="pointer-events-none absolute inset-y-0 left-3 grid place-items-center text-slate-400">
                <Search size={16} />
              </span>
              <input
                type="search"
                placeholder="Search help — e.g. 'cancel invoice'"
                className="w-full rounded-xl border border-slate-100 bg-white py-3 pl-10 pr-4 text-sm text-ink placeholder:text-slate-400 focus:border-ink focus:outline-none focus:ring-1 focus:ring-ink"
              />
            </label>
          </Reveal>

          <ul className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {TOPICS.map((t, i) => {
              const Icon = t.icon;
              return (
                <Reveal key={t.title} as="li" delay={staggerDelay(i)}>
                  <div className="flex h-full flex-col gap-4 rounded-xl border border-slate-100 bg-white p-6 transition-transform duration-panel ease-zk hover:-translate-y-1 hover:shadow-lg">
                    <div className="flex items-center gap-3">
                      <span className="grid h-9 w-9 place-items-center rounded-md bg-ink/5 text-ink">
                        <Icon size={18} />
                      </span>
                      <h3 className="text-base font-semibold text-ink">{t.title}</h3>
                    </div>
                    <ul className="space-y-2 text-sm text-slate-600">
                      {t.items.map((it) => (
                        <li key={it} className="flex items-start gap-2">
                          <span className="mt-1.5 inline-block h-1 w-1 shrink-0 rounded-full bg-signal" />
                          <span>{it}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </Reveal>
              );
            })}
          </ul>
        </div>
      </section>
    </MarketingPage>
  );
}
