"use client";

// Settings → SSO (Slice 97). Configure an OpenID Connect identity
// provider for the active organisation. One provider per org in v1;
// the panel renders empty-state with a "Configure" CTA when none is
// set, otherwise an editable form with a "Disconnect" affordance.

import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { SettingsTabs } from "@/components/settings/SettingsTabs";
import { Button } from "@/components/ui/button";

type Provider = {
  id: string;
  label: string;
  is_active: boolean;
  issuer: string;
  client_id: string;
  client_secret_set: boolean;
  scopes: string;
  allowed_email_domains: string[];
  jit_provision: boolean;
  default_role: string | null;
  last_login_at: string | null;
};

const ROLES = ["owner", "admin", "approver", "submitter", "viewer"] as const;

export default function SsoSettingsPage() {
  const [provider, setProvider] = useState<Provider | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [draft, setDraft] = useState<Partial<Provider> & { client_secret?: string }>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api
      .getOidcProvider()
      .then((data) => {
        setProvider((data.provider as Provider | null) ?? null);
        if (data.provider) {
          setDraft({});
        } else {
          // Sensible defaults for a new IdP
          setDraft({
            label: "OIDC SSO",
            scopes: "openid email profile",
            jit_provision: true,
            default_role: "submitter",
            is_active: true,
            allowed_email_domains: [],
          });
        }
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          setForbidden(true);
        } else {
          setError(err instanceof Error ? err.message : "Failed to load SSO settings.");
        }
      })
      .finally(() => setLoading(false));
  }, []);

  function value<K extends keyof Provider>(key: K): Provider[K] | undefined {
    if (key in draft) return draft[key as keyof typeof draft] as Provider[K];
    return provider?.[key];
  }

  function setField<K extends keyof Provider>(key: K, v: Provider[K]) {
    setDraft((prev) => ({ ...prev, [key]: v }));
  }

  async function onSave() {
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {};
      const keys: (keyof Provider | "client_secret")[] = [
        "label",
        "is_active",
        "issuer",
        "client_id",
        "scopes",
        "allowed_email_domains",
        "jit_provision",
        "default_role",
        "client_secret",
      ];
      for (const k of keys) {
        if (k in draft) body[k] = (draft as Record<string, unknown>)[k];
      }
      const method = provider ? "PATCH" : "POST";
      const result = await api.upsertOidcProvider(body, method);
      setProvider(result.provider as Provider);
      setDraft({});
      setSavedAt(Date.now());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function onDisconnect() {
    if (!confirm("Disconnect SSO? Existing users keep their accounts; new sign-ins will require a password.")) return;
    setSaving(true);
    setError(null);
    try {
      await api.deleteOidcProvider();
      setProvider(null);
      setDraft({
        label: "OIDC SSO",
        scopes: "openid email profile",
        jit_provision: true,
        default_role: "submitter",
        is_active: true,
        allowed_email_domains: [],
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Disconnect failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">Settings</h1>
        </header>
        <SettingsTabs />

        <section className="flex flex-col gap-4">
          <div>
            <h2 className="font-display text-xl font-semibold">Single sign-on (OIDC)</h2>
            <p className="mt-1 max-w-2xl text-sm text-slate-600">
              Delegate authentication to your existing identity provider — Google
              Workspace, Okta, Auth0, Azure AD, or any OIDC-compliant IdP. Users
              type their email on the sign-in page and click <em>Sign in with SSO</em>.
            </p>
          </div>

          {loading ? (
            <div className="grid place-items-center py-12 text-slate-400">Loading…</div>
          ) : forbidden ? (
            <div className="rounded-md border border-warning/30 bg-warning/5 px-4 py-3 text-sm text-slate-600">
              Only owners or admins can manage SSO.
            </div>
          ) : (
            <div className="grid gap-4 rounded-xl border border-slate-100 bg-white p-6">
              <Field
                label="Label"
                hint="Shown only in the admin UI — pick something you'll recognise (e.g. 'Okta', 'Google Workspace')."
                value={value("label") ?? ""}
                onChange={(v) => setField("label", v)}
              />
              <Field
                label="Issuer URL"
                hint="The base URL — we'll fetch /.well-known/openid-configuration from here. Examples: https://accounts.google.com, https://your-tenant.okta.com."
                value={value("issuer") ?? ""}
                onChange={(v) => setField("issuer", v)}
                required
              />
              <Field
                label="Client ID"
                hint="From your IdP's app registration."
                value={value("client_id") ?? ""}
                onChange={(v) => setField("client_id", v)}
                required
              />
              <Field
                label="Client secret"
                hint={
                  provider?.client_secret_set
                    ? "Already set. Leave blank to keep the existing secret; type a new value to rotate."
                    : "From your IdP's app registration. Encrypted at rest."
                }
                value={(draft.client_secret as string) ?? ""}
                onChange={(v) => setField("client_secret" as keyof Provider, v as never)}
                type="password"
                placeholder={provider?.client_secret_set ? "•••••••• (leave blank to keep)" : ""}
              />
              <Field
                label="Scopes"
                hint="Space-separated. ``openid`` is always requested; ``email`` and ``profile`` are recommended."
                value={value("scopes") ?? ""}
                onChange={(v) => setField("scopes", v)}
              />
              <Field
                label="Allowed email domains"
                hint="Comma-separated. Only emails ending in one of these domains can SSO. Leave empty to accept any email the IdP returns."
                value={(value("allowed_email_domains") ?? []).join(", ")}
                onChange={(v) =>
                  setField(
                    "allowed_email_domains",
                    v.split(",").map((s) => s.trim()).filter(Boolean),
                  )
                }
              />

              <div className="flex flex-col gap-1">
                <label className="text-2xs font-medium uppercase tracking-wider text-slate-400">
                  Default role for new users
                </label>
                <select
                  value={value("default_role") ?? "submitter"}
                  onChange={(e) => setField("default_role", e.target.value)}
                  className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-ink focus:border-ink focus:outline-none"
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
                <span className="text-2xs text-slate-400">
                  When a user signs in via SSO and isn&apos;t already a member of this org,
                  they&apos;re auto-provisioned with this role.
                </span>
              </div>

              <Toggle
                label="JIT-provision new users"
                hint="Auto-create accounts for emails the IdP authenticates. Disable to require manual invitations first."
                value={!!value("jit_provision")}
                onChange={(v) => setField("jit_provision", v)}
              />
              <Toggle
                label="Active"
                hint="Disable to temporarily turn off SSO without deleting the configuration."
                value={!!value("is_active")}
                onChange={(v) => setField("is_active", v)}
              />

              {error && (
                <div role="alert" className="rounded-md border border-error bg-error/5 px-4 py-2 text-xs text-error">
                  {error}
                </div>
              )}
              {savedAt && (
                <div className="text-2xs text-success">
                  Saved {new Date(savedAt).toLocaleTimeString()}.
                </div>
              )}

              <div className="flex flex-wrap gap-3">
                <Button onClick={onSave} disabled={saving}>
                  {saving ? "Saving…" : provider ? "Save changes" : "Connect SSO"}
                </Button>
                {provider && (
                  <Button variant="outline" onClick={onDisconnect} disabled={saving}>
                    Disconnect
                  </Button>
                )}
              </div>

              {provider && (
                <p className="text-2xs text-slate-400">
                  Last SSO login:{" "}
                  {provider.last_login_at
                    ? new Date(provider.last_login_at).toLocaleString()
                    : "never"}
                </p>
              )}
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}

function Field({
  label,
  hint,
  value,
  onChange,
  type = "text",
  placeholder,
  required,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        {label}
        {required && <span className="ml-1 text-error">*</span>}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-ink focus:border-ink focus:outline-none"
      />
      {hint && <span className="text-2xs text-slate-400">{hint}</span>}
    </label>
  );
}

function Toggle({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="flex items-center gap-3 text-sm text-ink">
        <input
          type="checkbox"
          checked={value}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 rounded border-slate-300 text-ink focus:ring-ink"
        />
        {label}
      </span>
      {hint && <span className="ml-7 text-2xs text-slate-400">{hint}</span>}
    </label>
  );
}
