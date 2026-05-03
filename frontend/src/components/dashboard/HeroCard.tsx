"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";

// Hero card analogue of the Vuexy "Congratulations" tile, on-brand.
// Calm tone, italics device on the value phrase per VISUAL_IDENTITY.md.
//
// The DropZone renders directly below this on the dashboard — so the
// hero deliberately doesn't carry its own "Drop an invoice" button.
// One CTA per row of attention; the dropzone is the action.

export function HeroCard({
  organizationName,
  validatedThisMonth,
  totalUploads = 0,
  needsReview = 0,
}: {
  organizationName: string;
  validatedThisMonth: number;
  /** Slice 102 — total upload count so the empty-state copy doesn't lie when the user has uploads in flight. */
  totalUploads?: number;
  needsReview?: number;
}) {
  const router = useRouter();

  // Three-state copy ladder — read the actual upload state, not just
  // LHDN-validated counts. The pre-Slice-102 single-branch copy lied
  // to users who had uploaded but not yet completed the cert+submit
  // flow, telling them "no invoices yet" while the dashboard stats
  // showed 11 in flight.
  let summary: string;
  if (validatedThisMonth > 0) {
    summary = `${validatedThisMonth} invoice${
      validatedThisMonth === 1 ? "" : "s"
    } validated by LHDN this month.`;
  } else if (needsReview > 0) {
    summary = `${needsReview} invoice${
      needsReview === 1 ? "" : "s"
    } waiting for review. Open the inbox to clear them.`;
  } else if (totalUploads > 0) {
    summary = `${totalUploads} upload${
      totalUploads === 1 ? "" : "s"
    } in flight. Set up LHDN signing in Settings to start validating.`;
  } else {
    summary = "No invoices submitted yet — drop your first one below to get started.";
  }

  return (
    <section className="relative overflow-hidden rounded-2xl border border-slate-100 bg-white p-6 md:p-8">
      <div className="grid gap-6 md:grid-cols-[1fr_auto] md:items-center">
        <div className="flex flex-col gap-3">
          <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">
            {organizationName} · this month
          </div>
          <h2 className="font-display text-2xl font-bold leading-tight tracking-tight md:text-3xl">
            Welcome back.{" "}
            <em className="not-italic text-slate-600">Drop a file when you&apos;re ready.</em>
          </h2>
          <p className="max-w-xl text-base text-slate-600">{summary}</p>
          <div className="mt-2 flex flex-wrap gap-3">
            <Button variant="outline" size="md" onClick={() => router.push("/dashboard/audit")}>
              View audit log
            </Button>
          </div>
        </div>
        <DropMotif />
      </div>
    </section>
  );
}

// The "drop" motif from VISUAL_IDENTITY.md — softly rounded square, 4:5
// aspect, slightly more rounded top. Decorative brand element; the
// actual upload UI is the DropZone directly below the hero.
function DropMotif() {
  return (
    <div
      aria-hidden="true"
      className="relative hidden h-40 w-32 md:block"
      style={{
        background: "linear-gradient(180deg, #C7F284 0%, #FAFAF7 100%)",
        borderRadius: "30% 30% 14% 14% / 18% 18% 14% 14%",
        boxShadow: "0 20px 40px -20px rgba(10,14,26,0.15)",
      }}
    >
      <div className="absolute inset-0 grid place-items-center">
        <div className="text-center">
          <div className="font-display text-3xl font-bold text-ink">⬇</div>
          <div className="mt-1 text-2xs uppercase tracking-wider text-ink/60">drop here</div>
        </div>
      </div>
    </div>
  );
}
