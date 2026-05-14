"use client";

// Client-side filter + topic grouping for the help center. The query
// matches against article title + summary; topic cards collapse to show
// only matching entries while the search is non-empty.

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Clock, Search } from "lucide-react";

import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";
import {
  HELP_ARTICLES,
  HELP_TOPICS,
  type HelpArticleMeta,
  type HelpTopicId,
} from "@/lib/marketing-help";

export function HelpIndex() {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();

  const filtered: HelpArticleMeta[] = useMemo(() => {
    if (!q) return HELP_ARTICLES;
    return HELP_ARTICLES.filter((a) => {
      const hay = `${a.title} ${a.summary}`.toLowerCase();
      return hay.includes(q);
    });
  }, [q]);

  const grouped = useMemo(() => {
    const out = new Map<HelpTopicId, HelpArticleMeta[]>();
    for (const a of filtered) {
      const list = out.get(a.topic) ?? [];
      list.push(a);
      out.set(a.topic, list);
    }
    return out;
  }, [filtered]);

  const hasResults = filtered.length > 0;
  const topicIds = (Object.keys(HELP_TOPICS) as HelpTopicId[]).filter((id) =>
    grouped.has(id),
  );

  return (
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
              placeholder="Search help — try ‘cancel invoice’ or ‘SQL Account’"
              className="w-full rounded-xl border border-slate-100 bg-white py-3 pl-10 pr-4 text-sm text-ink placeholder:text-slate-400 focus:border-ink focus:outline-none focus:ring-1 focus:ring-ink"
            />
          </label>
        </Reveal>

        {q ? (
          <Reveal delay={0.04}>
            <p className="mt-4 text-xs text-slate-400">
              {filtered.length} result{filtered.length === 1 ? "" : "s"} for{" "}
              <strong className="text-ink">&ldquo;{query}&rdquo;</strong>
            </p>
          </Reveal>
        ) : null}

        {hasResults ? (
          <div className="mt-12 space-y-12">
            {topicIds.map((tid, ti) => (
              <Reveal key={tid} delay={staggerDelay(ti, 0.04)}>
                <div>
                  <h2 className="font-display text-xl font-bold tracking-tight text-ink">
                    {HELP_TOPICS[tid].title}
                  </h2>
                  <ul className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                    {grouped.get(tid)!.map((a, ai) => (
                      <Reveal key={a.slug} as="li" delay={staggerDelay(ai, 0.04)}>
                        <Link
                          href={`/help/${a.slug}`}
                          className="group flex h-full flex-col gap-2 rounded-xl border border-slate-100 bg-white p-5 transition-all duration-panel ease-zk hover:-translate-y-1 hover:border-ink hover:shadow-lg"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <h3 className="text-sm font-semibold text-ink">{a.title}</h3>
                            <ArrowUpRight
                              size={14}
                              className="shrink-0 text-slate-400 transition-transform duration-panel ease-zk group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-ink"
                            />
                          </div>
                          <p className="text-xs text-slate-600">{a.summary}</p>
                          <div className="mt-auto flex items-center gap-1 text-2xs text-slate-400">
                            <Clock size={11} />
                            {a.readingMinutes} min read
                          </div>
                        </Link>
                      </Reveal>
                    ))}
                  </ul>
                </div>
              </Reveal>
            ))}
          </div>
        ) : (
          <Reveal delay={0.08}>
            <div className="mt-12 rounded-xl border border-dashed border-slate-200 bg-white p-10 text-center">
              <h3 className="font-display text-lg font-bold text-ink">No matching articles.</h3>
              <p className="mt-2 text-sm text-slate-600">
                Try a different search, or write to{" "}
                <a
                  className="underline underline-offset-4 hover:text-ink"
                  href="mailto:contact@symprio.com"
                >
                  contact@symprio.com
                </a>
                . We&apos;d rather write a new article than make you wait.
              </p>
              <button
                type="button"
                onClick={() => setQuery("")}
                className="mt-4 inline-flex items-center justify-center rounded-md border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-ink transition-colors duration-ack hover:bg-slate-50"
              >
                Clear search
              </button>
            </div>
          </Reveal>
        )}
      </div>
    </section>
  );
}
