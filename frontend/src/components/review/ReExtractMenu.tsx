"use client";

// Slice 106 — re-run extraction with a customer-chosen engine.
//
// The engine that picked first time isn't always the best fit
// (a low-confidence native PDF might be better as Claude vision;
// a scanned PDF where pdfplumber returned empty text might want
// RapidOCR). This menu lets the user pick a different engine and
// re-run end-to-end. The action overwrites the current invoice
// fields including any manual edits — we surface that in the
// confirm dialog so it isn't a surprise.

import { useEffect, useState } from "react";
import { ChevronDown, RotateCcw } from "lucide-react";

import {
  api,
  ApiError,
  type ExtractionEngineOption,
  type IngestionJob,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function ReExtractMenu({
  job,
  onComplete,
}: {
  job: IngestionJob;
  /** Called with the updated job when re-extraction returns. The
   *  parent typically swaps in the new job + refetches the invoice. */
  onComplete: (next: IngestionJob) => void;
}) {
  const [open, setOpen] = useState(false);
  const [engines, setEngines] = useState<ExtractionEngineOption[] | null>(null);
  const [pending, setPending] = useState<string | null>(null); // engine slug being run
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ExtractionEngineOption | null>(null);

  useEffect(() => {
    if (!open || engines !== null) return;
    api
      .listExtractionEngines()
      .then(setEngines)
      .catch((err) => {
        setEngines([]);
        setError(err instanceof Error ? err.message : "Failed to load engines.");
      });
  }, [open, engines]);

  async function onRun(slug: string) {
    setPending(slug);
    setError(null);
    try {
      const updated = await api.reExtractJob(job.id, slug);
      onComplete(updated);
      setOpen(false);
      setConfirm(null);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Re-extraction failed.");
      }
    } finally {
      setPending(null);
    }
  }

  // Hide the control if the job hasn't finished its first run
  // yet — re-extracting an in-flight job is racy.
  const RE_EXTRACTABLE = new Set([
    "ready_for_review",
    "awaiting_approval",
    "validated",
    "rejected",
    "cancelled",
    "error",
  ]);
  if (!RE_EXTRACTABLE.has(job.status)) return null;

  return (
    <div className="relative">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen((v) => !v)}
        disabled={pending !== null}
      >
        <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
        {pending ? `Re-extracting with ${pending}…` : "Re-extract"}
        <ChevronDown className="ml-1 h-3 w-3" />
      </Button>

      {open && (
        <div className="absolute right-0 top-full z-30 mt-2 w-72 rounded-xl border border-slate-100 bg-white p-2 shadow-md">
          <div className="px-3 pb-1 pt-2 text-2xs font-semibold uppercase tracking-wider text-slate-400">
            Try a different engine
          </div>
          {error && (
            <div className="mx-2 my-2 rounded-md border border-error bg-error/5 px-3 py-2 text-2xs text-error">
              {error}
            </div>
          )}
          {engines === null ? (
            <div className="px-3 py-3 text-2xs text-slate-400">Loading engines…</div>
          ) : engines.length === 0 ? (
            <div className="px-3 py-3 text-2xs text-slate-400">
              No alternative engines available.
            </div>
          ) : (
            <ul className="flex flex-col">
              {engines.map((engine) => {
                const isCurrent = engine.slug === job.extraction_engine;
                return (
                  <li key={engine.slug}>
                    <button
                      type="button"
                      onClick={() => setConfirm(engine)}
                      disabled={isCurrent || pending !== null}
                      className={cn(
                        "flex w-full items-start gap-2 rounded-md px-3 py-2 text-left text-2xs hover:bg-slate-50",
                        isCurrent && "cursor-not-allowed opacity-50 hover:bg-transparent",
                      )}
                      title={isCurrent ? "Already used for the current run" : undefined}
                    >
                      <div className="flex-1">
                        <div className="font-medium text-ink">{engine.label}</div>
                        <div className="mt-0.5 text-[10px] uppercase tracking-wider text-slate-400">
                          {engine.capability.replace(/_/g, " ")} · {engine.vendor}
                        </div>
                      </div>
                      {isCurrent && (
                        <span className="text-[10px] uppercase tracking-wider text-success">
                          current
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      {confirm && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="w-full max-w-md rounded-xl border border-slate-100 bg-white p-6 shadow-lg">
            <h3 className="font-display text-lg font-semibold">
              Re-extract with {confirm.label}?
            </h3>
            <p className="mt-2 text-2xs text-slate-500">
              This replaces the current extracted text and structured fields,
              including any manual edits you have made on this invoice. The
              audit log records the swap.
            </p>
            <div className="mt-5 flex items-center justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setConfirm(null)}
                disabled={pending !== null}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={() => onRun(confirm.slug)}
                disabled={pending !== null}
              >
                {pending ? "Re-extracting…" : `Use ${confirm.label}`}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
