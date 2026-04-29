"use client";

// Item master list (Slice 83). Symmetric to the Customers list:
// most-used items first, default codes visible at a glance, click
// through for the detail editor + lock toggles.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Package } from "lucide-react";

import { api, ApiError, type Item } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";

export default function ItemsPage() {
  const router = useRouter();
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listItems()
      .then(setItems)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/sign-in");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load items.");
        setItems([]);
      });
  }, [router]);

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header className="flex items-end justify-between">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">Items</h1>
            <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
              Line-item descriptions ZeroKey has learned from your invoices
            </p>
          </div>
          {items && items.length > 0 && (
            <span className="text-2xs uppercase tracking-wider text-slate-400">
              {items.length} total
            </span>
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

        {items === null ? (
          <Skeleton />
        ) : items.length === 0 ? (
          <EmptyState />
        ) : (
          <ItemTable items={items} />
        )}
      </div>
    </AppShell>
  );
}

function Skeleton() {
  return (
    <div className="grid place-items-center py-24 text-2xs uppercase tracking-wider text-slate-400">
      Loading…
    </div>
  );
}

function EmptyState() {
  return (
    <section className="rounded-xl border border-slate-100 bg-white p-12 text-center">
      <Package className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
      <h2 className="mt-4 font-display text-xl font-semibold">No items yet</h2>
      <p className="mx-auto mt-2 max-w-md text-2xs text-slate-500">
        Items appear here automatically as you submit invoices. Each new line description ZeroKey
        reads creates a master record; subsequent invoices reuse the master&apos;s default codes.
      </p>
      <Link
        href="/dashboard"
        className="mt-6 inline-block text-2xs font-medium text-ink underline-offset-4 hover:underline"
      >
        Drop your first invoice →
      </Link>
    </section>
  );
}

function ItemTable({ items }: { items: Item[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-100 bg-white">
      <table className="w-full text-2xs">
        <thead className="bg-slate-50 text-slate-400">
          <tr>
            <Th align="left">Item</Th>
            <Th align="left">MSIC</Th>
            <Th align="left">Classification</Th>
            <Th align="left">Tax</Th>
            <Th align="left">UOM</Th>
            <Th align="right">Lines</Th>
            <Th align="left">Last seen</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((it) => (
            <tr key={it.id} className="hover:bg-slate-50">
              <td className="px-3 py-3">
                <Link
                  href={`/dashboard/items/${it.id}`}
                  className="font-medium text-ink hover:underline"
                >
                  {it.canonical_name}
                </Link>
                {it.aliases.length > 0 && (
                  <div className="mt-0.5 text-slate-400">
                    also known as{" "}
                    {it.aliases.length === 1
                      ? it.aliases[0]
                      : `${it.aliases[0]} +${it.aliases.length - 1} more`}
                  </div>
                )}
              </td>
              <td className="px-3 py-3 font-mono text-slate-600">
                {it.default_msic_code || <span className="text-slate-400">—</span>}
              </td>
              <td className="px-3 py-3 font-mono text-slate-600">
                {it.default_classification_code || <span className="text-slate-400">—</span>}
              </td>
              <td className="px-3 py-3 font-mono text-slate-600">
                {it.default_tax_type_code || <span className="text-slate-400">—</span>}
              </td>
              <td className="px-3 py-3 font-mono text-slate-600">
                {it.default_unit_of_measurement || <span className="text-slate-400">—</span>}
              </td>
              <td className="px-3 py-3 text-right font-mono">{it.usage_count}</td>
              <td className="px-3 py-3 text-slate-600">
                {it.last_used_at ? new Date(it.last_used_at).toLocaleDateString() : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Th({ children, align }: { children: React.ReactNode; align: "left" | "right" }) {
  const cls =
    "px-3 py-2 font-medium uppercase tracking-wider " +
    (align === "right" ? "text-right" : "text-left");
  return <th className={cls}>{children}</th>;
}
