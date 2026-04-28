import { Button } from "@/components/ui/button";

// Hero card analogue of the Vuexy "Congratulations" tile, on-brand.
// Calm tone, italics device on the value phrase per VISUAL_IDENTITY.md.

export function HeroCard({
  firstName,
  organizationName,
  validatedThisMonth,
}: {
  firstName: string;
  organizationName: string;
  validatedThisMonth: number;
}) {
  return (
    <section className="relative overflow-hidden rounded-2xl border border-slate-100 bg-white p-6 md:p-8">
      <div className="grid gap-6 md:grid-cols-[1fr_auto] md:items-center">
        <div className="flex flex-col gap-3">
          <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">
            {organizationName} · this month
          </div>
          <h2 className="font-display text-2xl font-bold leading-tight tracking-tight md:text-3xl">
            Welcome back, {firstName}.{" "}
            <em className="not-italic text-slate-600">Drop a file when you&apos;re ready.</em>
          </h2>
          <p className="max-w-xl text-base text-slate-600">
            {validatedThisMonth > 0
              ? `${validatedThisMonth} invoice${validatedThisMonth === 1 ? "" : "s"} validated by LHDN this month.`
              : "No invoices submitted yet — drop your first one below to get started."}
          </p>
          <div className="mt-2 flex flex-wrap gap-3">
            <Button variant="signal" size="md">
              Drop an invoice
            </Button>
            <Button variant="outline" size="md">
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
// aspect, slightly more rounded top. Used here as the hero anchor instead
// of the Vuexy mascot illustration.
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
