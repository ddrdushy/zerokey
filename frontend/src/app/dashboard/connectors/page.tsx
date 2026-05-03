"use client";

// Slice 77b — Connectors landing page.
//
// Lists active integration configs + lets the user connect a new
// CSV source. Each row links into either the upload wizard (for
// CSV) or a "talk to sales" placeholder (for non-CSV connectors
// that aren't shipped yet — Slice 78+).
//
// CSV is the universal escape hatch + the only fully-wired
// connector today. The other connector types render as
// "Coming soon" rows so customers see what's planned without
// being able to mis-configure.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Database,
  FileSpreadsheet,
  Loader2,
  Plug,
  ShoppingBag,
  Trash2,
  Upload,
} from "lucide-react";

import { api, ApiError, type ConnectorType, type IntegrationConfigRow } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type CatalogEntry = {
  type: ConnectorType;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  shipped: boolean;
};

const CATALOG: CatalogEntry[] = [
  {
    type: "csv",
    label: "CSV upload",
    description:
      "Upload a customer / item list from any spreadsheet. The universal escape hatch — works with any system that exports CSV.",
    icon: FileSpreadsheet,
    shipped: true,
  },
  {
    type: "autocount",
    label: "AutoCount",
    description:
      "Upload your AutoCount Debtor List or Stock Items export — column mapping is built in.",
    icon: Database,
    shipped: true,
  },
  {
    type: "sql_account",
    label: "SQL Account",
    description:
      "Upload an SQL Account Debtor / Stock Maintenance export — column mapping is built in.",
    icon: Database,
    shipped: true,
  },
  {
    type: "sage_ubs",
    label: "Sage UBS",
    description:
      "Upload a Sage UBS Customer / Stock export — column mapping is built in (handles both LHDN-era and pre-LHDN exports).",
    icon: Database,
    shipped: true,
  },
  {
    type: "sql_accounting",
    label: "SQL Accounting (ODBC)",
    description: "Always-on ODBC sync against SQL Account / SQL Payroll database — coming when a customer asks.",
    icon: Database,
    shipped: false,
  },
  {
    type: "xero",
    label: "Xero",
    description: "OAuth — sync your Xero contacts + items.",
    icon: Plug,
    shipped: false,
  },
  {
    type: "quickbooks",
    label: "QuickBooks Online",
    description: "OAuth — sync your QuickBooks customers + products.",
    icon: Plug,
    shipped: false,
  },
  {
    type: "shopify",
    label: "Shopify",
    description: "Pull your Shopify customer list.",
    icon: ShoppingBag,
    shipped: false,
  },
  {
    type: "woocommerce",
    label: "WooCommerce",
    description: "Pull your WooCommerce customer list.",
    icon: ShoppingBag,
    shipped: false,
  },
];

export default function ConnectorsPage() {
  const router = useRouter();
  const [configs, setConfigs] = useState<IntegrationConfigRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creatingType, setCreatingType] = useState<ConnectorType | null>(null);

  async function refresh() {
    try {
      setConfigs(await api.listConnectorConfigs());
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        router.replace("/sign-in");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load.");
      setConfigs([]);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onConnect(type: ConnectorType) {
    setCreatingType(type);
    setError(null);
    try {
      const config = await api.createConnectorConfig(type);
      // CSV + the three CSV-driven accounting connectors all jump
      // straight into an upload page. Slice 98 added SQL Account and
      // Sage UBS using the same upload UX as AutoCount.
      if (type === "csv") {
        router.push(`/dashboard/connectors/${config.id}/upload`);
        return;
      }
      if (type === "autocount" || type === "sql_account" || type === "sage_ubs") {
        router.push(`/dashboard/connectors/${config.id}/${type}`);
        return;
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't connect.");
    } finally {
      setCreatingType(null);
    }
  }

  async function onDisconnect(id: string) {
    if (
      !window.confirm(
        "Disconnect this connector? Your synced data stays — only future syncs are stopped.",
      )
    )
      return;
    try {
      await api.deleteConnectorConfig(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't disconnect.");
    }
  }

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">Connectors</h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            Pull customers + items from systems you already use
          </p>
        </header>

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error"
          >
            {error}
          </div>
        )}

        <ActiveConnections configs={configs} onDisconnect={onDisconnect} />

        <Section title="Available connectors">
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {CATALOG.map((entry) => (
              <ConnectorCard
                key={entry.type}
                entry={entry}
                creating={creatingType === entry.type}
                onConnect={() => onConnect(entry.type)}
              />
            ))}
          </div>
        </Section>

        <Section title="Open conflicts">
          <Link
            href="/dashboard/connectors/conflicts"
            className="inline-flex items-center gap-2 rounded-xl border border-slate-100 bg-white px-4 py-3 text-2xs text-ink hover:border-slate-200"
          >
            View the conflict queue →
          </Link>
        </Section>
      </div>
    </AppShell>
  );
}

function ActiveConnections({
  configs,
  onDisconnect,
}: {
  configs: IntegrationConfigRow[] | null;
  onDisconnect: (id: string) => void;
}) {
  if (configs === null) return <Loading label="Loading connectors…" />;
  if (configs.length === 0) {
    return (
      <Section title="Active connections">
        <div className="rounded-xl border border-slate-100 bg-white px-5 py-6 text-center text-2xs text-slate-500">
          No connectors yet. Pick one below to get started.
        </div>
      </Section>
    );
  }
  return (
    <Section title="Active connections">
      <div className="overflow-x-auto rounded-xl border border-slate-100 bg-white">
        <table className="w-full text-2xs">
          <thead className="bg-slate-50 text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Connector
              </th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">
                Last sync
              </th>
              <th className="px-3 py-2 text-left font-medium uppercase tracking-wider">Status</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {configs.map((config) => {
              const meta = CATALOG.find((c) => c.type === config.connector_type);
              return (
                <tr key={config.id} className="hover:bg-slate-50">
                  <td className="px-3 py-3">
                    <div className="font-medium text-ink">
                      {meta?.label ?? config.connector_type}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-slate-600">
                    {config.last_sync_at ? new Date(config.last_sync_at).toLocaleString() : "—"}
                  </td>
                  <td className="px-3 py-3">
                    <SyncStatusPill status={config.last_sync_status} />
                  </td>
                  <td className="px-3 py-3 text-right">
                    {config.connector_type === "csv" && (
                      <Link
                        href={`/dashboard/connectors/${config.id}/upload`}
                        className="mr-3 inline-flex items-center gap-1 text-2xs font-medium text-ink hover:underline"
                      >
                        <Upload className="h-3.5 w-3.5" />
                        Upload CSV
                      </Link>
                    )}
                    {(config.connector_type === "autocount" ||
                      config.connector_type === "sql_account" ||
                      config.connector_type === "sage_ubs") && (
                      <Link
                        href={`/dashboard/connectors/${config.id}/${config.connector_type}`}
                        className="mr-3 inline-flex items-center gap-1 text-2xs font-medium text-ink hover:underline"
                      >
                        <Upload className="h-3.5 w-3.5" />
                        Upload{" "}
                        {config.connector_type === "autocount"
                          ? "AutoCount"
                          : config.connector_type === "sql_account"
                            ? "SQL Account"
                            : "Sage UBS"}
                      </Link>
                    )}
                    <button
                      type="button"
                      onClick={() => onDisconnect(config.id)}
                      className="inline-flex items-center gap-1 text-2xs font-medium text-slate-500 hover:text-error"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Disconnect
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function ConnectorCard({
  entry,
  creating,
  onConnect,
}: {
  entry: CatalogEntry;
  creating: boolean;
  onConnect: () => void;
}) {
  const Icon = entry.icon;
  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-xl border bg-white p-4",
        entry.shipped ? "border-slate-100" : "border-slate-100/60 opacity-60",
      )}
    >
      <div className="flex items-start gap-2">
        <div className="rounded-lg bg-ink/[0.05] p-2">
          <Icon className="h-4 w-4 text-ink" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-ink">{entry.label}</h3>
          <p className="mt-1 text-2xs text-slate-500">{entry.description}</p>
        </div>
      </div>
      <div className="mt-1">
        {entry.shipped ? (
          <Button size="sm" onClick={onConnect} disabled={creating}>
            {creating ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Connecting…
              </>
            ) : (
              "Connect"
            )}
          </Button>
        ) : (
          <span className="inline-flex rounded-md bg-slate-100 px-2 py-1 text-[10px] font-medium uppercase tracking-wider text-slate-500">
            Coming soon
          </span>
        )}
      </div>
    </div>
  );
}

function SyncStatusPill({ status }: { status: IntegrationConfigRow["last_sync_status"] }) {
  const tone =
    status === "applied"
      ? "bg-success/10 text-success"
      : status === "proposed"
        ? "bg-signal/15 text-ink"
        : status === "failed"
          ? "bg-error/10 text-error"
          : "bg-slate-100 text-slate-500";
  return (
    <span
      className={cn(
        "inline-flex rounded-sm px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider",
        tone,
      )}
    >
      {status.replace(/_/g, " ")}
    </span>
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

function Loading({ label }: { label: string }) {
  return (
    <div className="grid place-items-center px-5 py-12 text-2xs uppercase tracking-wider text-slate-400">
      {label}
    </div>
  );
}
