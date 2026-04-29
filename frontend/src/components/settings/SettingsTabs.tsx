"use client";

// Shared tab strip for the customer-side Settings area. Each tab is a
// full Next.js route under /dashboard/settings/, so navigation between
// tabs is just a Link click — no client-side tab state to manage. The
// active tab is derived from the current pathname so deep-linking
// (e.g. directly to /dashboard/settings/members) highlights the right
// tab automatically.

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

type Tab = {
  href: string;
  label: string;
  /** Match prefix for `pathname?.startsWith`. Default: exact match. */
  match?: "exact" | "prefix";
};

const TABS: Tab[] = [
  { href: "/dashboard/settings", label: "Organization", match: "exact" },
  { href: "/dashboard/settings/members", label: "Members" },
  { href: "/dashboard/settings/api-keys", label: "API keys" },
  { href: "/dashboard/settings/notifications", label: "Notifications" },
  { href: "/dashboard/settings/billing", label: "Billing" },
  { href: "/dashboard/settings/webhooks", label: "Webhooks" },
  { href: "/dashboard/settings/integrations", label: "Integrations" },
];

export function SettingsTabs() {
  const pathname = usePathname();
  return (
    <nav className="flex flex-wrap items-center gap-1 border-b border-slate-100 pb-px">
      {TABS.map((tab) => {
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
