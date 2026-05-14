"use client";

// /help — help-center landing. Topical groupings with a live search that
// filters article titles as you type. Empty-state shown when the query
// matches nothing.

import { useMemo, useState } from "react";
import { CreditCard, FileCheck, FileQuestion, Plug, Search, Settings, Users } from "lucide-react";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";

type Topic = {
  icon: typeof Search;
  title: string;
  items: string[];
};

const TOPICS: Topic[] = [
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
    items: [
      "Change languages",
      "Notification preferences",
      "Export your data",
      "Delete your account",
    ],
  },
];

export default function HelpPage() {
  const [query, setQuery] = useState("");
  const normalised = query.trim().toLowerCase();

  const filtered = useMemo<Topic[]>(() => {
    if (!normalised) return TOPICS;
    return TOPICS.map((t) => ({
      ...t,
      items: t.items.filter(
        (it) => it.toLowerCase().includes(normalised) || t.title.toLowerCase().includes(normalised),
      ),
    })).filter((t) => t.items.length > 0);
  }, [normalised]);

  const totalMatches = filtered.reduce((acc, t) => acc + t.items.length, 0);

  return (
    <MarketingPage>
      <PageHero
        eyebrow="Help center"
        headline={
          <>
            Answers to the questions <em>customers actually ask</em>.
          </>
        }
        description="Browse by topic, or search inline. We'd rather respond directly than make you guess."
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
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search help — e.g. 'cancel invoice'"
                className="w-full rounded-xl border border-slate-100 bg-white py-3 pl-10 pr-4 text-sm text-ink placeholder:text-slate-400 focus:border-ink focus:outline-none focus:ring-1 focus:ring-ink"
              />
            </label>
          </Reveal>

          {normalised ? (
            <p className="mt-3 text-xs text-slate-400">
              {totalMatches > 0
                ? `${totalMatches} article${totalMatches === 1 ? "" : "s"} matching "${query.trim()}"`
                : `No articles matching "${query.trim()}". Try a different word, or write to support@symprio.com.`}
            </p>
          ) : null}

          {filtered.length === 0 ? null : (
            <ul className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {filtered.map((topic, i) => {
                const Icon = topic.icon;
                return (
                  <Reveal key={topic.title} as="li" delay={staggerDelay(i)}>
                    <div className="flex h-full flex-col gap-4 rounded-xl border border-slate-100 bg-white p-6 transition-transform duration-panel ease-zk hover:-translate-y-1 hover:shadow-lg">
                      <div className="flex items-center gap-3">
                        <span className="grid h-9 w-9 place-items-center rounded-md bg-ink/5 text-ink">
                          <Icon size={18} />
                        </span>
                        <h3 className="text-base font-semibold text-ink">{topic.title}</h3>
                      </div>
                      <ul className="space-y-2 text-sm text-slate-600">
                        {topic.items.map((it) => (
                          <li key={it} className="flex items-start gap-2">
                            <span className="mt-1.5 inline-block h-1 w-1 shrink-0 rounded-full bg-signal" />
                            <span>{highlight(it, normalised)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </Reveal>
                );
              })}
            </ul>
          )}
        </div>
      </section>
    </MarketingPage>
  );
}

// Highlight matched substring with a subtle background. Case-insensitive.
function highlight(text: string, q: string) {
  if (!q) return text;
  const idx = text.toLowerCase().indexOf(q);
  if (idx === -1) return text;
  const before = text.slice(0, idx);
  const match = text.slice(idx, idx + q.length);
  const after = text.slice(idx + q.length);
  return (
    <>
      {before}
      <mark className="rounded bg-signal/40 px-0.5 text-ink">{match}</mark>
      {after}
    </>
  );
}
