"use client";

// Phase 3 of PORTAL_PLAN.md — Auto-submit Settings panel.
//
// Two settings:
//   - auto_submit_default: master toggle. When ON, ZeroKey signs and
//     submits ERP-pulled invoices to LHDN without a manual click,
//     subject to validation + confidence + per-customer override.
//   - auto_submit_confidence_threshold: 0-1. Anything below falls
//     back to the Not Submitted queue regardless of the toggle.
//
// Per-customer overrides ("always submit to buyer X, hold-for-review
// buyer Y") are managed on the Customer detail page — surfaced from
// here as a link.

import { useEffect, useState } from "react";
import { Bot, Loader2, ShieldAlert } from "lucide-react";

import { api, ApiError } from "@/lib/api";

type State = Awaited<ReturnType<typeof api.getAutoSubmit>>;

export function AutoSubmitCard() {
  const [state, setState] = useState<State | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Threshold is edited as a string so the user can type "0.95" without
  // the slider snapping back to a stale parsed value.
  const [thresholdInput, setThresholdInput] = useState("0.92");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getAutoSubmit()
      .then((r) => {
        if (!cancelled) {
          setState(r);
          setThresholdInput(String(r.auto_submit_confidence_threshold));
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Failed to load auto-submit settings.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function patch(body: {
    auto_submit_default?: boolean;
    auto_submit_confidence_threshold?: number;
  }) {
    setBusy(true);
    setError(null);
    try {
      const r = await api.updateAutoSubmit(body);
      setState(r);
      setThresholdInput(String(r.auto_submit_confidence_threshold));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update auto-submit.");
    } finally {
      setBusy(false);
    }
  }

  function commitThreshold() {
    const parsed = Number(thresholdInput);
    if (Number.isNaN(parsed) || parsed < 0 || parsed > 1) {
      setError("Threshold must be a number between 0 and 1.");
      return;
    }
    if (state && parsed === state.auto_submit_confidence_threshold) return;
    void patch({ auto_submit_confidence_threshold: parsed });
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-white p-4 text-2xs text-slate-500">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading auto-submit settings…
      </div>
    );
  }

  if (!state) {
    return (
      <div className="rounded-md border border-error/30 bg-error/5 p-4 text-2xs text-error">
        {error || "Couldn't load auto-submit settings."}
      </div>
    );
  }

  const enabled = state.auto_submit_default;

  return (
    <div className="grid gap-4">
      {/* Master toggle */}
      <div className="flex flex-col gap-3 rounded-md border border-slate-200 bg-white p-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-start gap-3">
          <span
            className={`grid h-9 w-9 shrink-0 place-items-center rounded-md ${enabled ? "bg-success/10 text-success" : "bg-ink/5 text-ink"}`}
          >
            <Bot size={18} />
          </span>
          <div>
            <div className="text-sm font-semibold text-ink">
              {enabled
                ? "Auto-submit is ON"
                : "Auto-submit is OFF"}
            </div>
            <p className="mt-1 max-w-md text-2xs text-slate-500">
              {enabled
                ? "New invoices that pass validation and the extraction-confidence gate are signed and sent to LHDN automatically. Anything that fails a gate lands in Not Submitted for you to review."
                : "Every new invoice lands in Not Submitted. You click Submit when you're ready. Turn this on once you trust the pipeline."}
            </p>
          </div>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void patch({ auto_submit_default: !enabled })}
          className={`shrink-0 rounded-md px-3 py-1.5 text-2xs font-medium transition-colors ${
            enabled
              ? "border border-slate-200 bg-white text-slate-600 hover:text-ink"
              : "bg-ink text-paper hover:bg-slate-800"
          } disabled:cursor-not-allowed disabled:opacity-50`}
        >
          {busy ? "Saving…" : enabled ? "Turn off" : "Turn on auto-submit"}
        </button>
      </div>

      {/* Threshold */}
      <div className="rounded-md border border-slate-100 bg-slate-50 p-4">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
          <div className="flex-1">
            <div className="text-sm font-semibold text-ink">Confidence threshold</div>
            <p className="mt-1 text-2xs text-slate-500">
              Invoices below this extraction-confidence score fall back to the Not Submitted
              queue, even when the master toggle is on. 0.92 is the launch default — raise it for
              tighter control, lower for more aggressive auto-submission.
            </p>
            <div className="mt-3 flex items-center gap-2">
              <input
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={thresholdInput}
                onChange={(e) => setThresholdInput(e.target.value)}
                onBlur={commitThreshold}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    commitThreshold();
                  }
                }}
                disabled={busy}
                className="w-24 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-ink focus:border-ink focus:outline-none focus:ring-1 focus:ring-ink disabled:cursor-not-allowed disabled:opacity-60"
              />
              <span className="text-2xs text-slate-400">currently {state.auto_submit_confidence_threshold}</span>
            </div>
          </div>
        </div>
      </div>

      <p className="text-2xs text-slate-400">
        Want to override per-buyer (always auto-submit buyer X, always review buyer Y)? Open a
        customer record from Customers and set the override on the row.
      </p>

      {error && (
        <div role="alert" className="rounded-md border border-error/30 bg-error/5 px-3 py-2 text-2xs text-error">
          {error}
        </div>
      )}
    </div>
  );
}
