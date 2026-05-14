// /blog — empty state at launch with one founder note in place. Real posts
// slot into a content tree under /blog/[slug] later.

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Reveal } from "@/components/landing/Reveal";

type Post = {
  date: string;
  title: string;
  excerpt: string;
  readingTime: string;
  href: string;
};

const POSTS: Post[] = [
  {
    date: "Coming soon",
    title: "What Phase 4 means for a small business in May 2026",
    excerpt:
      "A plain-language walkthrough of what enforcement actually looks like, what to do in May, and what you can safely defer until July.",
    readingTime: "6 min read",
    href: "/blog",
  },
  {
    date: "Coming soon",
    title: "Reading a MyInvois rejection without panicking",
    excerpt:
      "The five most common rejection codes and the one-line fix for each. Print this and pin it near your accountant.",
    readingTime: "4 min read",
    href: "/blog",
  },
  {
    date: "Coming soon",
    title: "Self-billed invoices, in three calm paragraphs",
    excerpt:
      "When you should use self-billed, when you really shouldn't, and how to switch a customer from one mode to the other without breaking history.",
    readingTime: "5 min read",
    href: "/blog",
  },
];

export default function BlogPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Blog"
        headline={
          <>
            Calm reading <em>about a noisy regulator</em>.
          </>
        }
        description="What we're learning about LHDN MyInvois, AI extraction, and Malaysian SMEs. New posts ship as we have something genuinely useful to say."
      />

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
          <ul className="space-y-4">
            {POSTS.map((p, i) => (
              <Reveal key={p.title} as="li" delay={i * 0.08}>
                <Link
                  href={p.href}
                  className="group block rounded-xl border border-slate-100 bg-white p-8 transition-all duration-panel ease-zk hover:-translate-y-1 hover:border-ink hover:shadow-lg"
                >
                  <div className="flex items-center gap-3 text-2xs font-semibold uppercase tracking-wider text-slate-400">
                    <span>{p.date}</span>
                    <span className="text-slate-200">·</span>
                    <span>{p.readingTime}</span>
                  </div>
                  <h3 className="mt-2 font-display text-xl font-bold leading-snug tracking-tight text-ink">
                    {p.title}
                  </h3>
                  <p className="mt-3 text-base text-slate-600">{p.excerpt}</p>
                  <span className="mt-4 inline-flex items-center gap-1 text-xs font-medium text-ink">
                    Read post
                    <ArrowUpRight
                      size={14}
                      className="transition-transform duration-panel ease-zk group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
                    />
                  </span>
                </Link>
              </Reveal>
            ))}
          </ul>

          <Reveal>
            <p className="mt-12 border-t border-slate-100 pt-6 text-xs text-slate-400">
              Want these in your inbox? Add yourself in your dashboard → notifications, or write
              to{" "}
              <a className="underline underline-offset-4 hover:text-ink" href="mailto:contact@symprio.com">
                contact@symprio.com
              </a>
              .
            </p>
          </Reveal>
        </div>
      </section>
    </MarketingPage>
  );
}
