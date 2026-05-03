"use client";

// Shared tab strip for the customer-side Settings area. Each tab is a
// full Next.js route under /dashboard/settings/, so navigation between
// tabs is just a Link click — no client-side tab state to manage. The
// active tab is derived from the current pathname so deep-linking
// (e.g. directly to /dashboard/settings/members) highlights the right
// tab automatically.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type Tab = {
  href: string;
  label: string;
  /** Match prefix for `pathname?.startsWith`. Default: exact match. */
  match?: "exact" | "prefix";
  /** When set, the tab is hidden unless this feature flag resolves true for the active org. */
  flag?: string;
};

const TABS: Tab[] = [
  { href: "/dashboard/settings", label: "Organization", match: "exact" },
  { href: "/dashboard/settings/members", label: "Members" },
  { href: "/dashboard/settings/api-keys", label: "API keys", flag: "api_ingestion" },
  { href: "/dashboard/settings/notifications", label: "Notifications" },
  { href: "/dashboard/settings/billing", label: "Billing" },
  { href: "/dashboard/settings/webhooks", label: "Webhooks", flag: "webhooks" },
  { href: "/dashboard/settings/integrations", label: "Integrations" },
  { href: "/dashboard/settings/sso", label: "SSO", flag: "sso" },
];

export function SettingsTabs() {
  const pathname = usePathname();
  const [flags, setFlags] = useState<Record<string, boolean> | null>(null);

  useEffect(() => {
    api
      .featureFlags()
      .then((r) => setFlags(r.flags))
      // Fail-open during the brief window where the endpoint is loading
      // — the worst case is a tab is visible that the user can't use,
      // which is no worse than today.
      .catch(() => setFlags({}));
  }, []);

  const visible = TABS.filter(
    (t) => !t.flag || flags === null || flags[t.flag] === true,
  );

  return (
    <nav className="flex flex-wrap items-center gap-1 border-b border-slate-100 pb-px">
      {visible.map((tab) => {
        const active =
          tab.match === "prefix" ? pathname?.startsWith(tab.href) : pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={cn(
              "relative -mb-px border-b-2 px-3 py-2 text-2xs font-medium transition",
              active ? "border-ink text-ink" : "border-transparent text-slate-500 hover:text-ink",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
