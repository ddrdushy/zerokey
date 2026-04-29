"use client";

// Item master detail (Slice 83). Symmetric to the customer detail
// page: same FieldRow + draft + SaveBar + lock-toggle pattern.
// What this page exists to do, in order:
//   1. Confirm the canonical name matches what the line items
//      should auto-fill against.
//   2. Audit / correct the default codes (MSIC, classification,
//      tax, UOM) so the next invoice line for this item renders
//      cleanly.
//   3. See alias history + usage so the user knows ZeroKey has
//      collapsed their LLM description variants without surprises.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Lock, LockOpen } from "lucide-react";

import { api, ApiError, type Item } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { FieldRow } from "@/components/review/FieldRow";
import { ProvenancePill } from "@/components/review/ProvenancePill";

type EditableItemField =
  | "canonical_name"
  | "default_msic_code"
  | "default_classification_code"
  | "default_tax_type_code"
  | "default_unit_of_measurement"
  | "default_unit_price_excl_tax";

type Draft = Partial<Record<EditableItemField, string>>;

export default function ItemDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [item, setItem] = useState<Item | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getItem(params.id)
      .then(setItem)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/sign-in");
          return;
        }
        if (err instanceof ApiError && err.status === 404) {
          setError("Item not found.");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load item.");
      });
  }, [params.id, router]);

  const dirtyCount = Object.keys(draft).length;

  function onChangeField(name: string, value: string) {
    setSaveError(null);
    setDraft((prev) => ({ ...prev, [name as EditableItemField]: value }));
  }

  async function onSave() {
    if (!item) return;
    setSaving(true);
    setSaveError(null);
    try {
      // Empty unit-price string maps to null on the wire so the
      // backend stores "no advisory price" rather than rejecting.
      const cleaned: Partial<Record<keyof Item, string | null>> = { ...draft };
      if ("default_unit_price_excl_tax" in cleaned) {
        const v = cleaned.default_unit_price_excl_tax;
        cleaned.default_unit_price_excl_tax = v === "" ? null : v;
      }
      const updated = await api.updateItem(item.id, cleaned);
      setItem(updated);
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

  async function onToggleLock(fieldName: EditableItemField, nextLocked: boolean) {
    if (!item) return;
    setSaveError(null);
    const wasLocked = item.locked_fields.includes(fieldName);
    const optimistic: Item = {
      ...item,
      locked_fields: nextLocked
        ? [...item.locked_fields.filter((f) => f !== fieldName), fieldName]
        : item.locked_fields.filter((f) => f !== fieldName),
    };
    setItem(optimistic);
    try {
      if (nextLocked) {
        await api.lockMasterField({
          master_type: "item",
          master_id: item.id,
          field_name: fieldName,
          reason: "Item detail page",
        });
      } else {
        await api.unlockMasterField({
          master_type: "item",
          master_id: item.id,
          field_name: fieldName,
        });
      }
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Lock toggle failed.");
      setItem((current) =>
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
  if (!item)
    return (
      <AppShell>
        <Empty>Loading…</Empty>
      </AppShell>
    );

  const valueOf = (name: EditableItemField): string => {
    if (name in draft) return draft[name] ?? "";
    const raw = (item as Record<string, unknown>)[name];
    if (raw === null || raw === undefined) return "";
    return String(raw);
  };
  const isDirty = (name: EditableItemField) => name in draft;

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <Header item={item} />

        <section className="grid gap-6 lg:grid-cols-[2fr_1fr]">
          <div className="flex flex-col gap-5">
            <Section title="Identity">
              <div className="grid gap-3 md:grid-cols-2">
                <ProvenancedField
                  item={item}
                  fieldName="canonical_name"
                  label="Canonical name"
                  value={valueOf("canonical_name")}
                  dirty={isDirty("canonical_name")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                />
              </div>
            </Section>

            <Section title="Defaults">
              <div className="grid gap-3 md:grid-cols-2">
                <ProvenancedField
                  item={item}
                  fieldName="default_msic_code"
                  label="MSIC code"
                  value={valueOf("default_msic_code")}
                  dirty={isDirty("default_msic_code")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                  mono
                />
                <ProvenancedField
                  item={item}
                  fieldName="default_classification_code"
                  label="Classification code"
                  value={valueOf("default_classification_code")}
                  dirty={isDirty("default_classification_code")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                  mono
                />
                <ProvenancedField
                  item={item}
                  fieldName="default_tax_type_code"
                  label="Tax type code"
                  value={valueOf("default_tax_type_code")}
                  dirty={isDirty("default_tax_type_code")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                  mono
                />
                <ProvenancedField
                  item={item}
                  fieldName="default_unit_of_measurement"
                  label="Unit of measurement"
                  value={valueOf("default_unit_of_measurement")}
                  dirty={isDirty("default_unit_of_measurement")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                  mono
                />
                <ProvenancedField
                  item={item}
                  fieldName="default_unit_price_excl_tax"
                  label="Unit price (excl. tax)"
                  value={valueOf("default_unit_price_excl_tax")}
                  dirty={isDirty("default_unit_price_excl_tax")}
                  onChange={onChangeField}
                  onToggleLock={onToggleLock}
                  mono
                />
              </div>
              <p className="text-2xs text-slate-500">
                The unit price is advisory only — the LLM still reads the price from each invoice.
                ZeroKey uses this to flag prices that look unusual on review.
              </p>
            </Section>
          </div>

          <aside className="flex flex-col gap-4">
            <Stat label="Lines using this master" value={String(item.usage_count)} />
            <Stat
              label="Last seen"
              value={item.last_used_at ? new Date(item.last_used_at).toLocaleDateString() : "—"}
            />
            <AliasCard aliases={item.aliases} />
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

function ProvenancedField({
  item,
  fieldName,
  label,
  value,
  dirty,
  onChange,
  onToggleLock,
  mono,
}: {
  item: Item;
  fieldName: EditableItemField;
  label: string;
  value: string;
  dirty: boolean;
  onChange: (name: string, value: string) => void;
  onToggleLock: (fieldName: EditableItemField, nextLocked: boolean) => void;
  mono?: boolean;
}) {
  const entry = item.field_provenance?.[fieldName];
  const locked = (item.locked_fields ?? []).includes(fieldName);
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

function Header({ item }: { item: Item }) {
  return (
    <div>
      <Link href="/dashboard/items" className="text-2xs font-medium text-slate-500 hover:text-ink">
        ← Items
      </Link>
      <h1 className="mt-1 font-display text-2xl font-bold tracking-tight">{item.canonical_name}</h1>
      <div className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
        {item.usage_count} line{item.usage_count === 1 ? "" : "s"}
        {item.default_msic_code ? ` · MSIC ${item.default_msic_code}` : ""}
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
        Description variants
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
            Save to update this master. Future invoice lines auto-fill from these defaults.
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
