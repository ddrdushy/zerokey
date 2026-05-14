// /blog/[slug] — one blog post. Statically generated from the catalog in
// lib/blog-posts. Same shell + typography as the help articles for visual
// consistency across long-form content.

import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ArrowUpRight, Clock } from "lucide-react";
import type { Metadata } from "next";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { Prose } from "@/components/marketing/Prose";
import { Reveal } from "@/components/landing/Reveal";
import { BLOG_POSTS, findPost } from "@/lib/blog-posts";

type Props = { params: { slug: string } };

export function generateStaticParams() {
  return BLOG_POSTS.map((p) => ({ slug: p.slug }));
}

export function generateMetadata({ params }: Props): Metadata {
  const post = findPost(params.slug);
  if (!post) return { title: "Post not found · ZeroKey blog" };
  return {
    title: `${post.title} · ZeroKey blog`,
    description: post.excerpt,
  };
}

export default function BlogPostPage({ params }: Props) {
  const post = findPost(params.slug);
  if (!post) notFound();

  const others = BLOG_POSTS.filter((p) => p.slug !== post.slug).slice(0, 2);

  return (
    <MarketingPage>
      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-3xl px-4 pb-12 pt-12 md:px-8 md:pb-16 md:pt-16">
          <Reveal>
            <Link
              href="/blog"
              className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-400 transition-colors duration-ack hover:text-ink"
            >
              <ArrowLeft size={14} />
              All posts
            </Link>
          </Reveal>
          <Reveal delay={0.04}>
            <div className="mt-6 flex flex-wrap items-center gap-3 text-2xs font-semibold uppercase tracking-wider text-slate-400">
              <span>{post.date}</span>
              <span className="text-slate-200">·</span>
              <span className="inline-flex items-center gap-1">
                <Clock size={11} /> {post.readingMinutes} min read
              </span>
            </div>
          </Reveal>
          <Reveal delay={0.08}>
            <h1 className="mt-3 font-display text-4xl font-bold leading-[1.1] tracking-tight md:text-5xl">
              {post.title}
            </h1>
          </Reveal>
          <Reveal delay={0.12}>
            <p className="mt-4 max-w-2xl text-lg text-slate-600">{post.excerpt}</p>
          </Reveal>
          <Reveal delay={0.16}>
            <div className="mt-8 flex items-center gap-3">
              <div
                aria-hidden="true"
                className="grid h-10 w-10 place-items-center rounded-full bg-ink font-display text-sm font-bold text-paper"
              >
                {post.author[0]}
              </div>
              <div>
                <div className="text-sm font-semibold text-ink">{post.author}</div>
                <div className="text-2xs text-slate-400">{post.authorTitle}</div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      <Prose>
        {post.sections.map((s) => (
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
          Questions on this post? Write to{" "}
          <a href="mailto:contact@symprio.com">contact@symprio.com</a> — we read every email.
        </p>
      </Prose>

      {others.length > 0 ? (
        <section className="border-b border-slate-100 bg-slate-50">
          <div className="mx-auto max-w-3xl px-4 py-12 md:px-8 md:py-16">
            <Reveal>
              <h2 className="font-display text-2xl font-bold tracking-tight">Keep reading</h2>
            </Reveal>
            <ul className="mt-6 grid gap-3 md:grid-cols-2">
              {others.map((o, i) => (
                <Reveal key={o.slug} as="li" delay={0.04 * i}>
                  <Link
                    href={`/blog/${o.slug}`}
                    className="group flex h-full flex-col gap-2 rounded-xl border border-slate-100 bg-white p-5 transition-all duration-panel ease-zk hover:-translate-y-1 hover:border-ink hover:shadow-lg"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="font-display text-base font-bold leading-snug text-ink">
                        {o.title}
                      </h3>
                      <ArrowUpRight
                        size={14}
                        className="shrink-0 text-slate-400 transition-transform duration-panel ease-zk group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-ink"
                      />
                    </div>
                    <p className="text-xs text-slate-600">{o.excerpt}</p>
                    <div className="mt-auto flex items-center gap-1 text-2xs text-slate-400">
                      <Clock size={11} />
                      {o.readingMinutes} min read
                    </div>
                  </Link>
                </Reveal>
              ))}
            </ul>
          </div>
        </section>
      ) : null}
    </MarketingPage>
  );
}
