"use client";

// Admin overview — landing for the platform-staff surface.
//
// Today this is a placeholder showing "you're in" with a brief
// inventory of what's wired and what's coming. Subsequent slices
// fill in the actual cross-tenant surfaces (audit log, tenant list,
// engine credentials).

import { ScrollText, Settings, ShieldCheck, Users } from "lucide-react";

import { AdminShell } from "@/components/admin/AdminShell";

const COMING_NEXT: Array<{
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  {
    title: "Platform audit log",
    description:
      "Every audit event across every tenant, in one chronologically-ordered table. Filter by action type, actor, or organization.",
    icon: ScrollText,
  },
  {
    title: "Tenant directory",
    description:
      "List of every Organization on the platform with state, member count, and recent ingestion activity.",
    icon: Users,
  },
  {
    title: "Engine credentials",
    description:
      "Edit per-engine API keys, hosts, and models without restarting the worker. Rotation lands on Engine.credentials.",
    icon: Settings,
  },
];

export default function AdminOverviewPage() {
  return (
    <AdminShell>
      <div className="flex flex-col gap-8">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Welcome back
          </h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            Platform operator surface · cross-tenant
          </p>
        </header>

        <section className="rounded-xl border border-slate-100 bg-white p-6">
          <div className="flex items-start gap-3">
            <div className="rounded-md bg-success/10 p-2 text-success">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div className="flex-1">
              <h2 className="font-display text-lg font-semibold">
                You&apos;re signed in as platform staff
              </h2>
              <p className="mt-1 text-sm text-slate-600">
                The admin namespace is org-agnostic by design — every page
                here reads across all tenants under super-admin elevation,
                with the elevation reason recorded on the audit log per
                request.
              </p>
            </div>
          </div>
        </section>

        <section>
          <h3 className="text-2xs font-medium uppercase tracking-wider text-slate-400">
            Coming next
          </h3>
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            {COMING_NEXT.map((item) => {
              const Icon = item.icon;
              return (
                <div
                  key={item.title}
                  className="rounded-xl border border-slate-100 bg-white p-4"
                >
                  <Icon className="h-4 w-4 text-slate-400" aria-hidden />
                  <div className="mt-2 text-sm font-medium text-ink">
                    {item.title}
                  </div>
                  <p className="mt-1 text-2xs leading-relaxed text-slate-500">
                    {item.description}
                  </p>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </AdminShell>
  );
}
