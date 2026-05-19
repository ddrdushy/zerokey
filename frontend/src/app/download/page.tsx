// DESKTOP_PIVOT_PLAN — /download.
//
// Phase 1 ships this as a teaser: explains the pivot and lets visitors
// register interest. The actual installer download (license-gated,
// signed S3 URL) lands in Phase 5 when the installer exists.

import Link from "next/link";
import { ArrowRight, CheckCircle2, Download, ShieldCheck } from "lucide-react";

import { Header } from "@/components/landing/Header";
import { Footer } from "@/components/landing/Footer";

export const metadata = {
  title: "Download — ZeroKey",
  description:
    "ZeroKey is becoming a desktop application. Your invoice data stays on your machine.",
};

const BULLETS = [
  "Invoice data never leaves your computer",
  "Works offline for up to 30 days at a stretch",
  "One annual license per company — no subscription",
  "Same LHDN submission, signed locally or by Symprio",
];

export default function DownloadPage() {
  return (
    <>
      <Header />
      <main className="bg-paper">
        <section className="mx-auto max-w-3xl px-4 py-16 md:py-24">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full bg-signal/15 px-3 py-1 text-2xs font-medium uppercase tracking-wider text-ink">
            <Download className="h-3.5 w-3.5" />
            Coming soon
          </div>
          <h1 className="font-display text-4xl font-bold tracking-tight text-ink md:text-5xl">
            ZeroKey is moving to your desktop.
          </h1>
          <p className="mt-4 text-base text-slate-600 md:text-lg">
            Drop the PDF. Drop the keys. And now — drop the cloud. The new
            ZeroKey runs on your Windows PC, keeps your invoice data on your
            own machine, and submits to LHDN without phoning home for every
            click.
          </p>

          <ul className="mt-8 grid gap-3 md:grid-cols-2">
            {BULLETS.map((b) => (
              <li
                key={b}
                className="flex items-start gap-2 rounded-md border border-slate-100 bg-white p-4 text-sm text-ink"
              >
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                <span>{b}</span>
              </li>
            ))}
          </ul>

          <div className="mt-10 flex flex-wrap items-center gap-4">
            <button
              type="button"
              disabled
              className="inline-flex cursor-not-allowed items-center gap-2 rounded-md bg-slate-200 px-5 py-3 text-sm font-semibold text-slate-500"
              title="Available when the desktop installer ships"
            >
              <Download className="h-4 w-4" />
              Download for Windows
            </button>
            <Link
              href="/contact"
              className="inline-flex items-center gap-2 text-sm font-medium text-ink underline-offset-4 hover:underline"
            >
              Tell us when it's ready
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>

          <div className="mt-12 rounded-md border border-slate-100 bg-white p-5">
            <div className="flex items-center gap-2 text-2xs font-medium uppercase tracking-wider text-slate-400">
              <ShieldCheck className="h-3.5 w-3.5" />
              Already a SaaS customer?
            </div>
            <p className="mt-2 text-sm text-slate-600">
              Your existing dashboard keeps working while we transition.
              Sign in to view your past activity. When the desktop installer
              is ready, we'll email everyone with an active account.
            </p>
            <div className="mt-3 flex gap-3">
              <Link
                href="/sign-in"
                className="text-2xs font-medium text-ink underline-offset-4 hover:underline"
              >
                Sign in
              </Link>
              <Link
                href="/dashboard"
                className="text-2xs font-medium text-slate-500 underline-offset-4 hover:underline"
              >
                Go to dashboard
              </Link>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
