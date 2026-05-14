"use client";

// Phase 1 of PORTAL_PLAN.md — Signing-mode panel for the Settings page.
//
// Two states the customer can be in:
//
//   - **Intermediary** (the new default). Symprio signs on the
//     customer's behalf. No customer-side certificate dance. The
//     panel surfaces the Symprio cert details and a "you've accepted
//     the intermediary terms on <date>" line. If they haven't
//     accepted yet (existing pre-Phase-1 tenants migrating in), the
//     panel renders a consent checkbox + "Use Symprio as my
//     intermediary" button.
//
//   - **Self-signed**. The org owns its own cert (uploaded or
//     dev-generated). Existing cert UI handles upload + rotation;
//     this panel just exposes a "switch back to intermediary" link.

import { useEffect, useState } from "react";
import { CheckCircle2, KeySquare, Loader2, ShieldCheck } from "lucide-react";

import { api, ApiError } from "@/lib/api";

type SigningModeResponse = Awaited<ReturnType<typeof api.getSigningMode>>;

export function SigningModeCard() {
  const [state, setState] = useState<SigningModeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [consentChecked, setConsentChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getSigningMode()
      .then((r) => {
        if (!cancelled) setState(r);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Failed to load signing mode.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function switchTo(mode: "intermediary" | "self_signed") {
    setBusy(true);
    setError(null);
    try {
      const r = await api.updateSigningMode(mode, mode === "intermediary" ? consentChecked : false);
      setState(r);
      setConsentChecked(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update signing mode.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-white p-4 text-2xs text-slate-500">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading signing mode…
      </div>
    );
  }

  if (!state) {
    return (
      <div className="rounded-md border border-error/30 bg-error/5 p-4 text-2xs text-error">
        {error || "Couldn't load signing mode."}
      </div>
    );
  }

  const isIntermediary = state.signing_mode === "intermediary";
  const consentPending = isIntermediary && state.intermediary_consent_at === null;
  const cert = state.intermediary_cert;

  return (
    <div className="grid gap-4">
      {/* Mode badge + toggle */}
      <div className="flex flex-col gap-3 rounded-md border border-slate-200 bg-white p-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-start gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-ink/5 text-ink">
            {isIntermediary ? <ShieldCheck size={18} /> : <KeySquare size={18} />}
          </span>
          <div>
            <div className="text-sm font-semibold text-ink">
              {isIntermediary
                ? "Symprio signs on your behalf"
                : "You sign with your own certificate"}
            </div>
            <p className="mt-1 max-w-md text-2xs text-slate-500">
              {isIntermediary
                ? "Symprio Sdn Bhd is registered with LHDN as a software intermediary. The TIN on each invoice is yours; the signing material is ours."
                : "Your LHDN-issued certificate signs every submission. You manage rotation and expiry."}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {!isIntermediary ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setConsentChecked(true);
                void switchTo("intermediary");
              }}
              className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs font-medium text-ink hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "Switching…" : "Use intermediary"}
            </button>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() => void switchTo("self_signed")}
              className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs font-medium text-slate-600 hover:bg-slate-50 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "Switching…" : "I'll bring my own cert"}
            </button>
          )}
        </div>
      </div>

      {/* Consent prompt — shown for intermediary orgs that migrated in
          from pre-Phase-1 without having explicitly accepted. */}
      {consentPending && (
        <div className="rounded-md border border-warning/40 bg-warning/5 p-4">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <div className="flex-1">
              <div className="text-sm font-semibold text-ink">Confirm intermediary consent</div>
              <p className="mt-1 text-2xs text-slate-600">
                You haven&apos;t formally accepted the intermediary terms yet. Symprio will not sign
                on your behalf until you do. By accepting, you authorise Symprio Sdn Bhd to sign
                LHDN MyInvois submissions for this organisation as a registered software
                intermediary.
              </p>
              <label className="mt-3 flex items-center gap-2 text-2xs text-ink">
                <input
                  type="checkbox"
                  checked={consentChecked}
                  onChange={(e) => setConsentChecked(e.target.checked)}
                  className="h-3.5 w-3.5"
                />
                I authorise Symprio to sign on my behalf as my LHDN intermediary.
              </label>
              <button
                type="button"
                onClick={() => void switchTo("intermediary")}
                disabled={busy || !consentChecked}
                className="mt-3 inline-flex items-center justify-center rounded-md bg-ink px-4 py-1.5 text-2xs font-medium text-paper hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? "Saving…" : "Accept intermediary terms"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Intermediary cert details — surfaces what's actually
          signing the submissions when in intermediary mode. */}
      {isIntermediary && !consentPending && (
        <div className="rounded-md border border-slate-100 bg-slate-50 p-4">
          <div className="text-2xs font-semibold uppercase tracking-wider text-slate-500">
            Intermediary certificate (Symprio)
          </div>
          <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1.5 text-2xs text-slate-600 md:grid-cols-2">
            <div className="flex justify-between gap-3">
              <dt className="text-slate-400">Subject</dt>
              <dd className="text-right text-ink">{cert.subject_common_name || "—"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-slate-400">Serial</dt>
              <dd className="truncate text-right font-mono text-ink">{cert.serial_hex || "—"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-slate-400">Expires</dt>
              <dd className="text-right text-ink">
                {cert.expires_at
                  ? new Date(cert.expires_at).toLocaleDateString()
                  : "—"}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-slate-400">LHDN registration</dt>
              <dd className="text-right font-mono text-ink">
                {cert.lhdn_registration_number || "—"}
              </dd>
            </div>
          </dl>
          {state.intermediary_consent_at && (
            <p className="mt-3 border-t border-slate-200 pt-2 text-2xs text-slate-500">
              You accepted the intermediary terms on{" "}
              {new Date(state.intermediary_consent_at).toLocaleString()}.
            </p>
          )}
        </div>
      )}

      {error && (
        <div role="alert" className="rounded-md border border-error/30 bg-error/5 px-3 py-2 text-2xs text-error">
          {error}
        </div>
      )}
    </div>
  );
}
