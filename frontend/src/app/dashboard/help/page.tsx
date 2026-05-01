"use client";

// Help center index (Slice 93). Every validation rule code with a
// long-form article gets listed here, searchable, with a stable URL
// (#code) that the inline issue pills link to.

import { useMemo, useState } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { listHelpArticles } from "@/lib/help-articles";

export default function HelpPage() {
  const [query, setQuery] = useState("");
  const all = useMemo(() => listHelpArticles(), []);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (a) =>
        a.code.toLowerCase().includes(q) ||
        a.title.toLowerCase().includes(q) ||
        a.summary.toLowerCase().includes(q),
    );
  }, [all, query]);

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Help center
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600">
            Plain-language guides for every LHDN error code and ZeroKey
            validation rule. Each article explains <em>what</em> it means,{" "}
            <em>why</em> LHDN cares, and <em>how</em> to fix it.
          </p>
        </header>

        <input
          type="search"
          placeholder="Search by code, title, or keyword…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search help articles"
          className="w-full max-w-md rounded-md border border-slate-200 bg-white px-3 py-2 text-base text-ink focus:border-ink focus:outline-none"
        />

        <div className="text-2xs uppercase tracking-wider text-slate-400">
          {filtered.length} article{filtered.length === 1 ? "" : "s"}
        </div>

        <div className="flex flex-col gap-4">
          {filtered.map((article) => (
            <article
              key={article.code}
              id={article.code}
              className="rounded-xl border border-slate-100 bg-white p-5 scroll-mt-20"
            >
              <div className="flex items-baseline justify-between gap-3">
                <h2 className="font-display text-lg font-semibold tracking-tight">
                  {article.title}
                </h2>
                <code className="rounded bg-slate-100 px-2 py-0.5 font-mono text-2xs text-slate-500">
                  {article.code}
                </code>
              </div>
              <p className="mt-2 text-sm text-slate-600">{article.summary}</p>
              <p className="mt-3 text-2xs uppercase tracking-wider text-slate-400">
                Why LHDN cares
              </p>
              <p className="mt-1 text-sm text-slate-700">{article.why}</p>
              <p className="mt-3 text-2xs uppercase tracking-wider text-slate-400">
                How to fix it
              </p>
              <ol className="mt-1 flex list-decimal flex-col gap-1 pl-5 text-sm text-slate-700">
                {article.howToFix.map((step, idx) => (
                  <li key={idx}>{step}</li>
                ))}
              </ol>
              {article.reference && (
                <p className="mt-3 text-2xs italic text-slate-400">
                  Reference: {article.reference}
                </p>
              )}
            </article>
          ))}
          {filtered.length === 0 && (
            <p className="text-sm text-slate-400">
              No articles match your search. Try a code (e.g.
              <code className="mx-1 rounded bg-slate-100 px-1 py-0.5 font-mono text-2xs">
                supplier.tin.format
              </code>
              ) or a keyword.
            </p>
          )}
        </div>
      </div>
    </AppShell>
  );
}
