"use client";

// DESKTOP_PIVOT_PLAN Phase 1 — License detail page.
//
// One license + its recent heartbeat trail. Three operator actions:
//   - Revoke (terminal; needs a reason for the audit log)
//   - Regenerate key (kills the old key + clears the fingerprint
//     binding, used for "I lost my key" or "I'm moving machines")
//   - Renew (bump expiry by N days)
//
// We don't show the original key here — it was revealed once on
// issuance. Regenerating produces a fresh key with the same reveal
// modal.

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Check, Copy, RefreshCw, RotateCw, Shield, X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";

import {
  api,
  ApiError,
  type LicenseHeartbeatRow,
  type LicenseIssuanceResponse,
  type LicenseRow,
} from "@/lib/api";
import { AdminShell } from "@/components/admin/AdminShell";
import { ConfirmDialog } from "@/components/admin/ConfirmDialog";

const EASE = [0.16, 1, 0.3, 1] as const;

export default function LicenseDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [license, setLicense] = useState<LicenseRow | null>(null);
  const [heartbeats, setHeartbeats] = useState<LicenseHeartbeatRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [reveal, setReveal] = useState<LicenseIssuanceResponse | null>(null);
  const [busy, setBusy] = useState(false);

  async function reload() {
    try {
      const r = await api.adminGetLicense(params.id);
      setLicense(r.license);
      setHeartbeats(r.recent_heartbeats);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        router.replace("/admin/licenses");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load.");
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  async function onRevoke(reason: string) {
    try {
      const r = await api.adminRevokeLicense(params.id, reason);
      setLicense(r.license);
      setRevokeOpen(false);
    } catch (err) {
      throw new Error(err instanceof ApiError ? err.message : "Failed to revoke.");
    }
  }

  async function onRegenerate() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.adminRegenerateLicenseKey(params.id);
      setLicense(r.license);
      setReveal(r);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to regenerate key.");
    } finally {
      setBusy(false);
    }
  }

  async function onRenew(days: number) {
    setBusy(true);
    setError(null);
    try {
      const r = await api.adminRenewLicense(params.id, days);
      setLicense(r.license);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to renew.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AdminShell>
      <div className="flex flex-col gap-6">
        <Link
          href="/admin/licenses"
          className="inline-flex items-center gap-1 text-2xs font-medium text-slate-500 hover:text-ink"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to licenses
        </Link>

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error"
          >
            {error}
          </div>
        )}

        {license === null ? (
          <Empty>Loading…</Empty>
        ) : (
          <>
            <header className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h1 className="font-display text-2xl font-bold tracking-tight">
                  {license.organization_legal_name}
                </h1>
                <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
                  TIN{" "}
                  <code className="font-mono normal-case">{license.organization_tin}</code>
                  {" · Plan "}
                  <span className="capitalize">{license.plan}</span>
                </p>
              </div>
              <StatusBadge status={license.status} />
            </header>

            <section className="grid gap-4 md:grid-cols-3">
              <Card label="Issued">
                <div className="text-sm text-ink">{formatDate(license.issued_at)}</div>
              </Card>
              <Card label="Expires">
                <div className="text-sm text-ink">{formatDate(license.expires_at)}</div>
                <div className="mt-0.5 text-2xs text-slate-500">
                  {expiryDelta(license.expires_at)}
                </div>
              </Card>
              <Card label="Last heartbeat">
                <div className="text-sm text-ink">
                  {license.last_heartbeat_at
                    ? formatRelative(license.last_heartbeat_at)
                    : "Never"}
                </div>
                {license.last_heartbeat_ip && (
                  <div className="mt-0.5 font-mono text-2xs text-slate-500">
                    {license.last_heartbeat_ip}
                  </div>
                )}
              </Card>
            </section>

            <section className="grid gap-4 md:grid-cols-2">
              <Card label="Machine binding">
                {license.bound_fingerprint_hash ? (
                  <>
                    <div className="font-mono text-2xs text-ink">
                      {license.bound_fingerprint_hash}…
                    </div>
                    <div className="mt-0.5 text-2xs text-slate-500">
                      Bound {license.bound_at ? formatRelative(license.bound_at) : "—"}
                    </div>
                  </>
                ) : (
                  <div className="text-2xs text-slate-500">Not yet activated</div>
                )}
              </Card>
              <Card label="Desktop version">
                <div className="text-sm text-ink">
                  {license.last_desktop_version || "—"}
                </div>
              </Card>
            </section>

            <section className="flex flex-wrap gap-2">
              {license.status !== "revoked" && (
                <>
                  <button
                    type="button"
                    onClick={onRegenerate}
                    disabled={busy}
                    className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs font-medium text-ink hover:border-ink disabled:opacity-50"
                    title="Issue a new key; clears the machine binding"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    Regenerate key
                  </button>
                  <button
                    type="button"
                    onClick={() => onRenew(365)}
                    disabled={busy}
                    className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs font-medium text-ink hover:border-ink disabled:opacity-50"
                  >
                    <RotateCw className="h-3.5 w-3.5" />
                    Renew 1 year
                  </button>
                  <button
                    type="button"
                    onClick={() => setRevokeOpen(true)}
                    disabled={busy}
                    className="inline-flex items-center gap-1.5 rounded-md border border-error/40 bg-error/5 px-3 py-1.5 text-2xs font-medium text-error hover:bg-error/10 disabled:opacity-50"
                  >
                    <Shield className="h-3.5 w-3.5" />
                    Revoke
                  </button>
                </>
              )}
              {license.status === "revoked" && (
                <div className="rounded-md border border-error/30 bg-error/5 px-3 py-2 text-2xs text-error">
                  Revoked {license.revoked_at ? formatRelative(license.revoked_at) : "—"}
                  {license.revoke_reason && (
                    <span className="ml-1 text-error/80"> · {license.revoke_reason}</span>
                  )}
                </div>
              )}
            </section>

            <section>
              <h2 className="mb-2 text-2xs font-medium uppercase tracking-wider text-slate-400">
                Recent heartbeats
              </h2>
              {heartbeats.length === 0 ? (
                <div className="rounded-md border border-slate-100 bg-white p-6 text-2xs text-slate-500">
                  The desktop hasn't phoned home yet.
                </div>
              ) : (
                <div className="overflow-x-auto rounded-md border border-slate-100 bg-white">
                  <table className="w-full text-2xs">
                    <thead className="bg-slate-50 text-slate-400">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">When</th>
                        <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Event</th>
                        <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Result</th>
                        <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">IP</th>
                        <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Version</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {heartbeats.map((h) => (
                        <tr key={h.id}>
                          <td className="px-3 py-2 text-slate-500">{formatRelative(h.at)}</td>
                          <td className="px-3 py-2 capitalize text-ink">{h.event_type}</td>
                          <td className="px-3 py-2">
                            <ResultPill result={h.result} />
                          </td>
                          <td className="px-3 py-2 font-mono text-slate-500">{h.ip ?? "—"}</td>
                          <td className="px-3 py-2 text-slate-500">{h.desktop_version || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </div>

      <ConfirmDialog
        open={revokeOpen}
        onClose={() => setRevokeOpen(false)}
        title="Revoke this license?"
        body={
          <p>
            The desktop will drop to read-only mode on its next heartbeat
            (within 24 h). The customer cannot ingest or submit invoices
            after that. This is terminal — to give them access back, issue
            a new license under the same TIN.
          </p>
        }
        confirmLabel="Revoke license"
        danger
        requireReason
        reasonPlaceholder="e.g. unpaid invoice; suspected key sharing"
        onConfirm={onRevoke}
      />

      <KeyRevealDialog payload={reveal} onClose={() => setReveal(null)} />
    </AdminShell>
  );
}

function StatusBadge({ status }: { status: LicenseRow["status"] }) {
  const tone =
    status === "active"
      ? "bg-success/10 text-success"
      : status === "expired"
        ? "bg-warning/10 text-warning"
        : status === "suspended"
          ? "bg-slate-100 text-slate-600"
          : "bg-error/10 text-error";
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-1 text-2xs font-medium uppercase tracking-wider ${tone}`}
    >
      {status}
    </span>
  );
}

function ResultPill({ result }: { result: LicenseHeartbeatRow["result"] }) {
  const tone =
    result === "ok"
      ? "bg-success/10 text-success"
      : result === "fingerprint_mismatch"
        ? "bg-warning/10 text-warning"
        : "bg-error/10 text-error";
  return (
    <span
      className={`inline-flex rounded-sm px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${tone}`}
    >
      {result.replace(/_/g, " ")}
    </span>
  );
}

function Card({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-slate-100 bg-white p-4">
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

function KeyRevealDialog({
  payload,
  onClose,
}: {
  payload: LicenseIssuanceResponse | null;
  onClose: () => void;
}) {
  const reduced = useReducedMotion();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!payload) setCopied(false);
  }, [payload]);

  async function onCopy() {
    if (!payload) return;
    try {
      await navigator.clipboard.writeText(payload.plaintext_key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore — user can select manually
    }
  }

  if (!payload) return null;
  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-[100] flex items-center justify-center px-4"
        initial={reduced ? false : { opacity: 0 }}
        animate={reduced ? undefined : { opacity: 1 }}
        exit={reduced ? undefined : { opacity: 0 }}
        transition={{ duration: 0.18, ease: EASE }}
      >
        <div className="absolute inset-0 bg-ink/40 backdrop-blur-sm" />
        <motion.div
          role="dialog"
          aria-modal="true"
          initial={reduced ? false : { opacity: 0, y: 12, scale: 0.98 }}
          animate={reduced ? undefined : { opacity: 1, y: 0, scale: 1 }}
          exit={reduced ? undefined : { opacity: 0, y: 12, scale: 0.98 }}
          transition={{ duration: 0.22, ease: EASE }}
          className="relative z-10 w-full max-w-lg overflow-hidden rounded-xl bg-white shadow-2xl shadow-ink/20"
        >
          <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-4">
            <h2 className="font-display text-lg font-bold tracking-tight text-ink">
              New key generated
            </h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-ink"
            >
              <X size={16} />
            </button>
          </header>
          <div className="px-6 py-5">
            <p className="text-sm text-slate-600">
              The old key is dead. Send this one to the customer.{" "}
              <span className="font-semibold text-ink">It will not be shown again.</span>
            </p>
            <div className="mt-4 flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
              <code className="flex-1 break-all font-mono text-xs text-ink">
                {payload.plaintext_key}
              </code>
              <button
                type="button"
                onClick={onCopy}
                className="inline-flex items-center gap-1 rounded-md bg-ink px-2 py-1.5 text-2xs font-medium text-paper hover:bg-slate-800"
              >
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          </div>
          <footer className="flex items-center justify-end gap-2 border-t border-slate-100 bg-slate-50 px-6 py-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md bg-ink px-4 py-2 text-sm font-semibold text-paper hover:bg-slate-800"
            >
              I've copied the key
            </button>
          </footer>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid place-items-center py-24 text-2xs uppercase tracking-wider text-slate-400">
      {children}
    </div>
  );
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "recently";
  const diffSec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (diffSec < 60) return "just now";
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  return `${Math.round(diffDay / 30)}mo ago`;
}

function expiryDelta(iso: string): string {
  const then = new Date(iso).getTime();
  const diffMs = then - Date.now();
  const days = Math.round(diffMs / (1000 * 60 * 60 * 24));
  if (days < 0) return `expired ${Math.abs(days)}d ago`;
  if (days === 0) return "expires today";
  if (days <= 30) return `${days}d remaining`;
  return `${Math.round(days / 30)}mo remaining`;
}
