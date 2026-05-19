"use client";

// DESKTOP_PIVOT_PLAN Phase 1 — License Inventory.
//
// One row per License the platform has ever issued. The operator's
// triage surface: who's active, who's expiring soon, who phoned home
// recently. Two destructive verbs live here (issue + revoke). Renew
// and regenerate live on the detail page.
//
// The cloud doesn't host invoices anymore — the customer's desktop
// does. This page is the lever Symprio actually pulls to operate the
// SaaS-shrunk-to-licensing model.

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Check, Copy, KeyRound, Plus, Search, X } from "lucide-react";

import { api, ApiError, type LicenseIssuanceResponse, type LicenseRow } from "@/lib/api";
import { AdminShell } from "@/components/admin/AdminShell";

const EASE = [0.16, 1, 0.3, 1] as const;

export default function LicenseInventoryPage() {
  const [licenses, setLicenses] = useState<LicenseRow[] | null>(null);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [issueOpen, setIssueOpen] = useState(false);
  const [reveal, setReveal] = useState<LicenseIssuanceResponse | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    let cancelled = false;
    setLicenses(null);
    setError(null);
    api
      .adminListLicenses({
        q: debouncedSearch || undefined,
        status: statusFilter || undefined,
        limit: 200,
      })
      .then((r) => {
        if (cancelled) return;
        setLicenses(r.results);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load.");
        setLicenses([]);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedSearch, statusFilter]);

  const sorted = useMemo(() => {
    if (!licenses) return null;
    return [...licenses].sort((a, b) => {
      // Active first, then by closest expiry.
      const aActive = a.status === "active" ? 0 : 1;
      const bActive = b.status === "active" ? 0 : 1;
      if (aActive !== bActive) return aActive - bActive;
      return a.expires_at.localeCompare(b.expires_at);
    });
  }, [licenses]);

  return (
    <AdminShell>
      <div className="flex flex-col gap-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">Licenses</h1>
            <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
              Desktop activations · one per organisation TIN
            </p>
          </div>
          <button
            type="button"
            onClick={() => setIssueOpen(true)}
            className="inline-flex items-center gap-2 rounded-md bg-ink px-3 py-2 text-2xs font-medium text-paper hover:bg-slate-800"
          >
            <Plus className="h-3.5 w-3.5" />
            Issue license
          </button>
        </header>

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error"
          >
            {error}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex max-w-md flex-1 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2">
            <Search className="h-4 w-4 text-slate-400" aria-hidden />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by company or TIN…"
              className="h-6 flex-1 bg-transparent text-2xs text-ink placeholder-slate-400 outline-none"
              aria-label="Search licenses"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="h-9 rounded-md border border-slate-200 bg-white px-2 text-2xs text-ink"
            aria-label="Status filter"
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="expired">Expired</option>
            <option value="suspended">Suspended</option>
            <option value="revoked">Revoked</option>
          </select>
        </div>

        {sorted === null ? (
          <Empty>Loading…</Empty>
        ) : sorted.length === 0 ? (
          <EmptyState filtered={!!debouncedSearch || !!statusFilter} />
        ) : (
          <LicenseTable rows={sorted} />
        )}
      </div>

      <IssueDialog
        open={issueOpen}
        onClose={() => setIssueOpen(false)}
        onIssued={(payload) => {
          setIssueOpen(false);
          setReveal(payload);
          // Slot the new row in immediately for instant feedback.
          setLicenses((cur) =>
            cur ? [payload.license, ...cur] : [payload.license],
          );
        }}
      />

      <KeyRevealDialog
        payload={reveal}
        onClose={() => setReveal(null)}
      />
    </AdminShell>
  );
}

function LicenseTable({ rows }: { rows: LicenseRow[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-100 bg-white">
      <table className="w-full text-2xs">
        <thead className="bg-slate-50 text-slate-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Organisation</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">TIN</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Plan</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Status</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Expires</th>
            <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Last heartbeat</th>
            <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => (
            <tr key={r.id} className="hover:bg-slate-50">
              <td className="px-3 py-3 font-medium text-ink">{r.organization_legal_name}</td>
              <td className="px-3 py-3">
                <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
                  {r.organization_tin}
                </code>
              </td>
              <td className="px-3 py-3 capitalize text-slate-600">{r.plan}</td>
              <td className="px-3 py-3">
                <StatusBadge status={r.status} />
              </td>
              <td className="px-3 py-3 text-slate-500">{formatDate(r.expires_at)}</td>
              <td className="px-3 py-3 text-slate-500">
                {r.last_heartbeat_at ? formatRelative(r.last_heartbeat_at) : "—"}
              </td>
              <td className="px-3 py-3 text-right">
                <Link
                  href={`/admin/licenses/${r.id}`}
                  className="text-2xs font-medium text-ink underline-offset-4 hover:underline"
                >
                  Open →
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
      className={`inline-flex rounded-sm px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${tone}`}
    >
      {status}
    </span>
  );
}

function IssueDialog({
  open,
  onClose,
  onIssued,
}: {
  open: boolean;
  onClose: () => void;
  onIssued: (response: LicenseIssuanceResponse) => void;
}) {
  const reduced = useReducedMotion();
  const [ownerUserId, setOwnerUserId] = useState("");
  const [legalName, setLegalName] = useState("");
  const [tin, setTin] = useState("");
  const [plan, setPlan] = useState<"starter" | "professional" | "enterprise">(
    "starter",
  );
  const [validityDays, setValidityDays] = useState(365);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setOwnerUserId("");
      setLegalName("");
      setTin("");
      setPlan("starter");
      setValidityDays(365);
      setSubmitting(false);
      setError(null);
    }
  }, [open]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const response = await api.adminIssueLicense({
        owner_user_id: ownerUserId.trim(),
        organization_legal_name: legalName.trim(),
        organization_tin: tin.trim(),
        plan,
        validity_days: validityDays,
      });
      onIssued(response);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to issue.");
      setSubmitting(false);
    }
  }

  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-[100] flex items-center justify-center px-4"
        initial={reduced ? false : { opacity: 0 }}
        animate={reduced ? undefined : { opacity: 1 }}
        exit={reduced ? undefined : { opacity: 0 }}
        transition={{ duration: 0.18, ease: EASE }}
      >
        <button
          type="button"
          tabIndex={-1}
          aria-hidden
          onClick={submitting ? undefined : onClose}
          className="absolute inset-0 cursor-default bg-ink/40 backdrop-blur-sm"
        />
        <motion.form
          role="dialog"
          aria-modal="true"
          aria-labelledby="issue-license-title"
          onSubmit={onSubmit}
          initial={reduced ? false : { opacity: 0, y: 12, scale: 0.98 }}
          animate={reduced ? undefined : { opacity: 1, y: 0, scale: 1 }}
          exit={reduced ? undefined : { opacity: 0, y: 12, scale: 0.98 }}
          transition={{ duration: 0.22, ease: EASE }}
          className="relative z-10 w-full max-w-lg overflow-hidden rounded-xl bg-white shadow-2xl shadow-ink/20"
        >
          <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-4">
            <h2
              id="issue-license-title"
              className="font-display text-lg font-bold tracking-tight text-ink"
            >
              Issue a new license
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

          <div className="space-y-3 px-6 py-5 text-sm">
            <Field label="Owner user ID">
              <input
                value={ownerUserId}
                onChange={(e) => setOwnerUserId(e.target.value)}
                required
                placeholder="UUID — copy from /admin/tenants/<id>"
                className="w-full rounded-md border border-slate-200 px-3 py-2 font-mono text-2xs text-ink"
              />
            </Field>
            <Field label="Organisation legal name">
              <input
                value={legalName}
                onChange={(e) => setLegalName(e.target.value)}
                required
                placeholder="Acme Sdn Bhd"
                className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm text-ink"
              />
            </Field>
            <Field label="LHDN TIN (must be unique)">
              <input
                value={tin}
                onChange={(e) => setTin(e.target.value.toUpperCase())}
                required
                placeholder="C1234567890"
                className="w-full rounded-md border border-slate-200 px-3 py-2 font-mono text-sm text-ink"
              />
            </Field>
            <div className="flex gap-3">
              <Field label="Plan">
                <select
                  value={plan}
                  onChange={(e) =>
                    setPlan(e.target.value as typeof plan)
                  }
                  className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-ink"
                >
                  <option value="starter">Starter</option>
                  <option value="professional">Professional</option>
                  <option value="enterprise">Enterprise</option>
                </select>
              </Field>
              <Field label="Validity (days)">
                <input
                  type="number"
                  min={30}
                  max={3650}
                  value={validityDays}
                  onChange={(e) => setValidityDays(Number(e.target.value))}
                  className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm text-ink"
                />
              </Field>
            </div>

            {error && (
              <p
                role="alert"
                className="rounded-md border border-error/30 bg-error/5 px-3 py-2 text-xs text-error"
              >
                {error}
              </p>
            )}
          </div>

          <footer className="flex items-center justify-end gap-2 border-t border-slate-100 bg-slate-50 px-6 py-3">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="rounded-md px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 hover:text-ink disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex items-center justify-center rounded-md bg-ink px-4 py-2 text-sm font-semibold text-paper hover:bg-slate-800 disabled:opacity-50"
            >
              {submitting ? "Issuing…" : "Issue license"}
            </button>
          </footer>
        </motion.form>
      </motion.div>
    </AnimatePresence>
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
      // Clipboard rejection — fall back to a select-and-prompt; rare,
      // not worth a full fallback path.
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
            <div className="flex items-start gap-3">
              <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-success/10 text-success">
                <KeyRound size={16} />
              </span>
              <div>
                <h2 className="font-display text-lg font-bold tracking-tight text-ink">
                  License issued
                </h2>
                <p className="text-2xs text-slate-500">
                  {payload.license.organization_legal_name}
                </p>
              </div>
            </div>
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
              Copy and send this key to the customer now.{" "}
              <span className="font-semibold text-ink">It will not be shown again.</span>{" "}
              If they lose it, regenerate from the license detail page.
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
            <p className="mt-3 text-2xs text-slate-500">
              TIN <code className="font-mono">{payload.license.organization_tin}</code> · Plan{" "}
              <span className="capitalize">{payload.license.plan}</span> · Expires{" "}
              {formatDate(payload.license.expires_at)}
            </p>
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-2xs font-medium uppercase tracking-wider text-slate-400">
        {label}
      </span>
      {children}
    </label>
  );
}

function EmptyState({ filtered }: { filtered: boolean }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-12 text-center">
      <KeyRound className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
      <h2 className="mt-4 font-display text-xl font-semibold">
        {filtered ? "No matching licenses" : "No licenses yet"}
      </h2>
      <p className="mx-auto mt-2 max-w-md text-2xs text-slate-500">
        {filtered
          ? "Try a different search or clear the filters."
          : "Issue the first license with the button above."}
      </p>
    </div>
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
