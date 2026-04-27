// Section 4 — How it works. Four-step visual flow. Captions are scannable in
// ~20 seconds.

const STEPS = [
  {
    n: "01",
    title: "Drop your invoice.",
    body: "Web upload, email forward, WhatsApp, or API. Whatever format your suppliers use.",
  },
  {
    n: "02",
    title: "We extract and validate.",
    body: "AI extracts the 55 LHDN fields with confidence scores and catches errors before LHDN does.",
  },
  {
    n: "03",
    title: "Review and approve.",
    body: "Original document side-by-side with extracted fields. Every change is logged.",
  },
  {
    n: "04",
    title: "Submitted to LHDN.",
    body: "We sign with your certificate, submit to MyInvois, and return the UUID and QR code.",
  },
];

export function HowItWorks() {
  return (
    <section className="border-b border-slate-100">
      <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
        <div className="max-w-2xl">
          <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
            From a PDF to a validated LHDN submission, <em>without typing</em>.
          </h2>
        </div>
        <ol className="mt-12 grid gap-8 md:grid-cols-4">
          {STEPS.map((step) => (
            <li key={step.n} className="flex flex-col gap-3">
              <span className="font-display text-lg font-bold text-slate-400">{step.n}</span>
              <h3 className="text-xl font-semibold">{step.title}</h3>
              <p className="text-base text-slate-600">{step.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
