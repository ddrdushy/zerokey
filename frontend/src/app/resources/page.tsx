// /resources — a directory of everything outside the product itself.
// At launch most of these link out to placeholders that will become real
// pages over time. This page collects them in one place so visitors who
// want depth know where to find it.

import {
  ArrowUpRight,
  BookOpenText,
  FileCode2,
  GraduationCap,
  LifeBuoy,
  ListTree,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

import { Header } from "@/components/landing/Header";
import { Footer } from "@/components/landing/Footer";
import { Faq } from "@/components/landing/Faq";
import { FinalCta } from "@/components/landing/FinalCta";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";

const RESOURCES = [
  {
    icon: BookOpenText,
    title: "Documentation",
    body: "How to onboard, how to wire connectors, what every screen does.",
    href: "/docs",
    cta: "Read the docs",
  },
  {
    icon: FileCode2,
    title: "API reference",
    body: "REST endpoints, request/response shapes, webhooks. OpenAPI spec downloadable.",
    href: "/api",
    cta: "Open API reference",
  },
  {
    icon: GraduationCap,
    title: "Blog",
    body: "What we are learning about LHDN MyInvois, AI extraction, and Malaysian SMEs.",
    href: "/blog",
    cta: "Read the blog",
  },
  {
    icon: LifeBuoy,
    title: "Help center",
    body: "Step-by-step articles for the questions customers ask most.",
    href: "/help",
    cta: "Browse articles",
  },
  {
    icon: ListTree,
    title: "Changelog",
    body: "What shipped, when, and what it changed.",
    href: "/changelog",
    cta: "See the changelog",
  },
  {
    icon: ShieldCheck,
    title: "Security & compliance",
    body: "Our security posture, certifications in flight, and the data-handling commitments behind them.",
    href: "/security",
    cta: "View posture",
  },
];

const LHDN_CHEAT_SHEET = [
  {
    deadline: "1 Aug 2024",
    label: "Phase 1",
    detail: "Mandatory for taxpayers > RM 100M.",
  },
  {
    deadline: "1 Jan 2025",
    label: "Phase 2",
    detail: "Mandatory for RM 25M–100M.",
  },
  {
    deadline: "1 Jul 2025",
    label: "Phase 3",
    detail: "Mandatory for RM 5M–25M.",
  },
  {
    deadline: "1 Jan 2026",
    label: "Phase 4",
    detail: "Mandatory for RM 1M–5M (you, probably).",
  },
  {
    deadline: "1 Jan 2027",
    label: "Penalty enforcement",
    detail: "RM 200 – RM 20,000 per non-compliant invoice.",
  },
];

export default function ResourcesPage() {
  return (
    <>
      <Header />
      <main>
        <PageHero />
        <ResourceGrid />
        <CheatSheet />
        <Faq />
        <FinalCta />
      </main>
      <Footer />
    </>
  );
}

function PageHero() {
  return (
    <section className="border-b border-slate-100">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <span className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
            Resources
          </span>
        </Reveal>
        <Reveal delay={0.06}>
          <h1 className="mt-3 max-w-3xl font-display text-4xl font-bold leading-[1.1] tracking-tight md:text-5xl">
            The shelf where we keep <em>the good stuff</em>.
          </h1>
        </Reveal>
        <Reveal delay={0.12}>
          <p className="mt-6 max-w-2xl text-lg text-slate-600">
            Docs, reference material, articles, and the security posture. Bookmark whichever you
            need.
          </p>
        </Reveal>
      </div>
    </section>
  );
}

function ResourceGrid() {
  return (
    <section className="border-b border-slate-100 bg-paper">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {RESOURCES.map((r, i) => {
            const Icon = r.icon;
            return (
              <Reveal key={r.title} as="li" delay={staggerDelay(i)}>
                <Link
                  href={r.href}
                  className="group flex h-full flex-col gap-3 rounded-xl border border-slate-100 bg-white p-6 transition-all duration-panel ease-zk hover:-translate-y-1 hover:border-ink hover:shadow-lg"
                >
                  <div className="flex items-start justify-between">
                    <span className="grid h-10 w-10 place-items-center rounded-md bg-ink/5 text-ink">
                      <Icon size={20} />
                    </span>
                    <ArrowUpRight
                      size={18}
                      className="text-slate-400 transition-transform duration-panel ease-zk group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-ink"
                    />
                  </div>
                  <h3 className="text-base font-semibold text-ink">{r.title}</h3>
                  <p className="text-sm text-slate-600">{r.body}</p>
                  <span className="mt-auto text-xs font-medium text-ink">{r.cta}</span>
                </Link>
              </Reveal>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

function CheatSheet() {
  return (
    <section className="border-b border-slate-100 bg-slate-50">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <div className="max-w-2xl">
            <span className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
              LHDN MyInvois cheat sheet
            </span>
            <h2 className="mt-3 font-display text-3xl font-bold tracking-tight md:text-4xl">
              The dates worth circling.
            </h2>
          </div>
        </Reveal>

        <ol className="mt-12 grid gap-4 md:grid-cols-5">
          {LHDN_CHEAT_SHEET.map((row, i) => (
            <Reveal key={row.deadline} as="li" delay={staggerDelay(i)}>
              <div className="flex h-full flex-col gap-3 rounded-xl border border-slate-100 bg-white p-6">
                <span className="font-display text-lg font-bold text-ink">{row.deadline}</span>
                <span className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                  {row.label}
                </span>
                <p className="text-sm text-slate-600">{row.detail}</p>
              </div>
            </Reveal>
          ))}
        </ol>
      </div>
    </section>
  );
}
