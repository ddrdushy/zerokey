"use client";

// Admin system settings — every platform-wide configuration namespace
// (LHDN MyInvois, Stripe billing, Email/SMTP, branding, engine defaults)
// editable from one screen. Each namespace has a schema (key + label +
// kind) so the UI renders consistently without per-namespace logic.
//
// Credentials are write-only — the API never returns plaintext values
// for them. The UI shows "•••• (set)" / "(unset)" placeholders and
// rotates by accepting a new value; an empty submit clears the key.
// Same contract the engine credentials surface uses.

import { useEffect, useState } from "react";
import {
  CircleCheck,
  Cog,
  CreditCard,
  Database,
  Globe,
  Mail,
  ShieldAlert,
} from "lucide-react";

import { api, type SystemSettingNamespace } from "@/lib/api";
import { AdminShell } from "@/components/admin/AdminShell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const NAMESPACE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  lhdn: Database,
  stripe: CreditCard,
  email: Mail,
  branding: Globe,
  engine_defaults: Cog,
};

export default function AdminSettingsPage() {
  const [namespaces, setNamespaces] = useState<SystemSettingNamespace[] | null>(
    null,
  );
  const [activeNs, setActiveNs] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const list = await api.adminListSystemSettings();
      setNamespaces(list);
      if (!activeNs && list.length > 0) {
        setActiveNs(list[0].namespace);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load.");
      setNamespaces([]);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const active = namespaces?.find((n) => n.namespace === activeNs) ?? null;

  return (
    <AdminShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            System settings
          </h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            Platform-wide configuration · cross-tenant
          </p>
        </header>

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error"
          >
            {error}
          </div>
        )}

        <div className="flex flex-col gap-6 md:flex-row">
          <NamespaceTabs
            namespaces={namespaces}
            active={activeNs}
            onPick={setActiveNs}
          />
          <div className="flex-1">
            {namespaces === null ? (
              <Loading />
            ) : active ? (
              <NamespaceEditor
                key={active.namespace}
                ns={active}
                onSaved={refresh}
                onError={setError}
              />
            ) : (
              <div className="grid place-items-center py-24 text-2xs uppercase tracking-wider text-slate-400">
                Pick a namespace.
              </div>
            )}
          </div>
        </div>
      </div>
    </AdminShell>
  );
}

function NamespaceTabs({
  namespaces,
  active,
  onPick,
}: {
  namespaces: SystemSettingNamespace[] | null;
  active: string | null;
  onPick: (ns: string) => void;
}) {
  if (!namespaces) {
    return (
      <aside className="flex w-full flex-col gap-1 md:w-56">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="h-10 animate-pulse rounded-md border border-slate-100 bg-slate-50"
          />
        ))}
      </aside>
    );
  }
  return (
    <aside className="flex w-full flex-col gap-1 md:w-56">
      {namespaces.map((ns) => {
        const Icon = NAMESPACE_ICON[ns.namespace] ?? Cog;
        const isActive = ns.namespace === active;
        const credCount = Object.values(ns.credential_keys).filter(Boolean)
          .length;
        const credTotal = Object.keys(ns.credential_keys).length;
        return (
          <button
            key={ns.namespace}
            type="button"
            onClick={() => onPick(ns.namespace)}
            className={cn(
              "flex items-start gap-3 rounded-md border px-3 py-2 text-left transition",
              isActive
                ? "border-ink/30 bg-white shadow-sm"
                : "border-transparent hover:bg-slate-50",
            )}
          >
            <Icon
              className={cn(
                "mt-0.5 h-4 w-4 flex-shrink-0",
                isActive ? "text-ink" : "text-slate-400",
              )}
            />
            <div className="flex-1">
              <div className="text-2xs font-medium text-ink">{ns.label}</div>
              <div className="mt-0.5 text-[10px] text-slate-400">
                {credTotal > 0 ? (
                  <span
                    className={cn(
                      credCount === credTotal && "text-success",
                      credCount === 0 && "text-warning",
                    )}
                  >
                    {credCount}/{credTotal} credentials set
                  </span>
                ) : (
                  "No credentials"
                )}
              </div>
            </div>
          </button>
        );
      })}
    </aside>
  );
}

function NamespaceEditor({
  ns,
  onSaved,
  onError,
}: {
  ns: SystemSettingNamespace;
  onSaved: () => void;
  onError: (msg: string | null) => void;
}) {
  // Editable field state. For non-credentials we initialize from values;
  // for credentials we ALWAYS start blank so the operator either rotates
  // (typed value) or leaves alone (blank).
  const initialFormValues = (() => {
    const out: Record<string, string> = {};
    for (const f of ns.fields) {
      if (f.kind === "credential") {
        out[f.key] = "";
      } else {
        out[f.key] = ns.values[f.key] ?? "";
      }
    }
    return out;
  })();

  const [form, setForm] = useState<Record<string, string>>(initialFormValues);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  function update(key: string, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function onSave() {
    if (!reason.trim()) {
      onError("A reason is required for system-setting changes.");
      return;
    }
    setSaving(true);
    onError(null);
    try {
      // Build fields payload:
      //   - non-credential: send if changed from current value
      //   - credential:     send if non-empty (rotate) OR if explicitly
      //                     emptied AFTER the user touched it. (We can't
      //                     tell "didn't touch" from "cleared" with our
      //                     state, so we treat blank as "leave alone"
      //                     unless the field was previously set and the
      //                     user clicks the Clear button below.)
      const fields: Record<string, string> = {};
      for (const f of ns.fields) {
        const current = ns.values[f.key] ?? "";
        const next = form[f.key] ?? "";
        if (f.kind === "credential") {
          if (next) fields[f.key] = next;
        } else if (next !== current) {
          fields[f.key] = next;
        }
      }
      if (Object.keys(fields).length === 0) {
        // Nothing actually changed — give the operator some feedback
        // rather than a silent no-op.
        onError("No changes to save.");
        return;
      }
      await api.adminUpdateSystemSetting(ns.namespace, {
        fields,
        reason: reason.trim(),
      });
      setReason("");
      onSaved();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function clearCredential(key: string) {
    if (!reason.trim()) {
      onError("A reason is required to clear a credential.");
      return;
    }
    setSaving(true);
    onError(null);
    try {
      await api.adminUpdateSystemSetting(ns.namespace, {
        fields: { [key]: "" },
        reason: reason.trim(),
      });
      setReason("");
      onSaved();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Clear failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <header className="border-b border-slate-100 px-5 py-4">
        <h2 className="font-display text-lg font-semibold text-ink">
          {ns.label}
        </h2>
        <p className="mt-1 text-2xs text-slate-500">{ns.description}</p>
        {ns.updated_at && (
          <p className="mt-1 text-[10px] text-slate-400">
            Last updated {new Date(ns.updated_at).toLocaleString()}
          </p>
        )}
      </header>
      <div className="grid gap-3 px-5 py-4 md:grid-cols-2">
        {ns.fields.map((field) => (
          <FieldEditor
            key={field.key}
            field={field}
            value={form[field.key] ?? ""}
            isSet={
              field.kind === "credential"
                ? Boolean(ns.credential_keys[field.key])
                : Boolean(ns.values[field.key])
            }
            onChange={(v) => update(field.key, v)}
            onClear={
              field.kind === "credential" && ns.credential_keys[field.key]
                ? () => clearCredential(field.key)
                : undefined
            }
            saving={saving}
          />
        ))}
      </div>
      <footer className="border-t border-slate-100 px-5 py-4">
        <p className="mb-2 text-[11px] text-slate-500">
          Privileged action — every change is audited under your staff
          identity. A reason is required.
        </p>
        <input
          type="text"
          placeholder="Reason (e.g. production cutover, key rotation)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="w-full rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink"
        />
        <div className="mt-3 flex items-center justify-end">
          <Button onClick={onSave} disabled={saving}>
            {saving ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </footer>
    </section>
  );
}

function FieldEditor({
  field,
  value,
  isSet,
  onChange,
  onClear,
  saving,
}: {
  field: { key: string; label: string; kind: string; placeholder?: string };
  value: string;
  isSet: boolean;
  onChange: (v: string) => void;
  onClear?: () => void;
  saving: boolean;
}) {
  const isCred = field.kind === "credential";
  return (
    <label className="flex flex-col gap-1 text-2xs">
      <div className="flex items-center justify-between">
        <span className="font-medium uppercase tracking-wider text-slate-400">
          {field.label}
        </span>
        {isCred && (
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider",
              isSet
                ? "bg-success/10 text-success"
                : "bg-slate-100 text-slate-500",
            )}
          >
            {isSet ? (
              <>
                <CircleCheck className="h-3 w-3" /> Set
              </>
            ) : (
              <>
                <ShieldAlert className="h-3 w-3" /> Unset
              </>
            )}
          </span>
        )}
      </div>
      <input
        type={isCred ? "password" : "text"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={
          isCred
            ? isSet
              ? "•••• (set — type to rotate)"
              : "(unset)"
            : (field.placeholder ?? "")
        }
        className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink"
      />
      {onClear && (
        <button
          type="button"
          onClick={onClear}
          disabled={saving}
          className="self-end text-[10px] font-medium text-slate-500 underline-offset-4 hover:text-error hover:underline disabled:opacity-50"
        >
          Clear value
        </button>
      )}
    </label>
  );
}

function Loading() {
  return (
    <div className="grid place-items-center py-24 text-2xs uppercase tracking-wider text-slate-400">
      Loading settings…
    </div>
  );
}
