"use client";

// Settings → Webhooks tab. Customers register endpoints + see
// recent deliveries. The signing secret is shown ONCE at creation
// (same write-only contract as API keys). Test delivery sends a
// synthetic ping (real outbound HTTP wires in a follow-up).

import { useEffect, useState } from "react";
import { AlertTriangle, Copy, Plus, Send, Trash2, Webhook } from "lucide-react";

import { api, ApiError, type WebhookDeliveryRow, type WebhookEndpointRow } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { SettingsTabs } from "@/components/settings/SettingsTabs";
import { cn } from "@/lib/utils";

type AvailableEvent = { key: string; label: string };

export default function WebhooksSettingsPage() {
  const [endpoints, setEndpoints] = useState<WebhookEndpointRow[] | null>(null);
  const [available, setAvailable] = useState<AvailableEvent[]>([]);
  const [deliveries, setDeliveries] = useState<WebhookDeliveryRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [newEvents, setNewEvents] = useState<string[]>([]);
  const [newSecret, setNewSecret] = useState<string | null>(null);

  async function refresh() {
    try {
      const [list, deliv] = await Promise.all([
        api.listWebhooks(),
        api.listWebhookDeliveries({ limit: 20 }),
      ]);
      setEndpoints(list.results);
      setAvailable(list.available_events);
      setDeliveries(deliv.results);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError("You are not a member of this organization.");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load.");
      setEndpoints([]);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onCreate() {
    if (!newLabel.trim() || !newUrl.trim()) {
      setError("Label and URL are required.");
      return;
    }
    setError(null);
    try {
      const result = await api.createWebhook({
        label: newLabel.trim(),
        url: newUrl.trim(),
        event_types: newEvents,
      });
      setNewSecret(result.plaintext_secret);
      setNewLabel("");
      setNewUrl("");
      setNewEvents([]);
      setCreating(false);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed.");
    }
  }

  async function onTest(webhookId: string) {
    setError(null);
    try {
      await api.testWebhook(webhookId);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test failed.");
    }
  }

  async function onRevoke(webhookId: string) {
    setError(null);
    try {
      await api.revokeWebhook(webhookId);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Revoke failed.");
    }
  }

  function toggleEvent(key: string) {
    setNewEvents((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  }

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">Settings</h1>
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

        {newSecret && <NewSecretAlert plaintext={newSecret} onDismiss={() => setNewSecret(null)} />}

        <section className="rounded-xl border border-slate-100 bg-white">
          <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div className="flex items-center gap-2">
              <Webhook className="h-4 w-4 text-slate-400" />
              <h2 className="text-sm font-semibold text-ink">Webhook endpoints</h2>
            </div>
            <Button size="sm" onClick={() => setCreating(!creating)} disabled={!!newSecret}>
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              {creating ? "Cancel" : "New endpoint"}
            </Button>
          </header>
          {creating && (
            <div className="border-b border-slate-100 bg-slate-50 px-5 py-4">
              <p className="mb-2 text-2xs text-slate-500">
                We&apos;ll POST a JSON payload to your URL whenever any of the selected events
                fires. The signing secret is shown once after creation; verify deliveries with
                <code className="mx-1 rounded bg-slate-200 px-1 py-0.5 font-mono text-[10px]">
                  HMAC-SHA256(secret, payload)
                </code>
                .
              </p>
              <div className="grid gap-2 md:grid-cols-2">
                <input
                  type="text"
                  value={newLabel}
                  onChange={(e) => setNewLabel(e.target.value)}
                  placeholder="zapier-prod"
                  className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink"
                />
                <input
                  type="url"
                  value={newUrl}
                  onChange={(e) => setNewUrl(e.target.value)}
                  placeholder="https://hooks.example.com/zk"
                  className="rounded-md border border-slate-200 bg-white px-3 py-1.5 font-mono text-[11px] text-ink focus:outline-none focus:ring-1 focus:ring-ink"
                />
              </div>
              <div className="mt-3">
                <p className="mb-1 text-[10px] uppercase tracking-wider text-slate-400">Events</p>
                <div className="flex flex-wrap gap-1.5">
                  {available.map((e) => {
                    const checked = newEvents.includes(e.key);
                    return (
                      <button
                        key={e.key}
                        type="button"
                        onClick={() => toggleEvent(e.key)}
                        className={cn(
                          "rounded-sm px-2 py-1 text-[10px] uppercase tracking-wider transition",
                          checked
                            ? "bg-ink text-paper"
                            : "bg-slate-100 text-slate-500 hover:bg-slate-200",
                        )}
                      >
                        {e.label}
                      </button>
                    );
                  })}
                </div>
                <p className="mt-2 text-[10px] text-slate-400">
                  No selection = receive every event.
                </p>
              </div>
              <div className="mt-3 flex justify-end">
                <Button size="sm" onClick={onCreate}>
                  Create endpoint
                </Button>
              </div>
            </div>
          )}

          {endpoints === null ? (
            <Loading />
          ) : endpoints.length === 0 ? (
            <EmptyState />
          ) : (
            <ul className="divide-y divide-slate-100">
              {endpoints.map((e) => (
                <li
                  key={e.id}
                  className={cn(
                    "flex flex-col gap-1 px-5 py-3 text-2xs",
                    !e.is_active && "opacity-60",
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium text-ink">{e.label}</div>
                      <div className="truncate font-mono text-[10px] text-slate-500">{e.url}</div>
                    </div>
                    <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-700">
                      {e.secret_prefix}…
                    </code>
                    {!e.is_active && (
                      <span className="rounded-sm bg-slate-200 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-slate-500">
                        Revoked
                      </span>
                    )}
                    {e.is_active && (
                      <>
                        <button
                          type="button"
                          onClick={() => onTest(e.id)}
                          aria-label={`Send test to ${e.label}`}
                          className="rounded-md p-1 text-slate-400 hover:bg-signal/15 hover:text-ink"
                        >
                          <Send className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => onRevoke(e.id)}
                          aria-label={`Revoke ${e.label}`}
                          className="rounded-md p-1 text-slate-400 hover:bg-error/10 hover:text-error"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </>
                    )}
                  </div>
                  {e.event_types.length > 0 && (
                    <div className="flex flex-wrap gap-1 text-[9px]">
                      {e.event_types.map((t) => (
                        <span
                          key={t}
                          className="rounded-sm bg-slate-100 px-1 py-0.5 font-mono text-slate-600"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <DeliveriesSection deliveries={deliveries} />
      </div>
    </AppShell>
  );
}

function NewSecretAlert({ plaintext, onDismiss }: { plaintext: string; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(plaintext);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // No-op.
    }
  }
  return (
    <div role="alert" className="rounded-xl border border-warning/40 bg-warning/5 p-4">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-warning" />
        <div className="flex-1">
          <h3 className="font-display text-sm font-semibold text-ink">
            Save this signing secret now — you won&apos;t see it again.
          </h3>
          <p className="mt-1 text-2xs text-slate-600">
            Receivers verify deliveries with{" "}
            <code className="rounded bg-slate-200 px-1 py-0.5 font-mono text-[10px]">
              HMAC-SHA256(secret, payload_body)
            </code>
            .
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

function DeliveriesSection({ deliveries }: { deliveries: WebhookDeliveryRow[] }) {
  return (
    <section className="rounded-xl border border-slate-100 bg-white">
      <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-2">
          <Send className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-semibold text-ink">Recent deliveries</h2>
        </div>
        <span className="text-[10px] uppercase tracking-wider text-slate-400">
          Worker not yet wired — test deliveries are synthetic
        </span>
      </header>
      {deliveries.length === 0 ? (
        <div className="px-5 py-8 text-center text-2xs text-slate-400">
          No deliveries yet. Hit the test button on an endpoint to create a synthetic one.
        </div>
      ) : (
        <table className="w-full text-2xs">
          <thead className="bg-slate-50 text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Event</th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Outcome</th>
              <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">Status</th>
              <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">Attempt</th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">When</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {deliveries.map((d) => (
              <tr key={d.id}>
                <td className="px-3 py-2">
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-700">
                    {d.event_type}
                  </code>
                </td>
                <td className="px-3 py-2">
                  <OutcomeBadge outcome={d.outcome} />
                </td>
                <td className="px-3 py-2 text-right text-slate-500">{d.response_status ?? "—"}</td>
                <td className="px-3 py-2 text-right text-slate-500">#{d.attempt}</td>
                <td className="px-3 py-2 text-slate-500">
                  {d.delivered_at ? new Date(d.delivered_at).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function OutcomeBadge({ outcome }: { outcome: WebhookDeliveryRow["outcome"] }) {
  const cls =
    outcome === "success"
      ? "bg-success/10 text-success"
      : outcome === "failure" || outcome === "abandoned"
        ? "bg-error/10 text-error"
        : "bg-slate-100 text-slate-500";
  return (
    <span
      className={`inline-flex rounded-sm px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${cls}`}
    >
      {outcome}
    </span>
  );
}

function Loading() {
  return (
    <div className="grid place-items-center px-5 py-12 text-2xs uppercase tracking-wider text-slate-400">
      Loading webhooks…
    </div>
  );
}

function EmptyState() {
  return (
    <div className="grid place-items-center px-5 py-12 text-center">
      <Webhook className="h-6 w-6 text-slate-300" aria-hidden />
      <p className="mt-2 max-w-md text-2xs text-slate-500">
        No webhooks yet. Click <span className="font-medium">New endpoint</span> above to register
        one.
      </p>
    </div>
  );
}
