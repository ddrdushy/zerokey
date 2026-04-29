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
import { Lock, LockOpen } from "lucide-react";

import { api, ApiError, type Customer, type CustomerInvoiceSummary } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { FieldRow } from "@/components/review/FieldRow";
import { ProvenancePill } from "@/components/review/ProvenancePill";

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
  const [invoices, setInvoices] = useState<CustomerInvoiceSummary[] | null>(null);
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
    // The invoice list is independent of the master detail; load both
    // in parallel. A 403 on this side is rare (the detail call would have
    // already redirected), but we still tolerate failures rather than
    // failing the whole page on a list-fetch error.
    api
      .listCustomerInvoices(params.id)
      .then(setInvoices)
      .catch(() => setInvoices([]));
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

  // Slice 81 — toggle a MasterFieldLock on this customer master.
  // Optimistic update: the page assumes the lock/unlock will
  // succeed; the backend is the source of truth + we re-fetch on
  // failure to roll back the visible state.
  async function onToggleLock(fieldName: EditableCustomerField, nextLocked: boolean) {
    if (!customer) return;
    setSaveError(null);
    const wasLocked = customer.locked_fields.includes(fieldName);
    const optimistic: Customer = {
      ...customer,
      locked_fields: nextLocked
        ? [...customer.locked_fields.filter((f) => f !== fieldName), fieldName]
        : customer.locked_fields.filter((f) => f !== fieldName),
    };
    setCustomer(optimistic);
    try {
      if (nextLocked) {
        await api.lockMasterField({
          master_type: "customer",
          master_id: customer.id,
          field_name: fieldName,
          reason: "Customer detail page",
        });
      } else {
        await api.unlockMasterField({
          master_type: "customer",
          master_id: customer.id,
          field_name: fieldName,
        });
      }
    } catch (err) {
      // Roll back the optimistic flip + re-fetch from the server
      // so the UI reflects the truth.
      setSaveError(err instanceof Error ? err.message : "Lock toggle failed.");
      setCustomer((current) =>
        current
          ? {
              ...current,
              locked_fields: wasLocked
                ? [...current.locked_fields.filter((f) => f !== fieldName), fieldName]
                : current.locked_fields.filter((f) => f !== fieldName),
            }
          : current,
      );
    }
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
                <ProvenancedField
                  customer={customer}
                  fieldName="legal_name"
                  label="Legal name"
                  value={valueOf("legal_name")}
                  dirty={isDirty("legal_name")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                />
                <ProvenancedField
                  customer={customer}
                  fieldName="tin"
                  label="TIN"
                  value={valueOf("tin")}
                  dirty={isDirty("tin")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                  mono
                />
                <ProvenancedField
                  customer={customer}
                  fieldName="registration_number"
                  label="Registration number"
                  value={valueOf("registration_number")}
                  dirty={isDirty("registration_number")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                  mono
                />
                <ProvenancedField
                  customer={customer}
                  fieldName="msic_code"
                  label="MSIC code"
                  value={valueOf("msic_code")}
                  dirty={isDirty("msic_code")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                  mono
                />
                <ProvenancedField
                  customer={customer}
                  fieldName="sst_number"
                  label="SST number"
                  value={valueOf("sst_number")}
                  dirty={isDirty("sst_number")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                  mono
                />
                <ProvenancedField
                  customer={customer}
                  fieldName="country_code"
                  label="Country code"
                  value={valueOf("country_code")}
                  dirty={isDirty("country_code")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                  mono
                />
              </div>
            </Section>

            <Section title="Contact">
              <div className="grid gap-3 md:grid-cols-2">
                <ProvenancedField
                  customer={customer}
                  fieldName="phone"
                  label="Phone"
                  value={valueOf("phone")}
                  dirty={isDirty("phone")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                />
                <ProvenancedField
                  customer={customer}
                  fieldName="address"
                  label="Address"
                  value={valueOf("address")}
                  dirty={isDirty("address")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                />
              </div>
            </Section>
          </div>

          <aside className="flex flex-col gap-4">
            <Stat label="Invoices using this master" value={String(customer.usage_count)} />
            <Stat
              label="Last seen"
              value={
                customer.last_used_at ? new Date(customer.last_used_at).toLocaleDateString() : "—"
              }
            />
            <AliasCard aliases={customer.aliases} />
            <VerificationCard customer={customer} />
          </aside>
        </section>

        <InvoiceHistory invoices={invoices} />

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

// Slice 73 — wraps FieldRow + ProvenancePill so each field carries
// its source pill underneath ("Extracted from invoice", "From
// AutoCount", "Entered manually"). Reads the entry from
// ``customer.field_provenance[fieldName]``; absent entries render
// nothing (e.g. fields the customer has never filled).
//
// Slice 81 — also shows a lock icon on each field. Clicking the
// icon toggles a ``MasterFieldLock`` row. Locked fields always
// route to the conflict queue on future syncs regardless of
// source — see Slice 74's classify_merge matrix.
function ProvenancedField({
  customer,
  fieldName,
  label,
  value,
  dirty,
  onChange,
  onToggleLock,
  mono,
}: {
  customer: Customer;
  fieldName: EditableCustomerField;
  label: string;
  value: string;
  dirty: boolean;
  onChange: (name: string, value: string) => void;
  onToggleLock: (fieldName: EditableCustomerField, nextLocked: boolean) => void;
  mono?: boolean;
}) {
  const entry = customer.field_provenance?.[fieldName];
  const locked = (customer.locked_fields ?? []).includes(fieldName);
  return (
    <div className="flex flex-col">
      <div className="relative">
        <FieldRow
          label={label}
          name={fieldName}
          value={value}
          dirty={dirty}
          onChange={onChange}
          mono={mono}
        />
        <button
          type="button"
          onClick={() => onToggleLock(fieldName, !locked)}
          aria-label={locked ? `Unlock ${label}` : `Lock ${label}`}
          title={
            locked
              ? "Unlock — future syncs can change this field again."
              : "Lock — future syncs will route changes to this field through the conflict queue."
          }
          className="absolute right-2 top-2 rounded p-1 text-slate-400 transition hover:bg-slate-100 hover:text-ink"
        >
          {locked ? (
            <Lock className="h-3.5 w-3.5 text-warning" />
          ) : (
            <LockOpen className="h-3.5 w-3.5" />
          )}
        </button>
      </div>
      <div className="flex items-center gap-2">
        <ProvenancePill entry={entry} />
        {locked && (
          <span className="mt-1.5 inline-flex items-center gap-1 rounded-md bg-warning/10 px-1.5 py-0.5 text-[10px] font-medium text-warning">
            <Lock className="h-2.5 w-2.5" aria-hidden />
            Locked
          </span>
        )}
      </div>
    </div>
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
      <h1 className="mt-1 font-display text-2xl font-bold tracking-tight">{customer.legal_name}</h1>
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
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">{label}</div>
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
        <div className="mt-1 text-2xs text-slate-400">No variants learned yet.</div>
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

function InvoiceHistory({ invoices }: { invoices: CustomerInvoiceSummary[] | null }) {
  if (invoices === null) {
    return (
      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold">Invoices from this buyer</h2>
        <div className="rounded-xl border border-slate-100 bg-white p-4 text-2xs text-slate-400">
          Loading…
        </div>
      </section>
    );
  }
  if (invoices.length === 0) {
    return (
      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold">Invoices from this buyer</h2>
        <div className="rounded-xl border border-slate-100 bg-white p-6 text-center">
          <p className="text-2xs text-slate-500">
            No invoices have referenced this buyer yet. New invoices that match this master appear
            here automatically.
          </p>
        </div>
      </section>
    );
  }
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold">Invoices from this buyer</h2>
        <span className="text-2xs uppercase tracking-wider text-slate-400">
          {invoices.length} invoice{invoices.length === 1 ? "" : "s"}
        </span>
      </div>
      <div className="overflow-hidden rounded-xl border border-slate-100 bg-white">
        <table className="w-full text-2xs">
          <thead className="bg-slate-50 text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Invoice number
              </th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Issue date
              </th>
              <th className="px-3 py-2 text-right font-medium uppercase tracking-wider">
                Grand total
              </th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {invoices.map((invoice) => (
              <tr key={invoice.id} className="hover:bg-slate-50">
                <td className="px-3 py-3">
                  <Link
                    href={`/dashboard/jobs/${invoice.ingestion_job_id}`}
                    className="font-medium text-ink hover:underline"
                  >
                    {invoice.invoice_number || <span className="text-slate-400">no number</span>}
                  </Link>
                </td>
                <td className="px-3 py-3 text-slate-600">
                  {invoice.issue_date ? new Date(invoice.issue_date).toLocaleDateString() : "—"}
                </td>
                <td className="px-3 py-3 text-right font-mono">
                  {invoice.grand_total ? `${invoice.currency_code} ${invoice.grand_total}` : "—"}
                </td>
                <td className="px-3 py-3">
                  <StatusPill status={invoice.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status === "validated" || status === "ready_for_review"
      ? "bg-success/10 text-success"
      : status === "error" || status === "rejected"
        ? "bg-error/10 text-error"
        : "bg-slate-100 text-slate-600";
  return (
    <span
      className={["inline-block rounded-full px-2 py-0.5 text-[10px] font-medium", tone].join(" ")}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function VerificationCard({ customer }: { customer: Customer }) {
  // Slice 73 — five-state tin_verification_state. The card uses
  // tone + label per state, and the helper text adjusts to the
  // state's meaning rather than always saying "lands in a
  // follow-up" (Slice 70 made verification real).
  const stateMeta: Record<
    Customer["tin_verification_state"],
    { label: string; tone: string; helper: string | null }
  > = {
    verified: {
      label: "Verified",
      tone: "text-success",
      helper: null,
    },
    failed: {
      label: "Failed verification",
      tone: "text-error",
      helper: "LHDN didn't recognise this TIN. Correct it + we'll re-check on save.",
    },
    unverified: {
      label: "Unverified",
      tone: "text-slate-500",
      helper: "Will be verified against LHDN automatically on the next enrichment cycle.",
    },
    unverified_external_source: {
      label: "Unverified · external source",
      tone: "text-amber-700",
      helper:
        "Synced from an external system. Will be verified against LHDN on the next enrichment cycle.",
    },
    manually_resolved: {
      label: "Manually resolved",
      tone: "text-success",
      helper:
        "A user picked this value in the conflict queue. Re-verified periodically against LHDN.",
    },
  };
  const meta = stateMeta[customer.tin_verification_state];
  return (
    <div className="rounded-xl border border-slate-100 bg-white px-4 py-3">
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        TIN verification
      </div>
      <div className={`mt-1 text-base font-medium ${meta.tone}`}>{meta.label}</div>
      {customer.tin_last_verified_at && (
        <div className="mt-1 text-2xs text-slate-400">
          last checked {new Date(customer.tin_last_verified_at).toLocaleDateString()}
        </div>
      )}
      {meta.helper && <p className="mt-2 text-2xs text-slate-500">{meta.helper}</p>}
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
            Save to update this master. Future invoices auto-fill from these values.
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
