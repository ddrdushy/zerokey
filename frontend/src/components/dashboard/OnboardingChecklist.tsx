"use client";

// Post-signup onboarding checklist (Slice 92).
//
// A single dismissible card on the dashboard showing the new owner
// what they need to configure to get value from ZeroKey, *why* each
// item matters, and *where* to find it. Items derive their done-state
// from real data (cert uploaded, inbox token configured, IngestionJob
// exists, etc.) so a user who completed a step before clicking the
// checklist sees it pre-checked.
//
// Why a checklist not a multi-step tour: a checklist persists as a
// reference until dismissed — users come back to it when they're
// ready to configure the next thing. A tour fires once and is gone.
// Per UX_PRINCIPLES principle 3 ("nothing happens silently"), the
// "where" link points at the configuration surface, not a popover.

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Circle, X } from "lucide-react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type Step = {
  key: string;
  title: string;
  why: string;
  where: string;
  done: boolean;
};

export function OnboardingChecklist() {
  const [steps, setSteps] = useState<Step[] | null>(null);
  const [dismissed, setDismissed] = useState<boolean>(false);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  useEffect(() => {
    api
      .getOnboarding()
      .then((data) => {
        setSteps(data.steps);
        setDismissed(data.dismissed_at != null);
      })
      .catch(() => {
        // Non-fatal — the checklist just won't render. Don't block
        // the rest of the dashboard.
      });
  }, []);

  if (steps == null || dismissed) return null;

  const completed = steps.filter((s) => s.done).length;
  const total = steps.length;

  async function onDismiss() {
    setDismissed(true); // optimistic
    api.dismissOnboarding().catch(() => {
      // If dismiss fails server-side, still hide locally — they
      // told us they're done. Server will catch up next time.
    });
  }

  return (
    <section className="relative overflow-hidden rounded-2xl border border-signal/40 bg-signal/5 p-6 md:p-8">
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss onboarding checklist"
        className="absolute right-4 top-4 grid h-8 w-8 place-items-center rounded-md text-slate-500 hover:bg-white/60 hover:text-ink"
      >
        <X className="h-4 w-4" />
      </button>

      <div className="mb-4 flex flex-col gap-1">
        <div className="text-2xs font-medium uppercase tracking-wider text-slate-500">
          Get started · {completed} of {total} done
        </div>
        <h2 className="font-display text-xl font-bold tracking-tight md:text-2xl">
          Configure ZeroKey for your business.
        </h2>
        <p className="text-sm text-slate-600">
          Five things to set up before your first real submission. Each step
          links to the page you need.
        </p>
      </div>

      <ol className="flex flex-col gap-1">
        {steps.map((step) => {
          const isExpanded = expandedKey === step.key;
          return (
            <li key={step.key}>
              <div
                className={cn(
                  "rounded-lg border bg-white px-4 py-3 transition-colors",
                  step.done ? "border-success/30" : "border-slate-200",
                )}
              >
                <button
                  type="button"
                  onClick={() => setExpandedKey(isExpanded ? null : step.key)}
                  className="flex w-full items-center gap-3 text-left"
                >
                  {step.done ? (
                    <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-success" />
                  ) : (
                    <Circle className="h-5 w-5 flex-shrink-0 text-slate-300" />
                  )}
                  <span
                    className={cn(
                      "flex-1 text-sm font-medium",
                      step.done ? "text-slate-500 line-through decoration-slate-300" : "text-ink",
                    )}
                  >
                    {step.title}
                  </span>
                  <span className="text-2xs uppercase tracking-wider text-slate-400">
                    {isExpanded ? "Hide" : "Why"}
                  </span>
                </button>
                {isExpanded && (
                  <div className="mt-3 flex flex-col gap-3 pl-8 text-sm text-slate-600">
                    <p>{step.why}</p>
                    {!step.done && (
                      <Link
                        href={step.where}
                        className="self-start rounded-md bg-ink px-3 py-1.5 text-2xs font-medium uppercase tracking-wider text-paper hover:bg-ink/90"
                      >
                        Take me there
                      </Link>
                    )}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
