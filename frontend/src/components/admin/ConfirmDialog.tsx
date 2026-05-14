"use client";

// Reusable confirm modal for destructive admin actions. Supersedes the
// native window.confirm + window.prompt pair we were using for tenant
// delete. Built on a focus-trapped portal so keyboard users can dismiss
// with Escape and tab is constrained to the dialog while open.
//
// Three optional shapes:
//   - bare confirm (no reason field) — pass nothing extra
//   - destructive confirm (red CTA, X icon) — pass `danger`
//   - audit-reason confirm (textarea required) — pass `requireReason`

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { AlertTriangle, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const EASE = [0.16, 1, 0.3, 1] as const;

export type ConfirmDialogProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Body — supports plain text or React children. */
  body?: React.ReactNode;
  /** Confirm-button label. */
  confirmLabel?: string;
  /** Cancel-button label. */
  cancelLabel?: string;
  /** Red destructive treatment on the confirm button. */
  danger?: boolean;
  /** When true, show a textarea and require non-empty text before calling onConfirm(reason). */
  requireReason?: boolean;
  /** Placeholder for the reason textarea. */
  reasonPlaceholder?: string;
  /** Called when the user confirms. Receives the typed reason string (empty if requireReason is false). */
  onConfirm: (reason: string) => void | Promise<void>;
};

export function ConfirmDialog({
  open,
  onClose,
  title,
  body,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  requireReason = false,
  reasonPlaceholder = "Reason (recorded in the audit log)",
  onConfirm,
}: ConfirmDialogProps) {
  const reduced = useReducedMotion();
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstFocusableRef = useRef<HTMLTextAreaElement | HTMLButtonElement>(null);

  // Reset internal state every time we open.
  useEffect(() => {
    if (open) {
      setReason("");
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  // Body scroll lock + initial focus.
  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const t = setTimeout(() => firstFocusableRef.current?.focus(), 50);
    return () => {
      document.body.style.overflow = prevOverflow;
      clearTimeout(t);
    };
  }, [open]);

  // Esc to close, simple Tab focus trap inside the dialog.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !submitting) {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose, submitting]);

  async function handleConfirm() {
    if (requireReason && !reason.trim()) {
      setError("A reason is required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
      // Caller is expected to close on success; nothing further here.
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed.");
      setSubmitting(false);
    }
  }

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center justify-center px-4"
          initial={reduced ? false : { opacity: 0 }}
          animate={reduced ? undefined : { opacity: 1 }}
          exit={reduced ? undefined : { opacity: 0 }}
          transition={{ duration: 0.18, ease: EASE }}
        >
          {/* Backdrop */}
          <button
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            onClick={submitting ? undefined : onClose}
            className="absolute inset-0 cursor-default bg-ink/40 backdrop-blur-sm"
          />

          {/* Dialog */}
          <motion.div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-dialog-title"
            initial={reduced ? false : { opacity: 0, y: 12, scale: 0.98 }}
            animate={reduced ? undefined : { opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? undefined : { opacity: 0, y: 12, scale: 0.98 }}
            transition={{ duration: 0.22, ease: EASE }}
            className="relative z-10 w-full max-w-md overflow-hidden rounded-xl bg-white shadow-2xl shadow-ink/20"
          >
            <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-4">
              <div className="flex items-start gap-3">
                {danger ? (
                  <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-error/10 text-error">
                    <AlertTriangle size={16} />
                  </span>
                ) : null}
                <h2 id="confirm-dialog-title" className="font-display text-lg font-bold tracking-tight text-ink">
                  {title}
                </h2>
              </div>
              <button
                type="button"
                onClick={onClose}
                disabled={submitting}
                aria-label="Close"
                className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
              >
                <X size={16} />
              </button>
            </header>

            <div className="px-6 py-5">
              {body ? <div className="text-sm leading-relaxed text-slate-600">{body}</div> : null}

              {requireReason ? (
                <label className="mt-4 block">
                  <span className="mb-1 block text-2xs font-medium uppercase tracking-wider text-slate-400">
                    Reason <span className="text-error">*</span>
                  </span>
                  <textarea
                    ref={firstFocusableRef as React.RefObject<HTMLTextAreaElement>}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder={reasonPlaceholder}
                    rows={3}
                    disabled={submitting}
                    className="w-full resize-none rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-ink placeholder:text-slate-400 focus:border-ink focus:outline-none focus:ring-1 focus:ring-ink disabled:cursor-not-allowed disabled:opacity-60"
                  />
                </label>
              ) : null}

              {error ? (
                <p role="alert" className="mt-3 rounded-md border border-error/30 bg-error/5 px-3 py-2 text-xs text-error">
                  {error}
                </p>
              ) : null}
            </div>

            <footer className="flex items-center justify-end gap-2 border-t border-slate-100 bg-slate-50 px-6 py-3">
              <button
                type="button"
                onClick={onClose}
                disabled={submitting}
                className="rounded-md px-4 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
              >
                {cancelLabel}
              </button>
              <button
                ref={requireReason ? undefined : (firstFocusableRef as React.RefObject<HTMLButtonElement>)}
                type="button"
                onClick={handleConfirm}
                disabled={submitting || (requireReason && !reason.trim())}
                className={[
                  "inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                  danger
                    ? "bg-error text-paper hover:brightness-110"
                    : "bg-ink text-paper hover:bg-slate-800",
                ].join(" ")}
              >
                {submitting ? "Working…" : confirmLabel}
              </button>
            </footer>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
