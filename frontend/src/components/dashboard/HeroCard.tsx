"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";

// Hero card analogue of the Vuexy "Congratulations" tile, on-brand.
// Calm tone, italics device on the value phrase per VISUAL_IDENTITY.md.

export function HeroCard({
  organizationName,
  validatedThisMonth,
}: {
  organizationName: string;
  validatedThisMonth: number;
}) {
  const router = useRouter();

  function scrollToDropzone() {
    // The DropZone always renders below the hero on the dashboard.
    // Scrolling beats a brittle imperative file-picker open: the user
    // sees both the drag affordance and the "click to browse" link.
    const target = document.querySelector('[data-dropzone="invoice"]');
    if (target instanceof HTMLElement) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      // A short visual pulse so the user knows where to drop.
      target.classList.add("ring-2", "ring-signal");
      setTimeout(() => target.classList.remove("ring-2", "ring-signal"), 1500);
    }
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
          <p className="max-w-xl text-base text-slate-600">
            {validatedThisMonth > 0
              ? `${validatedThisMonth} invoice${validatedThisMonth === 1 ? "" : "s"} validated by LHDN this month.`
              : "No invoices submitted yet — drop your first one below to get started."}
          </p>
          <div className="mt-2 flex flex-wrap gap-3">
            <Button variant="signal" size="md" onClick={scrollToDropzone}>
              Drop an invoice
            </Button>
            <Button variant="outline" size="md" onClick={() => router.push("/dashboard/audit")}>
              View audit log
            </Button>
          </div>
        </div>
        <DropMotif onClick={scrollToDropzone} />
      </div>
    </section>
  );
}

// The "drop" motif from VISUAL_IDENTITY.md — softly rounded square, 4:5
// aspect, slightly more rounded top. Used here as the hero anchor instead
// of the Vuexy mascot illustration.
function DropMotif({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Jump to upload"
      className="relative hidden h-40 w-32 transition-transform hover:scale-105 md:block"
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
    </button>
  );
}
