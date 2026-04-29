"use client";

// Slice 59B — LHDN submission panel for the invoice review screen.
//
// One panel that surfaces the entire LHDN lifecycle:
//
//   - Pre-submit (status ready_for_review / awaiting_approval):
//       "Submit to LHDN" button. Disabled if there are validation
//       issues open or required fields missing.
//   - In flight (status submitting):
//       Spinner + "Refresh status" button + auto-poll every ~5s.
//   - Validated (status validated):
//       UUID, validation timestamp, QR/verify link, "Cancel" button
//       (only inside the 72-hour window).
//   - Rejected (status rejected):
//       LHDN's error message verbatim + retry button.
//   - Cancelled (status cancelled):
//       Cancellation timestamp, "Past 72-hour window — issue a
//       credit note for further changes" hint.

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  FileMinus,
  FilePlus,
  Loader2,
  RotateCcw,
  Send,
  Shield,
  ShieldOff,
  X,
} from "lucide-react";

import { api, ApiError, type Invoice } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type AmendmentType = "credit_note" | "debit_note" | "refund_note";

const AMENDMENT_COPY: Record<
  AmendmentType,
  {
    title: string;
    blurb: string;
    placeholder: string;
    confirmLabel: string;
    busyLabel: string;
  }
> = {
  credit_note: {
    title: "Issue a credit note?",
    blurb:
      "A credit note credits or refunds value from the original invoice. Common case: customer returned goods, refund issued, or post-issue discount applied.",
    placeholder: "e.g. customer returned 2 units, refund due",
    confirmLabel: "Create credit note",
    busyLabel: "Creating credit note…",
  },
  debit_note: {
    title: "Issue a debit note?",
    blurb:
      "A debit note adds value to the original invoice. Common case: late-payment penalty, additional charge billed after issue, freight surcharge.",
    placeholder: "e.g. 5% late-payment penalty for invoice paid 14 days late",
    confirmLabel: "Create debit note",
    busyLabel: "Creating debit note…",
  },
  refund_note: {
    title: "Issue a refund note?",
    blurb:
      "A refund note documents that a refund payment has actually been made to the buyer. Distinct from a credit note (which adjusts the receivable).",
    placeholder: "e.g. RM 30 refunded via FPX on 29-Apr-2026",
    confirmLabel: "Create refund note",
    busyLabel: "Creating refund note…",
  },
};

type Phase =
  | "preflight"      // not yet submitted
  | "in_flight"      // submitted, waiting for LHDN to validate
  | "validated"      // LHDN accepted
  | "rejected"       // LHDN rejected
  | "cancelled"      // we cancelled it
  | "error";         // local pipeline error

function phaseFor(invoice: Invoice): Phase {
  switch (invoice.status) {
    case "submitting":
      return "in_flight";
    case "validated":
      return "validated";
    case "rejected":
      return "rejected";
    case "cancelled":
      return "cancelled";
    case "error":
      return "error";
    default:
      return "preflight";
  }
}

function withinCancelWindow(invoice: Invoice): boolean {
  if (!invoice.validation_timestamp) return false;
  const validatedAt = new Date(invoice.validation_timestamp).getTime();
  const seventyTwoHoursMs = 72 * 60 * 60 * 1000;
  return Date.now() - validatedAt < seventyTwoHoursMs;
}

export function LhdnPanel({
  invoice,
  onInvoiceChanged,
  blockingIssues,
}: {
  invoice: Invoice;
  onInvoiceChanged: (next: Invoice) => void;
  blockingIssues: number;
}) {
  const router = useRouter();
  const phase = useMemo(() => phaseFor(invoice), [invoice]);
  const [busy, setBusy] = useState<
    "submit" | "cancel" | "poll" | "amendment" | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [amendmentType, setAmendmentType] = useState<AmendmentType | null>(null);
  const [amendmentReason, setAmendmentReason] = useState("");

  // Auto-poll while in flight. Light cadence (5s) so the user
  // sees updates without the FE pummeling the worker. The server-
  // side worker also polls in the background per spec §4.2.
  useEffect(() => {
    if (phase !== "in_flight") return;
    const interval = setInterval(async () => {
      try {
        const result = await api.pollInvoiceLhdn(invoice.id);
        onInvoiceChanged(result.invoice);
      } catch {
        // Swallow — the manual button is always available.
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [phase, invoice.id, onInvoiceChanged]);

  async function onSubmit() {
    setBusy("submit");
    setError(null);
    try {
      const result = await api.submitInvoiceToLhdn(invoice.id);
      onInvoiceChanged(result.invoice);
      if (!result.ok && result.reason) {
        setError(result.reason);
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Submission failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function onPoll() {
    setBusy("poll");
    setError(null);
    try {
      const result = await api.pollInvoiceLhdn(invoice.id);
      onInvoiceChanged(result.invoice);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed.");
    } finally {
      setBusy(null);
    }
  }

  async function onConfirmCancel() {
    if (!cancelReason.trim()) return;
    setBusy("cancel");
    setError(null);
    try {
      const result = await api.cancelInvoiceLhdn(invoice.id, cancelReason.trim());
      onInvoiceChanged(result.invoice);
      if (!result.ok) {
        setError(result.reason);
      } else {
        setCancelOpen(false);
        setCancelReason("");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancellation failed.");
    } finally {
      setBusy(null);
    }
  }

  async function onConfirmAmendment() {
    if (!amendmentType || !amendmentReason.trim()) return;
    setBusy("amendment");
    setError(null);
    const issuer = {
      credit_note: api.issueCreditNote,
      debit_note: api.issueDebitNote,
      refund_note: api.issueRefundNote,
    }[amendmentType];
    try {
      const result = await issuer(invoice.id, amendmentReason.trim());
      // Navigate to the new amendment's review page so the user can
      // tweak amounts before submitting it to LHDN.
      router.push(`/dashboard/jobs/${result.ingestion_job_id}`);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : `Failed to create ${amendmentType.replace("_", " ")}.`,
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <header className="flex flex-wrap items-baseline justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-2">
          <h3 className="text-base font-semibold">LHDN MyInvois</h3>
          <PhaseBadge phase={phase} />
        </div>
        {phase === "validated" && invoice.lhdn_qr_code_url ? (
          <a
            href={invoice.lhdn_qr_code_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-2xs font-medium text-ink hover:underline"
          >
            View on MyInvois
            <ExternalLink className="h-3 w-3" />
          </a>
        ) : null}
      </header>

      <div className="flex flex-col gap-3 px-5 py-4">
        {phase === "preflight" && (
          <PreflightView
            invoice={invoice}
            blockingIssues={blockingIssues}
            busy={busy === "submit"}
            onSubmit={onSubmit}
          />
        )}
        {phase === "in_flight" && (
          <InFlightView
            invoice={invoice}
            busy={busy === "poll"}
            onPoll={onPoll}
          />
        )}
        {phase === "validated" && (
          <ValidatedView
            invoice={invoice}
            canCancel={withinCancelWindow(invoice)}
            onCancelOpen={() => setCancelOpen(true)}
            onAmendmentOpen={(t) => setAmendmentType(t)}
            onPoll={onPoll}
            polling={busy === "poll"}
          />
        )}
        {phase === "rejected" && (
          <RejectedView
            invoice={invoice}
            busy={busy === "submit"}
            onRetry={onSubmit}
          />
        )}
        {phase === "cancelled" && <CancelledView invoice={invoice} />}
        {phase === "error" && <ErrorView invoice={invoice} />}

        {error && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-error/30 bg-error/5 px-3 py-2 text-2xs text-error"
          >
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}
      </div>

      {cancelOpen && (
        <CancelDialog
          reason={cancelReason}
          onChangeReason={setCancelReason}
          onConfirm={onConfirmCancel}
          onClose={() => {
            setCancelOpen(false);
            setCancelReason("");
            setError(null);
          }}
          busy={busy === "cancel"}
        />
      )}
      {amendmentType !== null && (
        <AmendmentDialog
          type={amendmentType}
          reason={amendmentReason}
          onChangeReason={setAmendmentReason}
          onConfirm={onConfirmAmendment}
          onClose={() => {
            setAmendmentType(null);
            setAmendmentReason("");
            setError(null);
          }}
          busy={busy === "amendment"}
        />
      )}
    </section>
  );
}

function PhaseBadge({ phase }: { phase: Phase }) {
  const map: Record<Phase, { label: string; tone: string }> = {
    preflight: { label: "Ready to submit", tone: "bg-slate-100 text-slate-500" },
    in_flight: { label: "Submitting", tone: "bg-warning/15 text-warning" },
    validated: { label: "Validated", tone: "bg-success/15 text-success" },
    rejected: { label: "Rejected", tone: "bg-error/15 text-error" },
    cancelled: { label: "Cancelled", tone: "bg-slate-100 text-slate-400" },
    error: { label: "Error", tone: "bg-error/15 text-error" },
  };
  const cfg = map[phase];
  return (
    <span
      className={cn(
        "rounded-md px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider",
        cfg.tone,
      )}
    >
      {cfg.label}
    </span>
  );
}

function PreflightView({
  invoice,
  blockingIssues,
  busy,
  onSubmit,
}: {
  invoice: Invoice;
  blockingIssues: number;
  busy: boolean;
  onSubmit: () => void;
}) {
  const blocked = blockingIssues > 0 || !invoice.invoice_number;
  return (
    <>
      <p className="text-2xs text-slate-500">
        Once you submit, this invoice goes to LHDN for clearance. The
        validation UUID and QR code arrive in seconds. Cancellation is
        possible for 72 hours after.
      </p>
      {blocked && (
        <div className="rounded-md border border-warning/30 bg-warning/5 px-3 py-2 text-2xs text-slate-700">
          Resolve {blockingIssues > 0 ? `${blockingIssues} validation issue${blockingIssues === 1 ? "" : "s"}` : "the missing invoice number"} before submitting.
        </div>
      )}
      <div>
        <Button onClick={onSubmit} disabled={busy || blocked}>
          {busy ? (
            <>
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              Submitting…
            </>
          ) : (
            <>
              <Send className="mr-1.5 h-3.5 w-3.5" />
              Submit to LHDN
            </>
          )}
        </Button>
      </div>
    </>
  );
}

function InFlightView({
  busy,
  onPoll,
}: {
  invoice: Invoice;
  busy: boolean;
  onPoll: () => void;
}) {
  return (
    <>
      <div className="flex items-start gap-2 text-2xs text-slate-600">
        <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-warning" />
        <p>
          Submitted. LHDN is validating the document. Most decisions
          come back within 30 seconds. The page auto-refreshes every 5
          seconds.
        </p>
      </div>
      <div>
        <Button size="sm" variant="ghost" onClick={onPoll} disabled={busy}>
          Refresh status
        </Button>
      </div>
    </>
  );
}

function ValidatedView({
  invoice,
  canCancel,
  onCancelOpen,
  onAmendmentOpen,
  onPoll,
  polling,
}: {
  invoice: Invoice;
  canCancel: boolean;
  onCancelOpen: () => void;
  onAmendmentOpen: (t: AmendmentType) => void;
  onPoll: () => void;
  polling: boolean;
}) {
  return (
    <>
      <div className="flex items-start gap-2 text-2xs">
        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
        <p className="text-slate-600">
          Validated by LHDN MyInvois. The QR / verify link is publicly
          shareable.
        </p>
      </div>
      <dl className="grid gap-2 text-2xs sm:grid-cols-2">
        <Row label="Document UUID" value={invoice.lhdn_uuid} mono />
        <Row
          label="Validated at"
          value={
            invoice.validation_timestamp
              ? new Date(invoice.validation_timestamp).toLocaleString()
              : "—"
          }
        />
      </dl>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="ghost" onClick={onPoll} disabled={polling}>
          Refresh status
        </Button>
        {canCancel ? (
          <Button size="sm" variant="ghost" onClick={onCancelOpen}>
            <ShieldOff className="mr-1.5 h-3.5 w-3.5" />
            Cancel invoice
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onAmendmentOpen("credit_note")}
        >
          <FileMinus className="mr-1.5 h-3.5 w-3.5" />
          Credit note
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onAmendmentOpen("debit_note")}
        >
          <FilePlus className="mr-1.5 h-3.5 w-3.5" />
          Debit note
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onAmendmentOpen("refund_note")}
        >
          <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
          Refund note
        </Button>
      </div>
      {!canCancel && (
        <p className="text-2xs text-slate-400">
          72-hour cancel window has passed. To adjust this invoice,
          issue a credit/debit/refund note instead.
        </p>
      )}
    </>
  );
}

function RejectedView({
  invoice,
  busy,
  onRetry,
}: {
  invoice: Invoice;
  busy: boolean;
  onRetry: () => void;
}) {
  return (
    <>
      <div className="flex items-start gap-2 text-2xs">
        <X className="mt-0.5 h-3.5 w-3.5 shrink-0 text-error" />
        <div className="text-slate-600">
          <p className="font-medium text-error">LHDN rejected this invoice.</p>
          <p className="mt-1 whitespace-pre-wrap break-words">
            {invoice.error_message || "No detail provided."}
          </p>
        </div>
      </div>
      <div>
        <Button size="sm" onClick={onRetry} disabled={busy}>
          {busy ? "Retrying…" : "Fix issues + resubmit"}
        </Button>
      </div>
    </>
  );
}

function CancelledView({ invoice }: { invoice: Invoice }) {
  return (
    <div className="flex items-start gap-2 text-2xs text-slate-600">
      <Shield className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
      <div>
        <p>Cancelled at LHDN.</p>
        {invoice.cancellation_timestamp && (
          <p className="mt-1 text-slate-400">
            {new Date(invoice.cancellation_timestamp).toLocaleString()}
          </p>
        )}
      </div>
    </div>
  );
}

function ErrorView({ invoice }: { invoice: Invoice }) {
  return (
    <div className="flex items-start gap-2 text-2xs">
      <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-error" />
      <div className="text-slate-600">
        <p className="font-medium text-error">
          The submission pipeline hit an error.
        </p>
        <p className="mt-1 whitespace-pre-wrap break-words">
          {invoice.error_message || "Check the audit log."}
        </p>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-slate-400">
        {label}
      </dt>
      <dd
        className={cn(
          "mt-0.5",
          mono ? "font-mono text-[11px]" : "text-2xs",
          value ? "text-ink" : "text-slate-300",
        )}
      >
        {value || "—"}
      </dd>
    </div>
  );
}

function CancelDialog({
  reason,
  onChangeReason,
  onConfirm,
  onClose,
  busy,
}: {
  reason: string;
  onChangeReason: (v: string) => void;
  onConfirm: () => void;
  onClose: () => void;
  busy: boolean;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-ink/40 px-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-xl border border-slate-100 bg-white p-5 shadow-xl"
      >
        <h3 className="text-base font-semibold">Cancel this invoice?</h3>
        <p className="mt-2 text-2xs text-slate-500">
          Cancellation is final + visible on LHDN&apos;s portal. After 72
          hours from validation you can no longer cancel — issue a
          credit note instead.
        </p>
        <label className="mt-4 block text-2xs font-medium">
          Reason (required, sent to LHDN)
          <textarea
            value={reason}
            onChange={(e) => onChangeReason(e.target.value)}
            rows={3}
            placeholder="e.g. customer cancelled the order"
            className="mt-1 w-full rounded-md border border-slate-200 px-2 py-1.5 text-2xs focus:outline-none focus:ring-1 focus:ring-ink"
          />
        </label>
        <div className="mt-4 flex items-center justify-end gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={onClose}
            disabled={busy}
          >
            Keep invoice
          </Button>
          <Button
            size="sm"
            onClick={onConfirm}
            disabled={busy || !reason.trim()}
          >
            {busy ? "Cancelling…" : "Confirm cancellation"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function AmendmentDialog({
  type,
  reason,
  onChangeReason,
  onConfirm,
  onClose,
  busy,
}: {
  type: AmendmentType;
  reason: string;
  onChangeReason: (v: string) => void;
  onConfirm: () => void;
  onClose: () => void;
  busy: boolean;
}) {
  const copy = AMENDMENT_COPY[type];
  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-ink/40 px-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-xl border border-slate-100 bg-white p-5 shadow-xl"
      >
        <h3 className="text-base font-semibold">{copy.title}</h3>
        <p className="mt-2 text-2xs text-slate-500">
          {copy.blurb} It&apos;s a new LHDN document that links back to
          this one. After creation, you&apos;ll land on its review
          page where you can adjust amounts before submitting it to
          LHDN.
        </p>
        <label className="mt-4 block text-2xs font-medium">
          Reason (required, sent to LHDN)
          <textarea
            value={reason}
            onChange={(e) => onChangeReason(e.target.value)}
            rows={3}
            placeholder={copy.placeholder}
            className="mt-1 w-full rounded-md border border-slate-200 px-2 py-1.5 text-2xs focus:outline-none focus:ring-1 focus:ring-ink"
          />
        </label>
        <div className="mt-4 flex items-center justify-end gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={onClose}
            disabled={busy}
          >
            Never mind
          </Button>
          <Button
            size="sm"
            onClick={onConfirm}
            disabled={busy || !reason.trim()}
          >
            {busy ? copy.busyLabel : copy.confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
