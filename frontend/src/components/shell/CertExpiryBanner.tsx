"use client";

// Slice 66 — LHDN signing certificate expiry banner.
//
// Customers buy a 1- or 2-year cert from MSC Trustgate / Pos Digicert
// / TAB Bhd; it expires silently if nobody renews. A failed signature
// at submit time is the worst possible discovery moment — user is
// already trying to file an invoice. So we surface the expiry early.
//
// Tiers (chosen because LHDN cert renewal at the CAs takes 5–10
// business days, so 30 days is the realistic action threshold):
//   30+ days       → silent
//   30–14 days out → amber notice
//   14–1  days out → amber warning
//   today / past   → red banner ("expired today" / "expired N days ago")
//
// Self-signed dev certs are excluded from the banner — they auto-
// rotate on next signing operation, so showing them here would be
// noise. Only ``kind == "uploaded"`` triggers the banner.

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, X } from "lucide-react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type CertState = {
  uploaded: boolean;
  kind: string;
  subject_common_name: string;
  serial_hex: string;
  expires_at: string | null;
};

type Severity = "notice" | "warning" | "error";

type BannerCopy = {
  severity: Severity;
  message: string;
};

function deriveCopy(state: CertState): BannerCopy | null {
  if (state.kind !== "uploaded") return null;
  if (!state.expires_at) return null;

  const expiry = new Date(state.expires_at).getTime();
  const now = Date.now();
  const days = Math.floor((expiry - now) / 86_400_000);

  if (days > 30) return null;

  if (days < 0) {
    const ago = Math.abs(days);
    return {
      severity: "error",
      message:
        ago === 1
          ? "Your LHDN signing certificate expired yesterday — submissions will fail until you renew."
          : `Your LHDN signing certificate expired ${ago} days ago — submissions will fail until you renew.`,
    };
  }
  if (days === 0) {
    return {
      severity: "error",
      message:
        "Your LHDN signing certificate expires today. Renew before midnight to avoid signature failures.",
    };
  }
  if (days <= 14) {
    return {
      severity: "warning",
      message:
        days === 1
          ? "Your LHDN signing certificate expires tomorrow. CA renewal takes several business days — start now."
          : `Your LHDN signing certificate expires in ${days} days. CA renewal takes several business days — start now.`,
    };
  }
  return {
    severity: "notice",
    message: `Your LHDN signing certificate expires in ${days} days. Plan your renewal with your CA in advance.`,
  };
}

const DISMISS_KEY = "zerokey.cert_banner.dismissed_at";

function dismissedRecently(): boolean {
  if (typeof window === "undefined") return false;
  const raw = window.sessionStorage.getItem(DISMISS_KEY);
  if (!raw) return false;
  const at = Number.parseInt(raw, 10);
  if (!Number.isFinite(at)) return false;
  // Re-show after 4h even within the same session — this is too
  // important to bury permanently behind a click.
  return Date.now() - at < 4 * 60 * 60 * 1000;
}

export function CertExpiryBanner() {
  const [copy, setCopy] = useState<BannerCopy | null>(null);
  const [dismissed, setDismissed] = useState<boolean>(() => dismissedRecently());

  useEffect(() => {
    let cancelled = false;
    api
      .getCertificate()
      .then((state) => {
        if (cancelled) return;
        setCopy(deriveCopy(state));
      })
      .catch(() => {
        // 401/403 (signed out, cross-tenant) is not the banner's
        // problem — AppShell's redirect handles auth state.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!copy || dismissed) return null;

  function dismiss() {
    setDismissed(true);
    try {
      window.sessionStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {
      // Storage blocked — accept the in-memory dismissal only.
    }
  }

  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 border-b px-4 py-3 text-2xs md:px-8",
        copy.severity === "error" && "border-error/30 bg-error/5 text-error",
        copy.severity === "warning" && "border-warning/30 bg-warning/10 text-warning",
        copy.severity === "notice" && "border-amber-200 bg-amber-50 text-amber-800",
      )}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="flex flex-1 flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-medium">{copy.message}</span>
        <Link
          href="/dashboard/settings/integrations"
          className="underline underline-offset-2 hover:no-underline"
        >
          Open certificate settings →
        </Link>
      </div>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss certificate expiry banner"
        className="rounded p-0.5 hover:bg-black/5"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
