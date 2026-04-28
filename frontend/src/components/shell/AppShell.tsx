"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Bell,
  ChevronDown,
  FileText,
  Inbox,
  LayoutDashboard,
  LogOut,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";

import { api, type Me } from "@/lib/api";
import { cn } from "@/lib/utils";

// Persistent shell that wraps every authenticated page. The sidebar groups
// follow the bounded-context map from ARCHITECTURE.md; pages that aren't
// built yet are visibly disabled so the user knows what's coming.

type NavItem = {
  label: string;
  href?: string;
  icon: React.ComponentType<{ className?: string }>;
  disabled?: boolean;
};

type NavGroup = {
  label?: string;
  items: NavItem[];
};

const NAV_GROUPS: NavGroup[] = [
  {
    items: [{ label: "Dashboard", href: "/dashboard", icon: LayoutDashboard }],
  },
  {
    label: "Workflow",
    items: [
      { label: "Inbox", href: "/dashboard/inbox", icon: Inbox, disabled: true },
      { label: "Invoices", href: "/dashboard/invoices", icon: FileText, disabled: true },
      { label: "Customers", href: "/dashboard/customers", icon: Users },
    ],
  },
  {
    label: "Compliance",
    items: [
      { label: "Audit log", href: "/dashboard/audit", icon: ShieldCheck },
      { label: "Engine activity", href: "/dashboard/engines", icon: Sparkles, disabled: true },
    ],
  },
  {
    label: "Settings",
    items: [
      { label: "Organization", href: "/dashboard/settings", icon: Settings, disabled: true },
    ],
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
    <div className="flex min-h-screen bg-paper">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <TopBar
          me={me}
          menuOpen={menuOpen}
          setMenuOpen={setMenuOpen}
          onLogout={onLogout}
        />
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
  );
}

function Sidebar() {
  const pathname = usePathname();
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
            {group.label && (
              <div className="px-3 py-2 text-2xs font-semibold uppercase tracking-wider text-slate-400">
                {group.label}
              </div>
            )}
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = item.href === pathname;
                const Icon = item.icon;
                const className = cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-xs font-medium transition-colors duration-ack ease-zk",
                  active
                    ? "bg-slate-800 text-paper"
                    : "text-slate-400 hover:bg-slate-800/50 hover:text-paper",
                  item.disabled && "cursor-not-allowed opacity-50 hover:bg-transparent",
                );
                if (item.disabled || !item.href) {
                  return (
                    <li key={item.label}>
                      <span className={className} aria-disabled="true">
                        <Icon className="h-4 w-4" />
                        {item.label}
                        <span className="ml-auto text-2xs uppercase tracking-wider text-slate-500">
                          soon
                        </span>
                      </span>
                    </li>
                  );
                }
                return (
                  <li key={item.label}>
                    <Link href={item.href} className={className}>
                      <Icon className="h-4 w-4" />
                      {item.label}
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

  const activeOrg = me?.memberships.find(
    (m) => m.organization.id === me?.active_organization_id,
  );

  return (
    <header className="sticky top-0 z-40 border-b border-slate-100 bg-paper/85 backdrop-blur">
      <div className="flex h-14 items-center gap-4 px-4 md:px-8">
        <div className="flex flex-1 items-center gap-2">
          <Search className="h-4 w-4 text-slate-400" aria-hidden />
          <input
            type="search"
            placeholder="Search invoices, customers, audit log…"
            className="h-9 flex-1 max-w-md bg-transparent text-sm text-ink placeholder-slate-400 outline-none"
            aria-label="Search"
          />
        </div>
        <button
          type="button"
          aria-label="Notifications"
          className="rounded-md p-2 text-slate-400 hover:bg-slate-50 hover:text-ink"
        >
          <Bell className="h-4 w-4" />
        </button>
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
