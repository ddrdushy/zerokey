// DESKTOP_PIVOT_PLAN Phase 5 — /download.
//
// Three states for the visitor, resolved client-side:
//   1. Anonymous — show the pitch + "Buy a license" CTA pointing at /pricing.
//   2. Authenticated but no active license — show "Buy a license".
//   3. Authenticated with at least one active license — show the
//      per-platform installer download buttons returned by
//      /api/v1/licenses/desktop-release/.

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Apple,
  ArrowRight,
  CheckCircle2,
  Download,
  Loader2,
  Monitor,
  ShieldCheck,
} from "lucide-react";

import { Header } from "@/components/landing/Header";
import { Footer } from "@/components/landing/Footer";
import { api, ApiError } from "@/lib/api";

const BULLETS = [
  "Invoice data never leaves your computer",
  "Works offline for up to 30 days at a stretch",
  "One annual license per company — no subscription",
  "Same LHDN submission, signed locally or by Symprio",
];

type ReleaseInfo = Awaited<ReturnType<typeof api.desktopRelease>>;

type State =
  | { kind: "loading" }
  | { kind: "anonymous" }
  | { kind: "no_license" }
  | { kind: "ready"; release: ReleaseInfo };

export default function DownloadPage() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    api
      .desktopRelease()
      .then((release) => {
        if (cancelled) return;
        setState({ kind: "ready", release });
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError) {
          if (err.status === 401) setState({ kind: "anonymous" });
          else if (err.status === 403) setState({ kind: "no_license" });
          else setState({ kind: "anonymous" }); // network etc → soft fallback
        } else {
          setState({ kind: "anonymous" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <Header />
      <main className="bg-paper">
        <section className="mx-auto max-w-3xl px-4 py-16 md:py-24">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full bg-signal/15 px-3 py-1 text-2xs font-medium uppercase tracking-wider text-ink">
            <Download className="h-3.5 w-3.5" />
            ZeroKey desktop
          </div>
          <h1 className="font-display text-4xl font-bold tracking-tight text-ink md:text-5xl">
            Get ZeroKey on your computer.
          </h1>
          <p className="mt-4 text-base text-slate-600 md:text-lg">
            Install on your Windows PC. Sign in once with your license key
            and your invoice ingestion, validation, and LHDN submission
            stay on your machine.
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

          <section className="mt-10">
            {state.kind === "loading" && (
              <div className="flex items-center gap-2 rounded-md border border-slate-100 bg-white p-6 text-2xs text-slate-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                Checking your license…
              </div>
            )}

            {state.kind === "anonymous" && <AnonymousCta />}
            {state.kind === "no_license" && <NoLicenseCta />}
            {state.kind === "ready" && <ReleaseDownloads release={state.release} />}
          </section>

          <div className="mt-12 rounded-md border border-slate-100 bg-white p-5">
            <div className="flex items-center gap-2 text-2xs font-medium uppercase tracking-wider text-slate-400">
              <ShieldCheck className="h-3.5 w-3.5" />
              Existing SaaS dashboard
            </div>
            <p className="mt-2 text-sm text-slate-600">
              Your old web dashboard keeps working during the transition.
              The desktop app is the way forward — your dashboard data and
              audit log stay accessible while you migrate.
            </p>
            <div className="mt-3 flex gap-3">
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

function AnonymousCta() {
  return (
    <div className="rounded-md border border-slate-100 bg-white p-6">
      <h2 className="font-display text-lg font-bold tracking-tight">
        Sign in to download
      </h2>
      <p className="mt-2 text-sm text-slate-600">
        Your installer download is gated by your license. If you already
        have a license, sign in to download. If not, pick a plan first.
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <Link
          href="/sign-in?next=/download"
          className="inline-flex items-center gap-2 rounded-md bg-ink px-4 py-2 text-2xs font-medium text-paper hover:bg-slate-800"
        >
          Sign in
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
        <Link
          href="/pricing"
          className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-4 py-2 text-2xs font-medium text-ink hover:border-ink"
        >
          See pricing
        </Link>
      </div>
    </div>
  );
}

function NoLicenseCta() {
  return (
    <div className="rounded-md border border-warning/30 bg-warning/5 p-6">
      <h2 className="font-display text-lg font-bold tracking-tight">
        You don&apos;t have an active license yet.
      </h2>
      <p className="mt-2 text-sm text-slate-600">
        Once you buy a license, the installer becomes available here
        immediately. Annual price covers one Malaysian company (one
        LHDN TIN).
      </p>
      <div className="mt-4">
        <Link
          href="/pricing"
          className="inline-flex items-center gap-2 rounded-md bg-ink px-4 py-2 text-2xs font-medium text-paper hover:bg-slate-800"
        >
          Buy a license
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  );
}

function ReleaseDownloads({ release }: { release: ReleaseInfo }) {
  return (
    <div>
      <h2 className="font-display text-lg font-bold tracking-tight">
        Latest release · v{release.version}
      </h2>
      <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
        Channel {release.channel} · links expire in {Math.round(release.expires_in_seconds / 60)}{" "}
        min
      </p>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <PlatformCard
          icon={<Monitor className="h-4 w-4" />}
          label="Windows"
          asset={release.platforms.windows}
          primary
        />
        <PlatformCard
          icon={<Apple className="h-4 w-4" />}
          label="macOS"
          asset={release.platforms.mac}
        />
        <PlatformCard
          icon={<Download className="h-4 w-4" />}
          label="Linux"
          asset={release.platforms.linux}
        />
      </div>
      <p className="mt-4 text-2xs text-slate-500">
        After installing, paste your license key on first launch.{" "}
        <Link
          href="/dashboard/settings"
          className="font-medium text-ink underline-offset-4 hover:underline"
        >
          View your keys
        </Link>
        .
      </p>
    </div>
  );
}

function PlatformCard({
  icon,
  label,
  asset,
  primary = false,
}: {
  icon: React.ReactNode;
  label: string;
  asset: { url: string; filename: string };
  primary?: boolean;
}) {
  return (
    <a
      href={asset.url}
      className={[
        "flex flex-col gap-2 rounded-md border p-4 transition-colors",
        primary
          ? "border-ink bg-ink text-paper hover:bg-slate-800"
          : "border-slate-200 bg-white text-ink hover:border-ink",
      ].join(" ")}
    >
      <div className="flex items-center gap-2 text-2xs font-medium uppercase tracking-wider opacity-80">
        {icon}
        {label}
      </div>
      <div className="text-sm font-semibold">Download installer</div>
      <div className="text-2xs opacity-70 break-all">{asset.filename}</div>
    </a>
  );
}
