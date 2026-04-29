"use client";

// Customer master list. Most-used buyers first per the API's default sort —
// the data accumulates as the user submits invoices, so this view doubles
// as a "your frequent customers" board. Empty state speaks in opportunity
// per UX_PRINCIPLES principle 7 (empty states do real work).

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, ShieldQuestion, Users } from "lucide-react";

import { api, ApiError, type Customer } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { useT } from "@/lib/i18n";

export default function CustomersPage() {
  const router = useRouter();
  const t = useT();
  const [customers, setCustomers] = useState<Customer[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listCustomers()
      .then(setCustomers)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/sign-in");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load customers.");
        setCustomers([]);
      });
  }, [router]);

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header className="flex items-end justify-between">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">
              {t("customers.title")}
            </h1>
            <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
              {t("customers.subtitle")}
            </p>
          </div>
          {customers && customers.length > 0 && (
            <span className="text-2xs uppercase tracking-wider text-slate-400">
              {t("customers.count", { count: customers.length })}
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

        {customers === null ? (
          <Skeleton />
        ) : customers.length === 0 ? (
          <EmptyState />
        ) : (
          <CustomerTable customers={customers} />
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
      <Users className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
      <h2 className="mt-4 font-display text-xl font-semibold">No customers yet</h2>
      <p className="mx-auto mt-2 max-w-md text-2xs text-slate-500">
        Customers appear here automatically as you submit invoices. Each new buyer ZeroKey reads
        creates a master record; subsequent invoices for that buyer auto-fill from it.
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

function CustomerTable({ customers }: { customers: Customer[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-100 bg-white">
      <table className="w-full text-2xs">
        <thead className="bg-slate-50 text-slate-400">
          <tr>
            <Th align="left">Customer</Th>
            <Th align="left">TIN</Th>
            <Th align="left">MSIC</Th>
            <Th align="right">Invoices</Th>
            <Th align="left">Last seen</Th>
            <Th align="left">Verification</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {customers.map((c) => (
            <tr key={c.id} className="hover:bg-slate-50">
              <td className="px-3 py-3">
                <Link
                  href={`/dashboard/customers/${c.id}`}
                  className="font-medium text-ink hover:underline"
                >
                  {c.legal_name}
                </Link>
                {c.aliases.length > 0 && (
                  <div className="mt-0.5 text-slate-400">
                    also known as{" "}
                    {c.aliases.length === 1
                      ? c.aliases[0]
                      : `${c.aliases[0]} +${c.aliases.length - 1} more`}
                  </div>
                )}
              </td>
              <td className="px-3 py-3 font-mono text-slate-600">
                {c.tin || <span className="text-slate-400">—</span>}
              </td>
              <td className="px-3 py-3 font-mono text-slate-600">
                {c.msic_code || <span className="text-slate-400">—</span>}
              </td>
              <td className="px-3 py-3 text-right font-mono">{c.usage_count}</td>
              <td className="px-3 py-3 text-slate-600">
                {c.last_used_at ? new Date(c.last_used_at).toLocaleDateString() : "—"}
              </td>
              <td className="px-3 py-3">
                <VerificationBadge state={c.tin_verification_state} />
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

function VerificationBadge({ state }: { state: Customer["tin_verification_state"] }) {
  if (state === "verified") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-success/10 px-2 py-0.5 text-[10px] font-medium text-success">
        <CheckCircle2 className="h-3 w-3" /> Verified
      </span>
    );
  }
  if (state === "failed") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-error/10 px-2 py-0.5 text-[10px] font-medium text-error">
        Failed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">
      <ShieldQuestion className="h-3 w-3" /> Unverified
    </span>
  );
}
