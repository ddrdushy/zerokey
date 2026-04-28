"use client";

// Settings → Notifications tab. Per-user, per-tenant event toggles
// for in-app + email channels. Saves on toggle change with a
// debounced batch (so a user clicking a few toggles in quick
// succession produces one request, not five).

import { useEffect, useRef, useState } from "react";
import { Bell, CircleCheck, Mail } from "lucide-react";

import {
  api,
  ApiError,
  type NotificationPreferenceRow,
} from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { SettingsTabs } from "@/components/settings/SettingsTabs";
import { cn } from "@/lib/utils";

export default function NotificationsSettingsPage() {
  const [events, setEvents] = useState<NotificationPreferenceRow[] | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  // Pending updates batched until the debounce timer fires. Keyed by
  // event key so multiple toggles on the same event collapse.
  const pendingRef = useRef<
    Record<string, { in_app?: boolean; email?: boolean }>
  >({});
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function refresh() {
    try {
      const result = await api.getNotificationPreferences();
      setEvents(result.events);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError("You are not a member of this organization.");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load.");
      setEvents([]);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  function flush() {
    const updates = pendingRef.current;
    pendingRef.current = {};
    if (Object.keys(updates).length === 0) return;
    api
      .setNotificationPreferences(updates)
      .then((result) => {
        setEvents(result.events);
        setSavedFlash(true);
        setTimeout(() => setSavedFlash(false), 1200);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Save failed.");
        // Reload from server to discard the optimistic update.
        refresh();
      });
  }

  function onToggle(key: string, channel: "in_app" | "email", next: boolean) {
    // Optimistic update so the toggle responds instantly.
    setEvents((prev) =>
      prev
        ? prev.map((e) => (e.key === key ? { ...e, [channel]: next } : e))
        : prev,
    );
    // Merge into pending. We send the BOTH channels for the event so
    // the server has full context (the API replaces the per-event
    // sub-dict atomically).
    const current = events?.find((e) => e.key === key);
    if (!current) return;
    const merged = pendingRef.current[key] ?? {
      in_app: current.in_app,
      email: current.email,
    };
    merged[channel] = next;
    pendingRef.current[key] = merged;

    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(flush, 350);
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

        <section className="rounded-xl border border-slate-100 bg-white">
          <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div className="flex items-center gap-2">
              <Bell className="h-4 w-4 text-slate-400" />
              <h2 className="text-sm font-semibold text-ink">
                Notifications
              </h2>
            </div>
            {savedFlash && (
              <span className="inline-flex items-center gap-1 text-2xs text-success">
                <CircleCheck className="h-3.5 w-3.5" />
                Saved
              </span>
            )}
          </header>
          <div className="px-5 py-3 text-2xs text-slate-500">
            Choose which platform events reach you, and on which
            channels. Changes save automatically. Defaults are
            everything-on; toggle off only the events you don&apos;t
            want.
          </div>

          {events === null ? (
            <Loading />
          ) : (
            <div className="overflow-hidden">
              <table className="w-full text-2xs">
                <thead className="bg-slate-50 text-slate-400">
                  <tr>
                    <th className="px-5 py-2 text-left font-medium uppercase tracking-wider">
                      Event
                    </th>
                    <th className="px-3 py-2 text-center font-medium uppercase tracking-wider">
                      In-app bell
                    </th>
                    <th className="px-3 py-2 text-center font-medium uppercase tracking-wider">
                      Email
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {events.map((e) => (
                    <tr key={e.key}>
                      <td className="px-5 py-3">
                        <div className="font-medium text-ink">{e.label}</div>
                        <div className="mt-0.5 text-[10px] text-slate-500">
                          {e.description}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-center">
                        <Toggle
                          checked={e.in_app}
                          onChange={(next) =>
                            onToggle(e.key, "in_app", next)
                          }
                        />
                      </td>
                      <td className="px-3 py-3 text-center">
                        <Toggle
                          checked={e.email}
                          onChange={(next) =>
                            onToggle(e.key, "email", next)
                          }
                          icon={<Mail className="h-3 w-3" />}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="border-t border-slate-100 px-5 py-3 text-[10px] text-slate-400">
                Email delivery requires the platform&apos;s SMTP
                credentials to be configured by the operator. Until
                then, email toggles capture your preference but no
                message will be sent.
              </div>
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}

function Toggle({
  checked,
  onChange,
  icon,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  icon?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 items-center rounded-full transition",
        checked ? "bg-success" : "bg-slate-200",
      )}
    >
      <span
        className={cn(
          "inline-flex h-4 w-4 items-center justify-center rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-4" : "translate-x-1",
        )}
      >
        {icon && <span className="text-slate-500">{icon}</span>}
      </span>
    </button>
  );
}

function Loading() {
  return (
    <div className="grid place-items-center px-5 py-12 text-2xs uppercase tracking-wider text-slate-400">
      Loading preferences…
    </div>
  );
}
