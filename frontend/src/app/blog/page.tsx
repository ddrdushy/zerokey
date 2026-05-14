// /blog — index of posts. Reads from lib/blog-posts so new entries appear
// automatically without touching this file.

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Reveal } from "@/components/landing/Reveal";
import { BLOG_POSTS } from "@/lib/blog-posts";

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
        description="What we're learning about LHDN MyInvois and Malaysian SMEs. New posts ship as we have something useful to say."
      />

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
          <ul className="space-y-4">
            {BLOG_POSTS.map((p, i) => (
              <Reveal key={p.slug} as="li" delay={i * 0.08}>
                <Link
                  href={`/blog/${p.slug}`}
                  className="group block rounded-xl border border-slate-100 bg-white p-8 transition-all duration-panel ease-zk hover:-translate-y-1 hover:border-ink hover:shadow-lg"
                >
                  <div className="flex items-center gap-3 text-2xs font-semibold uppercase tracking-wider text-slate-400">
                    <span>{p.date}</span>
                    <span className="text-slate-200">·</span>
                    <span>{p.readingMinutes} min read</span>
                  </div>
                  <h2 className="mt-2 font-display text-xl font-bold leading-snug tracking-tight text-ink">
                    {p.title}
                  </h2>
                  <p className="mt-3 text-base text-slate-600">{p.excerpt}</p>
                  <div className="mt-4 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div
                        aria-hidden="true"
                        className="grid h-7 w-7 place-items-center rounded-full bg-ink font-display text-2xs font-bold text-paper"
                      >
                        {p.author[0]}
                      </div>
                      <div className="text-2xs text-slate-400">
                        {p.author} · {p.authorTitle}
                      </div>
                    </div>
                    <span className="inline-flex items-center gap-1 text-xs font-medium text-ink">
                      Read post
                      <ArrowUpRight
                        size={14}
                        className="transition-transform duration-panel ease-zk group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
                      />
                    </span>
                  </div>
                </Link>
              </Reveal>
            ))}
          </ul>

          <Reveal>
            <p className="mt-12 border-t border-slate-100 pt-6 text-xs text-slate-400">
              Want new posts in your inbox? Add yourself in your dashboard → notifications, or
              write to{" "}
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
