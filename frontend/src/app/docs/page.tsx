// /docs — documentation landing. At launch this is a directory pointing to
// help articles by topic. As the docs hub grows we wire it up as a real
// content tree.

import { ArrowUpRight, BookOpen, FileText, KeyRound, Plug, Settings, Users } from "lucide-react";
import Link from "next/link";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";

const TOPICS = [
  {
    icon: BookOpen,
    title: "Getting started",
    body: "Sign up, set up your organization, upload your first invoice.",
    href: "/help",
  },
  {
    icon: KeyRound,
    title: "Set up your LHDN certificate",
    body: "How to register with LHDN, generate the cert, and upload it safely.",
    href: "/help",
  },
  {
    icon: FileText,
    title: "Working with invoices",
    body: "Drop, extract, review, approve, submit — and what to do when one comes back rejected.",
    href: "/help",
  },
  {
    icon: Plug,
    title: "Connect your accounting system",
    body: "SQL Account, AutoCount and Sage UBS — what to expect, what to authorise.",
    href: "/help",
  },
  {
    icon: Users,
    title: "Team and permissions",
    body: "Inviting users, roles, approval flows, and how to keep your accountant happy.",
    href: "/help",
  },
  {
    icon: Settings,
    title: "Account settings",
    body: "Billing, notifications, language, and the rest of the small stuff that matters.",
    href: "/help",
  },
];

export default function DocsPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Documentation"
        headline={
          <>
            Everything we know about ZeroKey, <em>written down</em>.
          </>
        }
        description="Step-by-step guides for every part of the product. Plain language, screenshots where they help, the right link in every paragraph."
      />

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
          <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {TOPICS.map((t, i) => {
              const Icon = t.icon;
              return (
                <Reveal key={t.title} as="li" delay={staggerDelay(i)}>
                  <Link
                    href={t.href}
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
                    <h3 className="text-base font-semibold text-ink">{t.title}</h3>
                    <p className="text-sm text-slate-600">{t.body}</p>
                    <span className="mt-auto text-xs font-medium text-ink">Read articles →</span>
                  </Link>
                </Reveal>
              );
            })}
          </ul>
        </div>
      </section>

      <section className="border-b border-slate-100 bg-slate-50">
        <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
          <Reveal>
            <div className="rounded-xl border border-slate-100 bg-white p-8 md:p-12">
              <h3 className="font-display text-xl font-bold tracking-tight text-ink">
                Can&apos;t find what you need?
              </h3>
              <p className="mt-3 text-base text-slate-600">
                Email <a className="underline underline-offset-4 hover:text-ink" href="mailto:contact@symprio.com">contact@symprio.com</a> with the question. We&apos;d rather write a new article
                than make you wait.
              </p>
            </div>
          </Reveal>
        </div>
      </section>
    </MarketingPage>
  );
}
