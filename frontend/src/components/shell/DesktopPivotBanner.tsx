"use client";

// DESKTOP_PIVOT_PLAN — the SaaS dashboard is being deprecated.
//
// We do not delete the routes yet (some flows still need it, and the
// archive matters), but every customer-facing page now wears this
// banner so nobody misses the change. The CTA points at /download
// where the customer authenticates and pulls the installer.

import Link from "next/link";
import { Download, X } from "lucide-react";
import { useEffect, useState } from "react";

const DISMISS_KEY = "zk-desktop-pivot-banner-dismissed-v1";

export function DesktopPivotBanner() {
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    // Read localStorage post-mount to avoid SSR/CSR hydration mismatch.
    try {
      setDismissed(localStorage.getItem(DISMISS_KEY) === "1");
    } catch {
      setDismissed(false);
    }
  }, []);

  function onDismiss() {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      // Private mode etc — banner stays dismissed for the session.
    }
  }

  if (dismissed) return null;

  return (
    <div
      role="status"
      className="border-b border-signal/40 bg-signal/10 px-4 py-2 text-2xs text-ink"
    >
      <div className="mx-auto flex max-w-7xl items-center gap-3">
        <span className="inline-flex items-center gap-1.5 font-medium">
          <Download className="h-3.5 w-3.5" />
          ZeroKey is moving to a desktop app.
        </span>
        <span className="hidden text-slate-600 md:inline">
          Your invoice data stays on your machine. Annual license — no subscription.
        </span>
        <span className="flex-1" />
        <Link
          href="/download"
          className="rounded-md bg-ink px-2 py-1 text-2xs font-medium text-paper hover:bg-slate-800"
        >
          Get the installer
        </Link>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="rounded-md p-1 text-slate-500 hover:bg-ink/10 hover:text-ink"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
