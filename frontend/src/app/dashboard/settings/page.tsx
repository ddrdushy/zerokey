"use client";

// Settings → Organization. The user edits the org's contact + identity
// fields with the same FieldRow + SaveBar pattern as the invoice review
// (Slice 15) and customer master (Slice 16) screens. Read-only fields
// (TIN, billing currency, lifecycle, certificate state) render
// alongside as plain rows so the user sees the whole org shape but
// can't accidentally try to change values that don't belong here.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Building2, Globe, Phone, ShieldCheck } from "lucide-react";

import { api, ApiError, type OrganizationDetail } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { FieldRow } from "@/components/review/FieldRow";

type EditableOrgField =
  | "legal_name"
  | "sst_number"
  | "registered_address"
  | "contact_email"
  | "contact_phone"
  | "language_preference"
  | "timezone"
  | "logo_url";

type Draft = Partial<Record<EditableOrgField, string>>;

export default function OrganizationSettingsPage() {
  const router = useRouter();
  const [org, setOrg] = useState<OrganizationDetail | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getOrganization()
      .then(setOrg)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/sign-in");
          return;
        }
        setError(
          err instanceof Error ? err.message : "Failed to load organization.",
        );
      });
  }, [router]);

  function onChangeField(name: string, value: string) {
    setSaveError(null);
    setDraft((prev) => ({ ...prev, [name as EditableOrgField]: value }));
  }

  async function onSave() {
    if (!org) return;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await api.updateOrganization(draft);
      setOrg(updated);
      setDraft({});
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  function onDiscard() {
    setSaveError(null);
    setDraft({});
  }

  if (error)
    return (
      <AppShell>
        <Pad>{error}</Pad>
      </AppShell>
    );
  if (!org)
    return (
      <AppShell>
        <Pad>Loading…</Pad>
      </AppShell>
    );

  const valueOf = (name: EditableOrgField): string => {
    if (name in draft) return draft[name] ?? "";
    const raw = (org as Record<string, unknown>)[name];
    if (raw === null || raw === undefined) return "";
    return String(raw);
  };
  const isDirty = (name: EditableOrgField) => name in draft;
  const dirtyCount = Object.keys(draft).length;

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Organization
          </h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            {`Your organization's contact + identity details`}
          </p>
        </header>

        <Section title="Identity" icon={<Building2 className="h-4 w-4" />}>
          <div className="grid gap-3 md:grid-cols-2">
            <FieldRow
              label="Legal name"
              name="legal_name"
              value={valueOf("legal_name")}
              dirty={isDirty("legal_name")}
              onChange={onChangeField}
            />
            <ReadOnlyRow
              label="TIN"
              value={org.tin}
              hint="LHDN-issued. Contact support to change."
              mono
            />
            <FieldRow
              label="SST number"
              name="sst_number"
              value={valueOf("sst_number")}
              dirty={isDirty("sst_number")}
              onChange={onChangeField}
              mono
            />
            <FieldRow
              label="Registered address"
              name="registered_address"
              value={valueOf("registered_address")}
              dirty={isDirty("registered_address")}
              onChange={onChangeField}
            />
          </div>
        </Section>

        <Section title="Contact" icon={<Phone className="h-4 w-4" />}>
          <div className="grid gap-3 md:grid-cols-2">
            <FieldRow
              label="Contact email"
              name="contact_email"
              value={valueOf("contact_email")}
              dirty={isDirty("contact_email")}
              onChange={onChangeField}
            />
            <FieldRow
              label="Contact phone"
              name="contact_phone"
              value={valueOf("contact_phone")}
              dirty={isDirty("contact_phone")}
              onChange={onChangeField}
            />
          </div>
        </Section>

        <Section title="Preferences" icon={<Globe className="h-4 w-4" />}>
          <div className="grid gap-3 md:grid-cols-2">
            <FieldRow
              label="Language"
              name="language_preference"
              value={valueOf("language_preference")}
              dirty={isDirty("language_preference")}
              onChange={onChangeField}
            />
            <FieldRow
              label="Timezone"
              name="timezone"
              value={valueOf("timezone")}
              dirty={isDirty("timezone")}
              onChange={onChangeField}
            />
            <FieldRow
              label="Logo URL"
              name="logo_url"
              value={valueOf("logo_url")}
              dirty={isDirty("logo_url")}
              onChange={onChangeField}
            />
            <ReadOnlyRow
              label="Billing currency"
              value={org.billing_currency}
              hint="Set per Plan; contact support to change."
              mono
            />
          </div>
        </Section>

        <Section
          title="Subscription + certificate"
          icon={<ShieldCheck className="h-4 w-4" />}
        >
          <div className="grid gap-3 md:grid-cols-2">
            <ReadOnlyRow
              label="Trial state"
              value={org.trial_state.replace(/_/g, " ")}
            />
            <ReadOnlyRow
              label="Subscription"
              value={org.subscription_state.replace(/_/g, " ")}
            />
            <ReadOnlyRow
              label="Certificate uploaded"
              value={org.certificate_uploaded ? "Yes" : "Not yet"}
            />
            <ReadOnlyRow
              label="Certificate expires"
              value={
                org.certificate_expiry_date
                  ? new Date(org.certificate_expiry_date).toLocaleDateString()
                  : "—"
              }
            />
          </div>
        </Section>

        {dirtyCount > 0 && (
          <SaveBar
            count={dirtyCount}
            saving={saving}
            error={saveError}
            onSave={onSave}
            onDiscard={onDiscard}
          />
        )}
      </div>
    </AppShell>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="flex items-center gap-2 text-base font-semibold">
        {icon ? <span className="text-slate-400">{icon}</span> : null}
        {title}
      </h2>
      {children}
    </section>
  );
}

function ReadOnlyRow({
  label,
  value,
  hint,
  mono,
}: {
  label: string;
  value: string | null | undefined;
  hint?: string;
  mono?: boolean;
}) {
  const isMissing = !value;
  return (
    <div className="rounded-xl border border-slate-100 bg-slate-50/50 px-4 py-3">
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div
        className={[
          "mt-1 text-base text-slate-700",
          mono && value ? "font-mono text-sm" : "",
          isMissing ? "text-slate-400" : "",
        ].join(" ")}
      >
        {value || "—"}
      </div>
      {hint && <div className="mt-0.5 text-2xs text-slate-400">{hint}</div>}
    </div>
  );
}

function SaveBar({
  count,
  saving,
  error,
  onSave,
  onDiscard,
}: {
  count: number;
  saving: boolean;
  error: string | null;
  onSave: () => void;
  onDiscard: () => void;
}) {
  return (
    <div
      role="region"
      aria-label="Unsaved organization changes"
      className="sticky bottom-0 left-0 right-0 z-10 -mx-6 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white/95 px-6 py-3 backdrop-blur"
    >
      <div className="text-2xs">
        <span className="font-medium text-ink">
          {count} unsaved change{count === 1 ? "" : "s"}
        </span>
        {error ? (
          <span className="ml-3 text-error">{error}</span>
        ) : (
          <span className="ml-3 text-slate-500">
            Saved values are recorded in your audit log.
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onDiscard} disabled={saving}>
          Discard
        </Button>
        <Button size="sm" onClick={onSave} disabled={saving}>
          {saving ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

function Pad({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid place-items-center py-24 text-slate-400">{children}</div>
  );
}
