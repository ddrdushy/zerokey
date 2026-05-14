// Long-form typography wrapper for marketing pages that are mostly text
// (legal docs, About, blog posts). Sets sensible defaults for headings,
// paragraphs, lists, and tables so each page doesn't have to re-style them.
// Stays Tailwind-native — no @tailwindcss/typography dependency.

import type { ReactNode } from "react";

import { Reveal } from "@/components/landing/Reveal";

export function Prose({ children }: { children: ReactNode }) {
  return (
    <section className="border-b border-slate-100 bg-paper">
      <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <div
            className={[
              "max-w-none text-base text-slate-600",
              "[&_h2]:mt-12 [&_h2]:mb-4 [&_h2]:font-display [&_h2]:text-2xl [&_h2]:font-bold [&_h2]:tracking-tight [&_h2]:text-ink",
              "[&_h3]:mt-8 [&_h3]:mb-3 [&_h3]:text-lg [&_h3]:font-semibold [&_h3]:text-ink",
              "[&_p]:mt-4 [&_p]:leading-relaxed",
              "[&_ul]:mt-4 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:space-y-2",
              "[&_ol]:mt-4 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:space-y-2",
              "[&_a]:text-ink [&_a]:underline [&_a]:underline-offset-4 hover:[&_a]:text-slate-600",
              "[&_strong]:font-semibold [&_strong]:text-ink",
              "[&_code]:rounded [&_code]:bg-slate-100 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-2xs [&_code]:text-ink",
              "[&_hr]:my-12 [&_hr]:border-slate-100",
              "[&_blockquote]:mt-6 [&_blockquote]:border-l-2 [&_blockquote]:border-signal [&_blockquote]:pl-4 [&_blockquote]:text-slate-600 [&_blockquote]:italic",
            ].join(" ")}
          >
            {children}
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/**
 * Small "last-updated" header used at the top of every legal page so
 * visitors know how stale the document is at a glance.
 */
export function LastUpdated({ date }: { date: string }) {
  return (
    <p className="mb-12 text-2xs font-medium uppercase tracking-wider text-slate-400">
      Last updated · {date}
    </p>
  );
}
