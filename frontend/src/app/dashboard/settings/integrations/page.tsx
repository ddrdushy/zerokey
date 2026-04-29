"use client";

// Settings → Integrations (Slice 57). Per-tenant credentials for
// external integrations — today only LHDN MyInvois is wired.
//
// Each integration renders as a card with:
//   - Active-environment toggle at the top (sandbox vs production).
//   - Two stacked sub-cards: Sandbox creds, Production creds.
//   - "Test connection" button per environment with the last-test
//     outcome shown inline.
//
// Owner / admin only for writes; viewer / submitter / approver get
// a read-only view (no edit fields, no buttons). Backend enforces
// the same; the FE gate is for UX cleanliness.

import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  FileKey2,
  Loader2,
  PlugZap,
  ShieldCheck,
  Upload,
} from "lucide-react";

import {
  api,
  ApiError,
  type IntegrationCard,
  type Me,
} from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { SettingsTabs } from "@/components/settings/SettingsTabs";
import { cn } from "@/lib/utils";

export default function IntegrationsSettingsPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [cards, setCards] = useState<IntegrationCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setCards(await api.listIntegrations());
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError("You are not a member of this organization.");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load.");
      setCards([]);
    }
  }

  useEffect(() => {
    api.me().then(setMe).catch(() => {});
    refresh();
  }, []);

  const myRole = useMemo(
    () =>
      me
        ? me.memberships.find(
            (m) => m.organization.id === me.active_organization_id,
          )?.role.name ?? null
        : null,
    [me],
  );
  const canManage = myRole === "owner" || myRole === "admin";

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Settings
          </h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            Organization, members, and platform integrations
          </p>
        </header>
        <SettingsTabs />

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error"
          >
            {error}
          </div>
        )}

        <CertificateCard canManage={canManage} onError={setError} />

        {cards === null ? (
          <Loading />
        ) : cards.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="flex flex-col gap-6">
            {cards.map((card) => (
              <IntegrationCardView
                key={card.integration_key}
                card={card}
                canManage={canManage}
                onChanged={refresh}
                onError={setError}
              />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}

function IntegrationCardView({
  card,
  canManage,
  onChanged,
  onError,
}: {
  card: IntegrationCard;
  canManage: boolean;
  onChanged: () => void;
  onError: (m: string | null) => void;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-100 bg-white">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-ink/[0.05] p-2">
            <PlugZap className="h-4 w-4 text-ink" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-ink">{card.label}</h2>
            <p className="mt-1 max-w-xl text-2xs text-slate-500">
              {card.description}
            </p>
          </div>
        </div>
        <ActiveEnvBadge
          card={card}
          canManage={canManage}
          onChanged={onChanged}
          onError={onError}
        />
      </header>

      <div className="grid gap-px bg-slate-100 sm:grid-cols-2">
        <EnvironmentSubCard
          card={card}
          environment="sandbox"
          canManage={canManage}
          onChanged={onChanged}
          onError={onError}
        />
        <EnvironmentSubCard
          card={card}
          environment="production"
          canManage={canManage}
          onChanged={onChanged}
          onError={onError}
        />
      </div>
    </section>
  );
}

function ActiveEnvBadge({
  card,
  canManage,
  onChanged,
  onError,
}: {
  card: IntegrationCard;
  canManage: boolean;
  onChanged: () => void;
  onError: (m: string | null) => void;
}) {
  const [switching, setSwitching] = useState(false);
  const isProd = card.active_environment === "production";

  async function flip() {
    if (!canManage) return;
    const target: "sandbox" | "production" = isProd ? "sandbox" : "production";
    if (target === "production") {
      const ok = window.confirm(
        "Switch to PRODUCTION? Live invoices will hit LHDN's real API. " +
          "Make sure your production credentials have been tested.",
      );
      if (!ok) return;
    }
    setSwitching(true);
    onError(null);
    try {
      await api.switchIntegrationEnvironment(card.integration_key, target);
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Switch failed.");
    } finally {
      setSwitching(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <div
        className={cn(
          "rounded-md px-2 py-1 text-[10px] font-medium uppercase tracking-wider",
          isProd
            ? "bg-warning/15 text-warning"
            : "bg-slate-100 text-slate-500",
        )}
      >
        {isProd ? "Live · production" : "Sandbox / dev"}
      </div>
      {canManage && (
        <Button
          size="sm"
          variant="ghost"
          onClick={flip}
          disabled={switching}
        >
          {switching ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : isProd ? (
            "Switch to sandbox"
          ) : (
            "Go live →"
          )}
        </Button>
      )}
    </div>
  );
}

function EnvironmentSubCard({
  card,
  environment,
  canManage,
  onChanged,
  onError,
}: {
  card: IntegrationCard;
  environment: "sandbox" | "production";
  canManage: boolean;
  onChanged: () => void;
  onError: (m: string | null) => void;
}) {
  const env = card[environment];
  const lastTest =
    environment === "sandbox" ? card.last_test_sandbox : card.last_test_production;
  const isActive = card.active_environment === environment;

  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [recentTest, setRecentTest] = useState<{
    ok: boolean;
    detail: string;
  } | null>(null);

  // Reset draft when the card refreshes (e.g. after save).
  useEffect(() => {
    setDraft({});
  }, [card]);

  function setField(key: string, value: string) {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }

  async function save() {
    if (Object.keys(draft).length === 0) return;
    setSaving(true);
    onError(null);
    try {
      await api.patchIntegrationCredentials(
        card.integration_key,
        environment,
        draft,
      );
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function runTest() {
    setTesting(true);
    setRecentTest(null);
    onError(null);
    try {
      const result = await api.testIntegration(card.integration_key, environment);
      setRecentTest({ ok: result.ok, detail: result.detail });
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Test failed.");
    } finally {
      setTesting(false);
    }
  }

  const dirty = Object.keys(draft).length > 0;

  return (
    <div className="bg-white p-5">
      <header className="mb-3 flex items-baseline justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold capitalize">
          <ShieldCheck className="h-3.5 w-3.5 text-slate-400" />
          {environment}
          {isActive && (
            <span className="rounded-sm bg-signal/15 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-ink">
              Active
            </span>
          )}
        </h3>
      </header>

      <div className="flex flex-col gap-2">
        {card.fields.map((field) => {
          const isCred = field.kind === "credential";
          const isPresent = isCred && env.credential_present[field.key];
          const draftValue = draft[field.key];
          const value = draftValue ?? (isCred ? "" : env.values[field.key] ?? "");

          return (
            <label key={field.key} className="flex flex-col gap-1 text-2xs">
              <div className="flex items-center justify-between">
                <span className="font-medium text-ink">{field.label}</span>
                {isCred && isPresent && draftValue === undefined && (
                  <span className="text-[10px] text-success">Configured</span>
                )}
                {isCred && !isPresent && (
                  <span className="text-[10px] text-slate-400">Not set</span>
                )}
              </div>
              <input
                type={isCred ? "password" : "text"}
                disabled={!canManage}
                value={value}
                onChange={(e) => setField(field.key, e.target.value)}
                placeholder={
                  isCred && isPresent
                    ? "•••••••• (leave empty to keep)"
                    : field.placeholder
                }
                className={cn(
                  "rounded-md border bg-white px-2 py-1.5 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink",
                  draftValue !== undefined
                    ? "border-amber-200 ring-1 ring-amber-200"
                    : "border-slate-200",
                  !canManage && "bg-slate-50",
                )}
              />
            </label>
          );
        })}
      </div>

      {canManage && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={!dirty || saving} onClick={save}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
            {dirty && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setDraft({})}
                disabled={saving}
              >
                Discard
              </Button>
            )}
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={runTest}
            disabled={testing}
          >
            {testing ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Testing…
              </>
            ) : (
              <>
                <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                Test connection
              </>
            )}
          </Button>
        </div>
      )}

      {(recentTest || lastTest) && (
        <TestOutcomePanel
          outcome={recentTest ?? lastTest}
          isFresh={Boolean(recentTest)}
          lastTestAt={lastTest?.at}
        />
      )}
    </div>
  );
}

function TestOutcomePanel({
  outcome,
  isFresh,
  lastTestAt,
}: {
  outcome: { ok: boolean; detail: string } | null;
  isFresh: boolean;
  lastTestAt?: string;
}) {
  if (!outcome) return null;
  const Icon = outcome.ok ? CheckCircle2 : AlertCircle;
  return (
    <div
      className={cn(
        "mt-3 flex items-start gap-2 rounded-md border px-3 py-2 text-2xs",
        outcome.ok
          ? "border-success/30 bg-success/5 text-success"
          : "border-error/30 bg-error/5 text-error",
      )}
    >
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <div>
        <p className="font-medium">
          {outcome.ok ? "Connection OK" : "Test failed"}
        </p>
        <p className="mt-0.5 text-[11px] text-slate-600">{outcome.detail}</p>
        {!isFresh && lastTestAt && (
          <p className="mt-0.5 text-[10px] text-slate-400">
            Last tested {new Date(lastTestAt).toLocaleString()}
          </p>
        )}
      </div>
    </div>
  );
}

function Loading() {
  return (
    <div className="grid place-items-center px-5 py-12 text-2xs uppercase tracking-wider text-slate-400">
      Loading integrations…
    </div>
  );
}

function EmptyState() {
  return (
    <div className="grid place-items-center px-5 py-12 text-center">
      <PlugZap className="h-6 w-6 text-slate-300" aria-hidden />
      <p className="mt-2 text-2xs text-slate-500">
        No integrations yet.
      </p>
    </div>
  );
}

// Slice 59B — LHDN signing certificate card.
//
// Three states:
//   1. No cert at all (rare — Slice 58 auto-mints on first sign).
//   2. Self-signed dev cert active.
//   3. Customer-uploaded LHDN cert active.
//
// Upload form accepts PEM-encoded cert + private key. Validation
// happens server-side (matched RSA pair check); the FE just posts.
function CertificateCard({
  canManage,
  onError,
}: {
  canManage: boolean;
  onError: (m: string | null) => void;
}) {
  type CertState = {
    uploaded: boolean;
    kind: string;
    subject_common_name: string;
    serial_hex: string;
    expires_at: string | null;
  };
  const [state, setState] = useState<CertState | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [certPem, setCertPem] = useState("");
  const [keyPem, setKeyPem] = useState("");
  const [uploading, setUploading] = useState(false);

  async function refresh() {
    try {
      setState(await api.getCertificate());
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to load cert.");
    }
  }

  useEffect(() => {
    refresh();
    // refresh() is stable inside this component closure; the
    // eslint exhaustive-deps rule wants it in the array but
    // including it would require a useCallback wrap that buys
    // nothing here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onUpload() {
    if (!certPem.trim() || !keyPem.trim()) return;
    setUploading(true);
    onError(null);
    try {
      await api.uploadCertificate(certPem.trim(), keyPem.trim());
      setShowForm(false);
      setCertPem("");
      setKeyPem("");
      refresh();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  const isSelfSigned = state?.kind === "self_signed_dev";
  const isUploaded = state?.kind === "uploaded";

  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-ink/[0.05] p-2">
            <FileKey2 className="h-4 w-4 text-ink" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-ink">
              LHDN signing certificate
            </h2>
            <p className="mt-1 max-w-xl text-2xs text-slate-500">
              Used to sign every invoice before submission to LHDN.
              We auto-generate a dev certificate so you can test end-
              to-end immediately. For LHDN production, upload a real
              certificate from a recognised Malaysian CA (MSC
              Trustgate, Pos Digicert, Telekom Applied Business).
            </p>
          </div>
        </div>
        {state && (
          <span
            className={cn(
              "rounded-md px-2 py-1 text-[10px] font-medium uppercase tracking-wider",
              isSelfSigned && "bg-warning/15 text-warning",
              isUploaded && "bg-success/15 text-success",
              !state.uploaded && "bg-slate-100 text-slate-500",
            )}
          >
            {isUploaded
              ? "Uploaded · production-ready"
              : isSelfSigned
                ? "Self-signed · sandbox only"
                : "Not configured"}
          </span>
        )}
      </header>

      <div className="px-5 py-4 text-2xs">
        {state && state.uploaded ? (
          <dl className="grid gap-2 sm:grid-cols-3">
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-slate-400">
                Subject
              </dt>
              <dd className="mt-0.5 text-ink">
                {state.subject_common_name || "—"}
              </dd>
            </div>
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-slate-400">
                Serial
              </dt>
              <dd className="mt-0.5 font-mono text-[11px] text-ink">
                {state.serial_hex || "—"}
              </dd>
            </div>
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-slate-400">
                Expires
              </dt>
              <dd className="mt-0.5 text-ink">
                {state.expires_at
                  ? new Date(state.expires_at).toLocaleDateString()
                  : "—"}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="text-slate-500">
            No certificate yet. Submit your first invoice to LHDN
            (sandbox) and a self-signed dev certificate will be
            generated automatically.
          </p>
        )}

        {canManage && !showForm && (
          <div className="mt-3">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setShowForm(true)}
            >
              <Upload className="mr-1.5 h-3.5 w-3.5" />
              {isUploaded ? "Replace certificate" : "Upload my LHDN certificate"}
            </Button>
          </div>
        )}

        {showForm && (
          <div className="mt-4 flex flex-col gap-3 rounded-md border border-slate-200 bg-slate-50/40 p-4">
            <p className="text-2xs text-slate-500">
              Paste the PEM-encoded certificate and the matching
              RSA private key. The private key is encrypted at rest;
              the platform only decrypts it in memory during a
              signing operation.
            </p>
            <label className="flex flex-col gap-1 text-2xs font-medium">
              Certificate (PEM)
              <textarea
                value={certPem}
                onChange={(e) => setCertPem(e.target.value)}
                rows={5}
                placeholder={"-----BEGIN CERTIFICATE-----\nMIID...\n-----END CERTIFICATE-----"}
                className="rounded-md border border-slate-200 bg-white px-2 py-1.5 font-mono text-[11px] focus:outline-none focus:ring-1 focus:ring-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-2xs font-medium">
              Private key (PEM)
              <textarea
                value={keyPem}
                onChange={(e) => setKeyPem(e.target.value)}
                rows={5}
                placeholder={"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"}
                className="rounded-md border border-slate-200 bg-white px-2 py-1.5 font-mono text-[11px] focus:outline-none focus:ring-1 focus:ring-ink"
              />
            </label>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                onClick={onUpload}
                disabled={
                  uploading || !certPem.trim() || !keyPem.trim()
                }
              >
                {uploading ? "Uploading…" : "Upload certificate"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setShowForm(false);
                  setCertPem("");
                  setKeyPem("");
                  onError(null);
                }}
                disabled={uploading}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
