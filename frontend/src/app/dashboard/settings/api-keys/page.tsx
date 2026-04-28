"use client";

// Settings → API keys tab. Customers create + revoke keys here. The
// plaintext is shown ONCE in a "save this now" modal at creation; the
// API never returns it again. The list shows label + prefix + status
// + last-used + created-at; revoke is a one-click action with no
// reason gate (the audit chain still records the actor).

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Copy,
  KeyRound,
  Plus,
  Trash2,
} from "lucide-react";

import { api, ApiError, type APIKeyRow } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { SettingsTabs } from "@/components/settings/SettingsTabs";
import { cn } from "@/lib/utils";

export default function ApiKeysSettingsPage() {
  const [keys, setKeys] = useState<APIKeyRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newPlaintext, setNewPlaintext] = useState<string | null>(null);
  const [newLabel, setNewLabel] = useState("");

  async function refresh() {
    try {
      const list = await api.listApiKeys();
      setKeys(list);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError("You are not a member of this organization.");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load API keys.");
      setKeys([]);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onCreate() {
    if (!newLabel.trim()) {
      setError("A label is required.");
      return;
    }
    setError(null);
    try {
      const result = await api.createApiKey(newLabel.trim());
      setNewPlaintext(result.plaintext);
      setNewLabel("");
      setCreating(false);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed.");
    }
  }

  async function onRevoke(id: string) {
    setError(null);
    try {
      await api.revokeApiKey(id);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Revoke failed.");
    }
  }

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

        {newPlaintext && (
          <NewKeyAlert
            plaintext={newPlaintext}
            onDismiss={() => setNewPlaintext(null)}
          />
        )}

        <section className="rounded-xl border border-slate-100 bg-white">
          <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div className="flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-slate-400" />
              <h2 className="text-sm font-semibold text-ink">
                API keys ({keys?.filter((k) => k.is_active).length ?? 0} active)
              </h2>
            </div>
            <Button
              size="sm"
              onClick={() => setCreating(!creating)}
              disabled={!!newPlaintext}
            >
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              {creating ? "Cancel" : "New key"}
            </Button>
          </header>

          {creating && (
            <div className="border-b border-slate-100 bg-slate-50 px-5 py-4">
              <p className="mb-2 text-2xs text-slate-500">
                Pick a label that helps you identify the key later (e.g.
                <span className="font-mono"> ci-pipeline</span>,
                <span className="font-mono"> zapier-prod</span>). The
                plaintext key is shown once after creation — copy it
                somewhere safe before you close the dialog.
              </p>
              <div className="flex flex-wrap gap-2">
                <input
                  type="text"
                  value={newLabel}
                  onChange={(e) => setNewLabel(e.target.value)}
                  placeholder="ci-pipeline"
                  className="flex-1 min-w-0 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink"
                />
                <Button
                  size="sm"
                  onClick={onCreate}
                  disabled={!newLabel.trim()}
                >
                  Create key
                </Button>
              </div>
            </div>
          )}

          {keys === null ? (
            <Loading />
          ) : keys.length === 0 ? (
            <EmptyState />
          ) : (
            <ul className="divide-y divide-slate-100">
              {keys.map((k) => (
                <li
                  key={k.id}
                  className={cn(
                    "flex flex-col gap-1 px-5 py-3 text-2xs",
                    !k.is_active && "opacity-60",
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex flex-1 items-center gap-3 min-w-0">
                      <span className="font-medium text-ink truncate">
                        {k.label}
                      </span>
                      <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
                        {k.key_prefix}…
                      </code>
                      {!k.is_active && (
                        <span className="rounded-sm bg-slate-200 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-slate-500">
                          Revoked
                        </span>
                      )}
                    </div>
                    <span className="text-[10px] text-slate-400">
                      Created{" "}
                      {k.created_at
                        ? new Date(k.created_at).toLocaleDateString()
                        : "—"}
                    </span>
                    {k.is_active && (
                      <button
                        type="button"
                        onClick={() => onRevoke(k.id)}
                        aria-label={`Revoke ${k.label}`}
                        className="rounded-md p-1 text-slate-400 hover:bg-error/10 hover:text-error"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                  <div className="text-[10px] text-slate-400">
                    {k.last_used_at
                      ? `Last used ${new Date(k.last_used_at).toLocaleString()}`
                      : "Never used"}
                    {k.revoked_at &&
                      ` · Revoked ${new Date(k.revoked_at).toLocaleDateString()}`}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </AppShell>
  );
}

function NewKeyAlert({
  plaintext,
  onDismiss,
}: {
  plaintext: string;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(plaintext);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Browser blocked clipboard write — user will need to select + copy.
    }
  }
  return (
    <div
      role="alert"
      className="rounded-xl border border-warning/40 bg-warning/5 p-4"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-warning" />
        <div className="flex-1">
          <h3 className="font-display text-sm font-semibold text-ink">
            Save this key now — you won&apos;t see it again.
          </h3>
          <p className="mt-1 text-2xs text-slate-600">
            We only store a hash of the key. If you lose it, revoke and
            create a new one.
          </p>
          <div className="mt-3 flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2">
            <code className="flex-1 truncate font-mono text-[11px] text-slate-700">
              {plaintext}
            </code>
            <button
              type="button"
              onClick={copy}
              className="inline-flex items-center gap-1 rounded-md bg-ink px-2.5 py-1 text-2xs font-medium text-paper hover:opacity-90"
            >
              <Copy className="h-3 w-3" />
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <div className="mt-3 flex justify-end">
            <Button size="sm" variant="ghost" onClick={onDismiss}>
              I&apos;ve saved it
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Loading() {
  return (
    <div className="grid place-items-center px-5 py-12 text-2xs uppercase tracking-wider text-slate-400">
      Loading API keys…
    </div>
  );
}

function EmptyState() {
  return (
    <div className="grid place-items-center px-5 py-12 text-center">
      <KeyRound className="h-6 w-6 text-slate-300" aria-hidden />
      <p className="mt-2 max-w-md text-2xs text-slate-500">
        No API keys yet. Click <span className="font-medium">New key</span>{" "}
        above to create one for your CI pipeline, Zapier, or any other
        integration that needs programmatic access.
      </p>
    </div>
  );
}
