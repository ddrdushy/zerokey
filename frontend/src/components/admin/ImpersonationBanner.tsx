"use client";

// Impersonation banner — surfaces above the customer shell whenever
// the active session is a staff impersonation. Shows the tenant's
// legal name, the reason for the session, a live countdown to expiry,
// and an "End impersonation" button that returns the operator to
// /admin and unwinds the Django session.
//
// Renders nothing when there's no active impersonation, so wrapping
// the customer AppShell with this is a zero-cost layout change for
// regular customer sessions.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldAlert, X } from "lucide-react";

import { api, type ImpersonationContext } from "@/lib/api";

type Props = {
  ctx: ImpersonationContext;
};

export function ImpersonationBanner({ ctx }: Props) {
  const router = useRouter();
  const [remaining, setRemaining] = useState(() => secondsLeft(ctx.expires_at));
  const [ending, setEnding] = useState(false);

  useEffect(() => {
    const interval = setInterval(() => {
      setRemaining(secondsLeft(ctx.expires_at));
    }, 1000);
    return () => clearInterval(interval);
  }, [ctx.expires_at]);

  async function onEnd() {
    setEnding(true);
    try {
      const result = await api.adminEndImpersonation();
      router.replace(result.redirect_to || "/admin");
    } catch {
      // Even if the end call fails, route to /admin — the next /me/
      // will reconcile.
      router.replace("/admin");
    } finally {
      setEnding(false);
    }
  }

  const expired = remaining <= 0;
  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;

  return (
    <div
      role="status"
      aria-live="polite"
      className={
        expired
          ? "border-b border-error/30 bg-error/5 px-4 py-2 text-error"
          : "border-b border-warning/30 bg-warning/5 px-4 py-2 text-warning"
      }
    >
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 text-2xs">
        <ShieldAlert className="h-3.5 w-3.5" />
        <span className="font-semibold uppercase tracking-wider">
          Impersonating
        </span>
        <span className="font-medium text-ink">{ctx.tenant_legal_name}</span>
        <span className="text-slate-500">· {ctx.reason}</span>
        <span className="ml-auto inline-flex items-center gap-3">
          <span className="font-mono">
            {expired
              ? "session expired"
              : `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")} remaining`}
          </span>
          <button
            type="button"
            onClick={onEnd}
            disabled={ending}
            className="inline-flex items-center gap-1 rounded-md bg-ink px-2.5 py-1 text-2xs font-medium text-paper hover:opacity-90 disabled:opacity-60"
          >
            <X className="h-3 w-3" />
            End impersonation
          </button>
        </span>
      </div>
    </div>
  );
}

function secondsLeft(iso: string): number {
  const expiresAt = new Date(iso).getTime();
  if (Number.isNaN(expiresAt)) return 0;
  return Math.max(0, Math.floor((expiresAt - Date.now()) / 1000));
}
