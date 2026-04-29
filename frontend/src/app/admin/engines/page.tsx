"use client";

// Engine credentials management — the surface where the operator
// rotates per-engine API keys, swaps models, toggles status (active /
// degraded / archived), and adjusts cost baselines without touching
// .env or restarting workers.
//
// Credential VALUES are never returned by the API. The credential_keys
// map carries {key: bool} so the UI can show "set" vs "not set" badges,
// but the operator can only rotate (replace), not read. To clear a
// credential, submit an empty string for that key.

import { useEffect, useState } from "react";
import { Activity, CircleCheck, Settings, ShieldAlert, ShieldCheck } from "lucide-react";

import { api, type AdminEngine } from "@/lib/api";
import { AdminShell } from "@/components/admin/AdminShell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const STATUS_OPTIONS: AdminEngine["status"][] = ["active", "degraded", "archived"];

const CAPABILITY_LABEL: Record<string, string> = {
  text_extract: "Text extract",
  vision_extract: "Vision extract",
  field_structure: "Field structure",
  embed: "Embed",
  classify: "Classify",
};

export default function AdminEnginesPage() {
  const [engines, setEngines] = useState<AdminEngine[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);

  async function refresh() {
    try {
      const list = await api.adminListEngines();
      setEngines(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load engines.");
      setEngines([]);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <AdminShell>
      <div className="flex flex-col gap-6">
        <header className="flex items-end justify-between">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">Engines</h1>
            <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
              Adapter catalogue · credential rotation · status overrides
            </p>
          </div>
          {engines && (
            <div className="rounded-md bg-slate-100 px-3 py-1.5 text-2xs text-slate-600">
              <span className="inline-flex items-center gap-1.5">
                <Settings className="h-3.5 w-3.5" />
                <span className="font-medium">{engines.length}</span>
                <span>engine{engines.length === 1 ? "" : "s"}</span>
              </span>
            </div>
          )}
        </header>

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error"
          >
            {error}
          </div>
        )}

        <div className="grid gap-4">
          {engines === null ? (
            <Loading />
          ) : engines.length === 0 ? (
            <EmptyState />
          ) : (
            engines.map((engine) => (
              <EngineCard
                key={engine.id}
                engine={engine}
                expanded={editing === engine.id}
                onToggle={() => setEditing(editing === engine.id ? null : engine.id)}
                onChanged={() => {
                  setEditing(null);
                  refresh();
                }}
                onError={setError}
              />
            ))
          )}
        </div>
      </div>
    </AdminShell>
  );
}

function EngineCard({
  engine,
  expanded,
  onToggle,
  onChanged,
  onError,
}: {
  engine: AdminEngine;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
  onError: (msg: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-100 bg-white">
      <header className="flex items-start justify-between gap-4 px-4 py-3">
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-display text-base font-semibold text-ink">{engine.name}</span>
            <StatusPill status={engine.status} />
            <span className="rounded-sm bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-slate-500">
              {CAPABILITY_LABEL[engine.capability] || engine.capability}
            </span>
          </div>
          <div className="mt-1 text-2xs text-slate-500">
            <span className="text-slate-400">vendor</span> {engine.vendor} ·{" "}
            <span className="text-slate-400">model</span> {engine.model_identifier || "—"} ·{" "}
            <span className="text-slate-400">adapter</span> v{engine.adapter_version}
          </div>
          {engine.description && (
            <p className="mt-2 text-2xs text-slate-500">{engine.description}</p>
          )}
        </div>
        <div className="text-right text-2xs text-slate-500">
          <Activity className="ml-auto h-3.5 w-3.5 text-slate-400" />
          <div className="mt-1">
            <span className="font-medium text-ink">{engine.calls_last_7d ?? 0}</span> calls last 7d
          </div>
          {(engine.calls_last_7d ?? 0) > 0 && (
            <div className="text-[10px]">{engine.calls_success_last_7d ?? 0} succeeded</div>
          )}
        </div>
      </header>
      <div className="border-t border-slate-100 bg-slate-50 px-4 py-2">
        <div className="flex items-center justify-between">
          <CredentialSummary credentialKeys={engine.credential_keys} />
          <Button variant="ghost" size="sm" onClick={onToggle}>
            {expanded ? "Cancel" : "Edit"}
          </Button>
        </div>
      </div>
      {expanded && <EngineEditor engine={engine} onSaved={onChanged} onError={onError} />}
    </div>
  );
}

function CredentialSummary({ credentialKeys }: { credentialKeys: Record<string, boolean> }) {
  const keys = Object.keys(credentialKeys);
  if (keys.length === 0) {
    return (
      <span className="text-2xs text-slate-400">
        No credentials configured (engine may run on env fallbacks)
      </span>
    );
  }
  return (
    <ul className="flex flex-wrap items-center gap-1.5 text-[11px]">
      {keys.map((key) => (
        <li
          key={key}
          className={cn(
            "inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-mono",
            credentialKeys[key] ? "bg-success/10 text-success" : "bg-slate-200 text-slate-500",
          )}
        >
          {credentialKeys[key] ? (
            <CircleCheck className="h-3 w-3" aria-hidden />
          ) : (
            <ShieldAlert className="h-3 w-3" aria-hidden />
          )}
          {key}
        </li>
      ))}
    </ul>
  );
}

function StatusPill({ status }: { status: AdminEngine["status"] }) {
  const cls =
    status === "active"
      ? "bg-success/10 text-success"
      : status === "degraded"
        ? "bg-warning/10 text-warning"
        : "bg-slate-200 text-slate-500";
  const Icon = status === "active" ? ShieldCheck : status === "degraded" ? ShieldAlert : Settings;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${cls}`}
    >
      <Icon className="h-3 w-3" />
      {status}
    </span>
  );
}

function EngineEditor({
  engine,
  onSaved,
  onError,
}: {
  engine: AdminEngine;
  onSaved: () => void;
  onError: (msg: string) => void;
}) {
  const [status, setStatus] = useState<AdminEngine["status"]>(engine.status);
  const [model, setModel] = useState(engine.model_identifier);
  const [credValues, setCredValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  async function onSave() {
    setSaving(true);
    onError("");
    try {
      const fields: Record<string, unknown> = {};
      if (status !== engine.status) fields.status = status;
      if (model !== engine.model_identifier) fields.model_identifier = model;
      const credentials: Record<string, string> = {};
      for (const [key, value] of Object.entries(credValues)) {
        // Only include keys the operator actually edited.
        if (value !== "" || engine.credential_keys[key]) {
          credentials[key] = value;
        }
      }
      const hasFieldChanges = Object.keys(fields).length > 0;
      const hasCredChanges = Object.keys(credentials).length > 0;
      if (!hasFieldChanges && !hasCredChanges) {
        onSaved();
        return;
      }
      await api.adminUpdateEngine(engine.id, {
        fields: hasFieldChanges ? fields : undefined,
        credentials: hasCredChanges ? credentials : undefined,
      });
      onSaved();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  // Always show every credential key the engine knows about; an empty
  // input means "leave unchanged" (we only include it in the PATCH body
  // if the operator typed something).
  const credKeys = Object.keys(engine.credential_keys);

  return (
    <div className="border-t border-slate-100 bg-white px-4 py-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Status">
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as AdminEngine["status"])}
            className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink"
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Model identifier">
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="e.g. claude-sonnet-4-6"
            className="w-full rounded-md border border-slate-200 bg-white px-3 py-1.5 font-mono text-[11px] text-ink focus:outline-none focus:ring-1 focus:ring-ink"
          />
        </Field>
      </div>

      {credKeys.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-2xs font-medium uppercase tracking-wider text-slate-400">
            Credentials
          </div>
          <p className="mb-2 text-[11px] text-slate-500">
            Existing values are never returned by the API. Type a new value to rotate; leave blank
            to keep the current value; submit an empty string in a key&apos;s input to clear it.
          </p>
          <div className="grid gap-2">
            {credKeys.map((key) => (
              <div key={key} className="flex items-center gap-3">
                <code className="w-32 truncate font-mono text-[11px] text-slate-700">{key}</code>
                <input
                  type="text"
                  value={credValues[key] ?? ""}
                  onChange={(e) =>
                    setCredValues((prev) => ({
                      ...prev,
                      [key]: e.target.value,
                    }))
                  }
                  placeholder={engine.credential_keys[key] ? "•••• (set)" : "(unset)"}
                  className="flex-1 rounded-md border border-slate-200 bg-white px-3 py-1.5 font-mono text-[11px] text-ink focus:outline-none focus:ring-1 focus:ring-ink"
                />
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 flex items-center justify-end gap-2">
        <Button onClick={onSave} disabled={saving}>
          {saving ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-slate-400">
        {label}
      </div>
      {children}
    </div>
  );
}

function Loading() {
  return (
    <div className="grid place-items-center py-24 text-2xs uppercase tracking-wider text-slate-400">
      Loading engines…
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-12 text-center">
      <Settings className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
      <h2 className="mt-4 font-display text-xl font-semibold">No engines registered</h2>
      <p className="mx-auto mt-2 max-w-md text-2xs text-slate-500">
        The seed migration usually populates this. Run{" "}
        <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px]">
          make migrate
        </code>{" "}
        to repopulate.
      </p>
    </div>
  );
}
