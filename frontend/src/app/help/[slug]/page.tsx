// /help/[slug] — one help article. Statically generated at build time
// from the article list in lib/marketing-help so every entry ships as a
// pre-rendered page (good for SEO and offline-friendly link sharing).

import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ArrowUpRight, Clock } from "lucide-react";
import type { Metadata } from "next";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { Prose } from "@/components/marketing/Prose";
import { Reveal } from "@/components/landing/Reveal";
import {
  HELP_ARTICLES,
  HELP_TOPICS,
  findArticle,
} from "@/lib/marketing-help";

type Props = { params: { slug: string } };

export function generateStaticParams() {
  return HELP_ARTICLES.map((a) => ({ slug: a.slug }));
}

export function generateMetadata({ params }: Props): Metadata {
  const article = findArticle(params.slug);
  if (!article) return { title: "Article not found · ZeroKey help" };
  return {
    title: `${article.title} · ZeroKey help`,
    description: article.summary,
  };
}

export default function HelpArticlePage({ params }: Props) {
  const article = findArticle(params.slug);
  if (!article) notFound();

  const topic = HELP_TOPICS[article.topic];

  return (
    <MarketingPage>
      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-3xl px-4 pb-12 pt-12 md:px-8 md:pb-16 md:pt-16">
          <Reveal>
            <Link
              href="/help"
              className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-400 transition-colors duration-ack hover:text-ink"
            >
              <ArrowLeft size={14} />
              All help
            </Link>
          </Reveal>
          <Reveal delay={0.04}>
            <div className="mt-6 flex flex-wrap items-center gap-3 text-2xs font-semibold uppercase tracking-wider text-slate-400">
              <span>{topic.title}</span>
              <span className="text-slate-200">·</span>
              <span className="inline-flex items-center gap-1">
                <Clock size={11} /> {article.readingMinutes} min read
              </span>
            </div>
          </Reveal>
          <Reveal delay={0.08}>
            <h1 className="mt-3 font-display text-4xl font-bold leading-[1.1] tracking-tight md:text-5xl">
              {article.title}
            </h1>
          </Reveal>
          <Reveal delay={0.12}>
            <p className="mt-4 max-w-2xl text-lg text-slate-600">{article.summary}</p>
          </Reveal>
        </div>
      </section>

      <Prose>
        {article.sections.map((s) => (
          <div key={s.heading}>
            <h2>{s.heading}</h2>
            {s.paragraphs.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
            {s.bullets ? (
              <ul>
                {s.bullets.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ))}

        <hr />
        <p>
          Need more help? Write to{" "}
          <a href="mailto:contact@symprio.com">contact@symprio.com</a>. We&apos;d rather respond
          directly than make you guess.
        </p>
      </Prose>

      {article.seeAlso && article.seeAlso.length > 0 ? (
        <section className="border-b border-slate-100 bg-slate-50">
          <div className="mx-auto max-w-3xl px-4 py-12 md:px-8 md:py-16">
            <Reveal>
              <h2 className="font-display text-2xl font-bold tracking-tight">See also</h2>
            </Reveal>
            <ul className="mt-6 grid gap-3 md:grid-cols-2">
              {article.seeAlso.map((s, i) => {
                const related = findArticle(s);
                if (!related) return null;
                return (
                  <Reveal key={s} as="li" delay={0.04 * i}>
                    <Link
                      href={`/help/${related.slug}`}
                      className="group flex items-start justify-between gap-3 rounded-xl border border-slate-100 bg-white p-5 transition-all duration-panel ease-zk hover:-translate-y-1 hover:border-ink hover:shadow-lg"
                    >
                      <div>
                        <div className="text-sm font-semibold text-ink">{related.title}</div>
                        <div className="mt-1 text-xs text-slate-600">{related.summary}</div>
                      </div>
                      <ArrowUpRight
                        size={16}
                        className="shrink-0 text-slate-400 transition-transform duration-panel ease-zk group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-ink"
                      />
                    </Link>
                  </Reveal>
                );
              })}
            </ul>
          </div>
        </section>
      ) : null}
    </MarketingPage>
  );
}
