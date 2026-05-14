// /integrations — the things ZeroKey plugs into. Focused on what customers
// connect, not how. Engines, OCR vendors and protocol acronyms intentionally
// stay out — landing pages talk in features, not stack.

import {
  FileSpreadsheet,
  Mail,
  MessageCircle,
  Plug,
  Globe2,
  Workflow,
  Bell,
} from "lucide-react";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { FinalCta } from "@/components/landing/FinalCta";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";

type Status = "live" | "beta" | "roadmap";

type Integration = {
  name: string;
  blurb: string;
  status: Status;
};

const ACCOUNTING: Integration[] = [
  { name: "SQL Account", blurb: "Two-way sync. Customers, items, invoices stay in step.", status: "live" },
  { name: "AutoCount", blurb: "Pulls your customer master and writes back submission status.", status: "live" },
  { name: "Sage UBS", blurb: "Read-only at launch. Two-way coming next.", status: "beta" },
  { name: "QuickBooks Online", blurb: "Multi-entity friendly. One-click connect.", status: "roadmap" },
  { name: "Xero", blurb: "Keeps tracking categories intact through the round-trip.", status: "roadmap" },
];

const CHANNELS: Integration[] = [
  { name: "Web upload", blurb: "Drag a PDF, image, or spreadsheet. Done.", status: "live" },
  { name: "Email forward", blurb: "Your own ZeroKey address. Forward and forget.", status: "live" },
  { name: "WhatsApp", blurb: "Snap or forward an invoice from your phone.", status: "beta" },
  { name: "Scheduled drop-folder", blurb: "Suppliers drop into a folder; we sweep it.", status: "live" },
];

const NOTIFICATIONS: Integration[] = [
  { name: "Email", blurb: "Per-event digests or instant alerts.", status: "live" },
  { name: "Slack", blurb: "Channel-routed exceptions and submission summaries.", status: "live" },
  { name: "Microsoft Teams", blurb: "Same as Slack — pick your weapon.", status: "live" },
  { name: "WhatsApp alerts", blurb: "Push the urgent stuff where your team already is.", status: "beta" },
];

const WORKPLACE: Integration[] = [
  { name: "Single sign-on", blurb: "Sign in with your company login. One click.", status: "live" },
  { name: "Multi-user roles", blurb: "Approver, reviewer, admin, accountant. Granular.", status: "live" },
  { name: "Audit log export", blurb: "Tamper-evident bundle for your auditor on demand.", status: "live" },
  { name: "Automation triggers", blurb: "Kick off your own workflows from invoice events.", status: "roadmap" },
];

const GROUPS: { title: string; icon: typeof Plug; items: Integration[] }[] = [
  { title: "Accounting systems", icon: FileSpreadsheet, items: ACCOUNTING },
  { title: "Ways to send invoices in", icon: Mail, items: CHANNELS },
  { title: "Alerts where your team works", icon: Bell, items: NOTIFICATIONS },
  { title: "Workplace + governance", icon: Globe2, items: WORKPLACE },
];

const PILL_STYLES: Record<Status, string> = {
  live: "bg-signal/30 text-ink",
  beta: "bg-ink/5 text-ink",
  roadmap: "bg-slate-100 text-slate-600",
};

const PILL_LABEL: Record<Status, string> = {
  live: "Available",
  beta: "Early access",
  roadmap: "Coming soon",
};

export default function IntegrationsPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Integrations"
        headline={
          <>
            Slots into the stack you <em>already use</em>.
          </>
        }
        description="Your accounting system, the inbox the invoices arrive in, the chat your team lives in, and the sign-in your IT team trusts. ZeroKey meets each one where it is."
      />

      {GROUPS.map((group, gi) => (
        <section
          key={group.title}
          className={`border-b border-slate-100 ${gi % 2 === 0 ? "bg-paper" : "bg-slate-50"}`}
        >
          <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-20">
            <Reveal>
              <div className="flex items-center gap-3">
                <span className="grid h-10 w-10 place-items-center rounded-md bg-ink/5 text-ink">
                  <group.icon size={20} />
                </span>
                <h2 className="font-display text-2xl font-bold tracking-tight md:text-3xl">
                  {group.title}
                </h2>
              </div>
            </Reveal>
            <ul className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {group.items.map((it, i) => (
                <Reveal key={it.name} as="li" delay={staggerDelay(i)}>
                  <div className="flex h-full items-start justify-between gap-4 rounded-xl border border-slate-100 bg-white p-6 transition-transform duration-panel ease-zk hover:-translate-y-1 hover:shadow-lg">
                    <div>
                      <h3 className="text-base font-semibold text-ink">{it.name}</h3>
                      <p className="mt-1 text-sm text-slate-600">{it.blurb}</p>
                    </div>
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-2xs font-semibold ${PILL_STYLES[it.status]}`}
                    >
                      {PILL_LABEL[it.status]}
                    </span>
                  </div>
                </Reveal>
              ))}
            </ul>
          </div>
        </section>
      ))}

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-20">
          <Reveal>
            <div className="grid gap-8 rounded-xl border border-slate-100 bg-white p-8 md:grid-cols-[auto_1fr_auto] md:items-center md:p-12">
              <span className="grid h-12 w-12 place-items-center rounded-md bg-ink text-paper">
                <Workflow size={22} />
              </span>
              <div>
                <h3 className="font-display text-xl font-bold tracking-tight text-ink">
                  Need something we don&apos;t list yet?
                </h3>
                <p className="mt-2 text-sm text-slate-600">
                  Tell us — if a few customers ask for the same thing, we ship it. The roadmap is
                  shaped by the inbox, not by guesses.
                </p>
              </div>
              <a
                href="/contact"
                className="inline-flex items-center justify-center rounded-md bg-ink px-5 py-2.5 text-sm font-medium text-paper transition-colors duration-ack ease-zk hover:bg-slate-800"
              >
                Request an integration
              </a>
            </div>
          </Reveal>
        </div>
      </section>

      <FinalCta />
    </MarketingPage>
  );
}
