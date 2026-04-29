"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ChevronDown,
  FileText,
  Inbox,
  LayoutDashboard,
  LogOut,
  Package,
  Plug,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";

import { api, type Me } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useT, getLocale, setLocale, SUPPORTED_LOCALES, LOCALE_LABELS } from "@/lib/i18n";
import { ImpersonationBanner } from "@/components/admin/ImpersonationBanner";
import { NotificationBell } from "./NotificationBell";
import { CertExpiryBanner } from "./CertExpiryBanner";

// Persistent shell that wraps every authenticated page. The sidebar groups
// follow the bounded-context map from ARCHITECTURE.md; pages that aren't
// built yet are visibly disabled so the user knows what's coming.

type NavItem = {
  // Slice 86 — labels resolve through the i18n table at render
  // time. ``labelKey`` is a translation key (e.g. "nav.invoices");
  // the EN fallback is kept in en.ts.
  labelKey: string;
  href?: string;
  icon: React.ComponentType<{ className?: string }>;
  disabled?: boolean;
};

type NavGroup = {
  labelKey?: string;
  items: NavItem[];
};

const NAV_GROUPS: NavGroup[] = [
  {
    items: [{ labelKey: "nav.dashboard", href: "/dashboard", icon: LayoutDashboard }],
  },
  {
    labelKey: "nav.workflow",
    items: [
      { labelKey: "nav.inbox", href: "/dashboard/inbox", icon: Inbox },
      { labelKey: "nav.invoices", href: "/dashboard/invoices", icon: FileText },
      { labelKey: "nav.approvals", href: "/dashboard/approvals", icon: ShieldCheck },
      { labelKey: "nav.customers", href: "/dashboard/customers", icon: Users },
      { labelKey: "nav.items", href: "/dashboard/items", icon: Package },
      { labelKey: "nav.connectors", href: "/dashboard/connectors", icon: Plug },
    ],
  },
  {
    labelKey: "nav.compliance",
    items: [
      { labelKey: "nav.audit", href: "/dashboard/audit", icon: ShieldCheck },
      { labelKey: "nav.engines", href: "/dashboard/engines", icon: Sparkles },
    ],
  },
  {
    labelKey: "nav.settings_group",
    items: [{ labelKey: "nav.settings", href: "/dashboard/settings", icon: Settings }],
  },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch(() => router.replace("/sign-in"));
  }, [router]);

  async function onLogout() {
    await api.logout().catch(() => {});
    router.replace("/sign-in");
  }

  return (
    <div className="flex min-h-screen flex-col bg-paper">
      {me?.impersonation && <ImpersonationBanner ctx={me.impersonation} />}
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <div className="flex flex-1 flex-col">
          <TopBar me={me} menuOpen={menuOpen} setMenuOpen={setMenuOpen} onLogout={onLogout} />
          {me && <CertExpiryBanner />}
          <main className="flex-1 px-4 py-6 md:px-8 md:py-8">
            {error && (
              <div className="mb-4 rounded-md border border-error bg-error/5 px-4 py-2 text-xs text-error">
                {error}
              </div>
            )}
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}

function Sidebar() {
  const pathname = usePathname();
  const t = useT();
  return (
    <aside className="hidden w-60 flex-col border-r border-slate-800 bg-ink text-paper md:flex">
      <Link
        href="/dashboard"
        className="flex items-center gap-2 px-6 py-5 font-display text-xl font-bold tracking-tight"
      >
        ZeroKey
      </Link>
      <nav className="flex-1 overflow-y-auto px-3 py-2">
        {NAV_GROUPS.map((group, idx) => (
          <div key={idx} className="mb-6">
            {group.labelKey && (
              <div className="px-3 py-2 text-2xs font-semibold uppercase tracking-wider text-slate-400">
                {t(group.labelKey)}
              </div>
            )}
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = item.href === pathname;
                const Icon = item.icon;
                const label = t(item.labelKey);
                const className = cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-xs font-medium transition-colors duration-ack ease-zk",
                  active
                    ? "bg-slate-800 text-paper"
                    : "text-slate-400 hover:bg-slate-800/50 hover:text-paper",
                  item.disabled && "cursor-not-allowed opacity-50 hover:bg-transparent",
                );
                if (item.disabled || !item.href) {
                  return (
                    <li key={item.labelKey}>
                      <span className={className} aria-disabled="true">
                        <Icon className="h-4 w-4" />
                        {label}
                        <span className="ml-auto text-2xs uppercase tracking-wider text-slate-500">
                          soon
                        </span>
                      </span>
                    </li>
                  );
                }
                return (
                  <li key={item.labelKey}>
                    <Link href={item.href} className={className}>
                      <Icon className="h-4 w-4" />
                      {label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
      <div className="border-t border-slate-800 px-6 py-4 text-2xs text-slate-400">
        Phase 2 build · pre-GA
      </div>
    </aside>
  );
}

function TopBar({
  me,
  menuOpen,
  setMenuOpen,
  onLogout,
}: {
  me: Me | null;
  menuOpen: boolean;
  setMenuOpen: (open: boolean) => void;
  onLogout: () => void;
}) {
  const initials =
    me?.email
      .split("@")[0]
      .split(/[._-]/)
      .map((s) => s[0]?.toUpperCase() ?? "")
      .join("")
      .slice(0, 2) || "··";

  const activeOrg = me?.memberships.find((m) => m.organization.id === me?.active_organization_id);

  return (
    <header className="sticky top-0 z-40 border-b border-slate-100 bg-paper/85 backdrop-blur">
      <div className="flex h-14 items-center gap-4 px-4 md:px-8">
        <div className="flex flex-1 items-center gap-2">
          <Search className="h-4 w-4 text-slate-400" aria-hidden />
          <input
            type="search"
            placeholder="Search invoices, customers, audit log…"
            className="h-9 max-w-md flex-1 bg-transparent text-sm text-ink placeholder-slate-400 outline-none"
            aria-label="Search"
          />
        </div>
        <NotificationBell />
        <div className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen(!menuOpen)}
            className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-slate-50"
          >
            <span className="grid h-8 w-8 place-items-center rounded-full bg-ink text-2xs font-semibold text-paper">
              {initials}
            </span>
            <div className="hidden text-left md:block">
              <div className="text-2xs font-medium text-ink">{me?.email ?? "…"}</div>
              <div className="text-2xs text-slate-400">
                {activeOrg?.organization.legal_name ?? "no active org"}
              </div>
            </div>
            <ChevronDown className="h-3 w-3 text-slate-400" />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-full mt-2 w-56 rounded-md border border-slate-100 bg-white p-1 shadow-md">
              <LanguageMenu />
              <div className="my-1 border-t border-slate-100" />
              <button
                type="button"
                onClick={onLogout}
                className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-xs text-ink hover:bg-slate-50"
              >
                <LogOut className="h-4 w-4" /> Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

// Slice 86 — language switcher in the user dropdown.
//
// Stored in localStorage immediately for instant flip + best-
// effort persisted to the server so it survives a fresh sign-in.
// Server failure is non-blocking: the local choice still applies
// for this session (the next sign-in re-reads server state).
function LanguageMenu() {
  const t = useT();
  const [active, setActive] = useState(getLocale());
  return (
    <div className="px-2 pb-1 pt-2">
      <div className="px-1 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        {t("settings.language.title")}
      </div>
      <div className="flex flex-col">
        {SUPPORTED_LOCALES.map((loc) => (
          <button
            key={loc}
            type="button"
            onClick={() => {
              setLocale(loc);
              setActive(loc);
              api.updatePreferences({ preferred_language: loc }).catch(() => {});
            }}
            className={cn(
              "flex items-center justify-between rounded-md px-2 py-1.5 text-xs hover:bg-slate-50",
              active === loc ? "font-medium text-ink" : "text-slate-600",
            )}
          >
            <span>{LOCALE_LABELS[loc]}</span>
            {active === loc && <span className="text-2xs text-success">✓</span>}
          </button>
        ))}
      </div>
    </div>
  );
}
