// /product — deep dive on what ZeroKey does. Built from the same primitives
// as the home page so the visual language stays consistent.
//
// Section coverage:
//   - Page header (title + sub)
//   - Capability grid (ingest / extract / sign / submit / archive)
//   - Architecture row (engines, audit, residency)
//   - HowItWorks (reused from home)
//   - Trust (reused)
//   - FinalCta (reused)

import {
  Boxes,
  FileText,
  Globe2,
  KeyRound,
  ScanLine,
  SearchCheck,
  ShieldCheck,
  Signature,
  Workflow,
} from "lucide-react";

import { Header } from "@/components/landing/Header";
import { Footer } from "@/components/landing/Footer";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { Trust } from "@/components/landing/Trust";
import { FinalCta } from "@/components/landing/FinalCta";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";

const CAPABILITIES = [
  {
    icon: ScanLine,
    title: "Ingest from anywhere",
    body: "PDF, image, Excel, email, WhatsApp, API. Forwarding rules handle the boring stuff so your team does not.",
  },
  {
    icon: SearchCheck,
    title: "Extract with confidence",
    body: "We pull out every LHDN field and tell you how confident we are about each one. Anything uncertain lands in the review queue automatically.",
  },
  {
    icon: FileText,
    title: "Validate before LHDN",
    body: "We catch the errors before MyInvois does — industry codes, tax types, totals, TIN format, currency lines. Fewer rejections, less back-and-forth.",
  },
  {
    icon: Signature,
    title: "Sign without exposure",
    body: "Your LHDN certificate stays sealed in hardware-grade storage. We sign on your behalf — we never carry the key around.",
  },
  {
    icon: Workflow,
    title: "Submit and track",
    body: "We send the invoice to LHDN, watch for the result, and write the UUID and QR code back to your record. You see the status live.",
  },
  {
    icon: Boxes,
    title: "Archive that survives audits",
    body: "Hash-chained, tamper-evident, exportable. Auditors get a bundle. You sleep at night.",
  },
];

const ARCHITECTURE = [
  {
    icon: ShieldCheck,
    title: "Reliable extraction, always",
    body: "If one extraction service has a bad day, ZeroKey quietly falls back to another. You never notice — your invoices keep moving.",
  },
  {
    icon: KeyRound,
    title: "Tamper-evident audit trail",
    body: "Every action is chained to the last. If something gets edited or removed, the chain breaks loudly. Auditors love it.",
  },
  {
    icon: Globe2,
    title: "Malaysian by default",
    body: "Your data lives in a Malaysian datacentre. Disaster recovery in Singapore. Multi-tenant isolation enforced at the storage level — your data and your competitor's never meet.",
  },
];

export default function ProductPage() {
  return (
    <>
      <Header />
      <main>
        <PageHero />
        <Capabilities />
        <Architecture />
        <HowItWorks />
        <Trust />
        <FinalCta />
      </main>
      <Footer />
    </>
  );
}

function PageHero() {
  return (
    <section className="relative overflow-hidden border-b border-slate-100">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-glow opacity-30 blur-3xl"
      />
      <div className="relative mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <span className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
            Product
          </span>
        </Reveal>
        <Reveal delay={0.06}>
          <h1 className="mt-3 max-w-3xl font-display text-4xl font-bold leading-[1.1] tracking-tight md:text-5xl">
            One pipeline from supplier PDF to <em>LHDN UUID</em>.
          </h1>
        </Reveal>
        <Reveal delay={0.12}>
          <p className="mt-6 max-w-2xl text-lg text-slate-600">
            ZeroKey is the boring infrastructure that turns the invoices already arriving in your
            inbox into compliant MyInvois submissions — without you typing a thing.
          </p>
        </Reveal>
      </div>
    </section>
  );
}

function Capabilities() {
  return (
    <section className="border-b border-slate-100 bg-paper">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
            Six things ZeroKey does well.
          </h2>
        </Reveal>
        <ul className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {CAPABILITIES.map((cap, i) => {
            const Icon = cap.icon;
            return (
              <Reveal key={cap.title} as="li" delay={staggerDelay(i)}>
                <div className="flex h-full flex-col gap-3 rounded-xl border border-slate-100 bg-white p-6 transition-transform duration-panel ease-zk hover:-translate-y-1 hover:shadow-lg">
                  <span className="grid h-10 w-10 place-items-center rounded-md bg-ink/5 text-ink">
                    <Icon size={20} />
                  </span>
                  <h3 className="text-base font-semibold text-ink">{cap.title}</h3>
                  <p className="text-sm text-slate-600">{cap.body}</p>
                </div>
              </Reveal>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

function Architecture() {
  return (
    <section className="border-b border-slate-100 bg-slate-50">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <div className="max-w-2xl">
            <span className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
              Under the hood
            </span>
            <h2 className="mt-3 font-display text-3xl font-bold tracking-tight md:text-4xl">
              Architecture choices we are willing to defend.
            </h2>
          </div>
        </Reveal>
        <div className="mt-12 grid gap-6 md:grid-cols-3">
          {ARCHITECTURE.map((a, i) => {
            const Icon = a.icon;
            return (
              <Reveal key={a.title} delay={staggerDelay(i)}>
                <div className="h-full rounded-xl border border-slate-100 bg-white p-8">
                  <span className="grid h-10 w-10 place-items-center rounded-md bg-signal/30 text-ink">
                    <Icon size={20} />
                  </span>
                  <h3 className="mt-4 text-lg font-semibold text-ink">{a.title}</h3>
                  <p className="mt-2 text-sm text-slate-600">{a.body}</p>
                </div>
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
}
