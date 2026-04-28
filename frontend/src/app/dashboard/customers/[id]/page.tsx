"use client";

// Customer master detail. Read-and-edit surface mirroring the invoice
// review screen — same FieldRow component, same draft + SaveBar pattern,
// same allowlist contract with the backend (EDITABLE_CUSTOMER_FIELDS on
// the server, EditableCustomerField here).
//
// What this page exists to do, in priority order per UX_PRINCIPLES principle 1
// ("the user's job comes before everything else"):
//   1. Confirm we have the right buyer (legal name + TIN, prominent).
//   2. Audit / correct the auto-fill defaults (MSIC, address, etc.) so
//      the next invoice for this buyer renders cleanly.
//   3. See alias history + usage so the user knows we've handled their
//      LLM name variants without surprises.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { api, ApiError, type Customer } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { FieldRow } from "@/components/review/FieldRow";

type EditableCustomerField =
  | "legal_name"
  | "tin"
  | "registration_number"
  | "msic_code"
  | "address"
  | "phone"
  | "sst_number"
  | "country_code";

type Draft = Partial<Record<EditableCustomerField, string>>;

export default function CustomerDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getCustomer(params.id)
      .then(setCustomer)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/sign-in");
          return;
        }
        if (err instanceof ApiError && err.status === 404) {
          setError("Customer not found.");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load customer.");
      });
  }, [params.id, router]);

  const dirtyCount = Object.keys(draft).length;

  function onChangeField(name: string, value: string) {
    setSaveError(null);
    setDraft((prev) => ({ ...prev, [name as EditableCustomerField]: value }));
  }

  async function onSave() {
    if (!customer) return;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await api.updateCustomer(customer.id, draft);
      setCustomer(updated);
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
        <Empty>{error}</Empty>
      </AppShell>
    );
  if (!customer)
    return (
      <AppShell>
        <Empty>Loading…</Empty>
      </AppShell>
    );

  const valueOf = (name: EditableCustomerField): string => {
    if (name in draft) return draft[name] ?? "";
    const raw = (customer as Record<string, unknown>)[name];
    if (raw === null || raw === undefined) return "";
    return String(raw);
  };
  const isDirty = (name: EditableCustomerField) => name in draft;

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <Header customer={customer} />

        <section className="grid gap-6 lg:grid-cols-[2fr_1fr]">
          <div className="flex flex-col gap-5">
            <Section title="Identity">
              <div className="grid gap-3 md:grid-cols-2">
                <FieldRow
                  label="Legal name"
                  name="legal_name"
                  value={valueOf("legal_name")}
                  dirty={isDirty("legal_name")}
                  onChange={onChangeField}
                />
                <FieldRow
                  label="TIN"
                  name="tin"
                  value={valueOf("tin")}
                  dirty={isDirty("tin")}
                  onChange={onChangeField}
                  mono
                />
                <FieldRow
                  label="Registration number"
                  name="registration_number"
                  value={valueOf("registration_number")}
                  dirty={isDirty("registration_number")}
                  onChange={onChangeField}
                  mono
                />
                <FieldRow
                  label="MSIC code"
                  name="msic_code"
                  value={valueOf("msic_code")}
                  dirty={isDirty("msic_code")}
                  onChange={onChangeField}
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
                  label="Country code"
                  name="country_code"
                  value={valueOf("country_code")}
                  dirty={isDirty("country_code")}
                  onChange={onChangeField}
                  mono
                />
              </div>
            </Section>

            <Section title="Contact">
              <div className="grid gap-3 md:grid-cols-2">
                <FieldRow
                  label="Phone"
                  name="phone"
                  value={valueOf("phone")}
                  dirty={isDirty("phone")}
                  onChange={onChangeField}
                />
                <FieldRow
                  label="Address"
                  name="address"
                  value={valueOf("address")}
                  dirty={isDirty("address")}
                  onChange={onChangeField}
                />
              </div>
            </Section>
          </div>

          <aside className="flex flex-col gap-4">
            <Stat label="Invoices using this master" value={String(customer.usage_count)} />
            <Stat
              label="Last seen"
              value={
                customer.last_used_at
                  ? new Date(customer.last_used_at).toLocaleDateString()
                  : "—"
              }
            />
            <AliasCard aliases={customer.aliases} />
            <VerificationCard customer={customer} />
          </aside>
        </section>

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

function Header({ customer }: { customer: Customer }) {
  return (
    <div>
      <Link
        href="/dashboard/customers"
        className="text-2xs font-medium text-slate-500 hover:text-ink"
      >
        ← Customers
      </Link>
      <h1 className="mt-1 font-display text-2xl font-bold tracking-tight">
        {customer.legal_name}
      </h1>
      <div className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
        {customer.tin || "no TIN"} · {customer.usage_count} invoice
        {customer.usage_count === 1 ? "" : "s"}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white px-4 py-3">
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div className="mt-1 font-display text-xl font-semibold">{value}</div>
    </div>
  );
}

function AliasCard({ aliases }: { aliases: string[] }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white px-4 py-3">
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        Name variants
      </div>
      {aliases.length === 0 ? (
        <div className="mt-1 text-2xs text-slate-400">
          No variants learned yet.
        </div>
      ) : (
        <ul className="mt-2 flex flex-col gap-1 text-2xs text-slate-600">
          {aliases.map((alias, idx) => (
            <li key={`${alias}-${idx}`} className="truncate">
              {alias}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function VerificationCard({ customer }: { customer: Customer }) {
  const verified = customer.tin_verification_state === "verified";
  const failed = customer.tin_verification_state === "failed";
  const tone = verified
    ? "text-success"
    : failed
      ? "text-error"
      : "text-slate-500";
  return (
    <div className="rounded-xl border border-slate-100 bg-white px-4 py-3">
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        TIN verification
      </div>
      <div className={`mt-1 text-base font-medium ${tone}`}>
        {customer.tin_verification_state.charAt(0).toUpperCase() +
          customer.tin_verification_state.slice(1)}
      </div>
      {customer.tin_last_verified_at && (
        <div className="mt-1 text-2xs text-slate-400">
          last checked{" "}
          {new Date(customer.tin_last_verified_at).toLocaleDateString()}
        </div>
      )}
      {!verified && !failed && (
        <p className="mt-2 text-2xs text-slate-500">
          Live LHDN verification lands in a follow-up slice — until then this
          stays unverified.
        </p>
      )}
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
      aria-label="Unsaved corrections"
      className="sticky bottom-0 left-0 right-0 z-10 -mx-6 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white/95 px-6 py-3 backdrop-blur"
    >
      <div className="text-2xs">
        <span className="font-medium text-ink">
          {count} unsaved correction{count === 1 ? "" : "s"}
        </span>
        {error ? (
          <span className="ml-3 text-error">{error}</span>
        ) : (
          <span className="ml-3 text-slate-500">
            Save to update this master. Future invoices auto-fill from these
            values.
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onDiscard} disabled={saving}>
          Discard
        </Button>
        <Button size="sm" onClick={onSave} disabled={saving}>
          {saving ? "Saving…" : "Save corrections"}
        </Button>
      </div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="grid place-items-center py-24 text-slate-400">{children}</div>;
}
