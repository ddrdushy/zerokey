"use client";

// Platform-admin shell — distinct from the customer-facing AppShell.
// Different sidebar (cross-tenant surfaces), different brand mark
// (a subtle "ADMIN" badge), no organization switcher in the topbar
// because admin runs across all tenants.
//
// Auth: every admin page wraps its content in this shell. The shell
// fetches /api/v1/admin/me/ on mount; on 403 it redirects to
// /dashboard, on 401 it redirects to /sign-in. Page-level logic only
// runs after the shell confirms staff identity, so individual pages
// don't repeat the auth check.

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ChevronDown,
  LogOut,
  ScrollText,
  Settings,
  ShieldCheck,
  Users,
} from "lucide-react";

import { api, ApiError, type AdminMe } from "@/lib/api";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  soon?: boolean;
};

const NAV: NavItem[] = [
  { href: "/admin", label: "Overview", icon: ShieldCheck },
  { href: "/admin/audit", label: "Platform audit", icon: ScrollText, soon: true },
  { href: "/admin/tenants", label: "Tenants", icon: Users, soon: true },
  { href: "/admin/engines", label: "Engines", icon: Settings, soon: true },
];

export function AdminShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<AdminMe | null>(null);
  const [authError, setAuthError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .adminMe()
      .then((response) => {
        if (cancelled) return;
        setMe(response);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          // 401 = not authenticated → sign-in.
          // 403 = authenticated but not staff → kick them to the
          //       customer dashboard rather than dead-ending.
          if (err.status === 401) router.replace("/sign-in?next=/admin");
          else router.replace("/dashboard");
          return;
        }
        setAuthError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function onLogout() {
    try {
      await api.logout();
    } finally {
      router.replace("/sign-in");
    }
  }

  if (authError) {
    return (
      <div className="grid min-h-screen place-items-center bg-paper px-6 text-center">
        <div className="max-w-sm">
          <div className="text-2xs font-medium uppercase tracking-wider text-error">
            Could not load admin context
          </div>
          <p className="mt-2 text-sm text-slate-500">
            The platform admin API is unreachable. Try again, or sign back in.
          </p>
          <button
            type="button"
            onClick={() => router.replace("/sign-in")}
            className="mt-4 rounded-md bg-ink px-4 py-2 text-2xs font-medium text-paper hover:opacity-90"
          >
            Back to sign-in
          </button>
        </div>
      </div>
    );
  }

  if (!me) {
    return (
      <div className="grid min-h-screen place-items-center bg-paper text-2xs uppercase tracking-wider text-slate-400">
        Loading admin…
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-paper">
      <AdminSidebar />
      <div className="flex flex-1 flex-col">
        <AdminTopbar me={me} onLogout={onLogout} />
        <main className="flex-1 px-4 py-6 md:px-8 md:py-10">{children}</main>
      </div>
    </div>
  );
}

function AdminSidebar() {
  const pathname = usePathname();
  return (
    <aside className="sticky top-0 hidden h-screen w-60 flex-shrink-0 flex-col border-r border-slate-100 bg-ink text-paper md:flex">
      <div className="flex h-14 items-center justify-between border-b border-paper/10 px-4">
        <div className="flex items-baseline gap-2">
          <span className="font-display text-lg font-bold tracking-tight">
            ZeroKey
          </span>
          <span className="rounded-sm bg-signal/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-signal">
            Admin
          </span>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 py-4">
        {NAV.map((item) => {
          const active =
            item.href === "/admin"
              ? pathname === "/admin"
              : pathname?.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.soon ? "#" : item.href}
              className={cn(
                "mb-1 flex items-center gap-2 rounded-md px-3 py-2 text-2xs font-medium transition",
                active
                  ? "bg-paper/10 text-paper"
                  : "text-paper/60 hover:bg-paper/5 hover:text-paper",
                item.soon && "cursor-not-allowed opacity-50",
              )}
              aria-disabled={item.soon}
            >
              <Icon className="h-4 w-4" />
              <span className="flex-1">{item.label}</span>
              {item.soon && (
                <span className="rounded-sm bg-paper/10 px-1.5 py-0.5 text-[9px] uppercase tracking-wider">
                  soon
                </span>
              )}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-paper/10 px-3 py-2 text-[10px] uppercase tracking-wider text-paper/40">
        Symprio Sdn Bhd
      </div>
    </aside>
  );
}

function AdminTopbar({ me, onLogout }: { me: AdminMe; onLogout: () => void }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const initials =
    me.email
      .split("@")[0]
      .split(/[._-]/)
      .map((s) => s[0]?.toUpperCase() ?? "")
      .join("")
      .slice(0, 2) || "··";

  return (
    <header className="sticky top-0 z-40 border-b border-slate-100 bg-paper/85 backdrop-blur">
      <div className="flex h-14 items-center gap-4 px-4 md:px-8">
        <div className="flex flex-1 items-center gap-2">
          <span className="text-2xs font-medium uppercase tracking-wider text-slate-400">
            Platform admin
          </span>
        </div>
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
              <div className="text-2xs font-medium text-ink">{me.email}</div>
              <div className="text-2xs text-slate-400">Staff</div>
            </div>
            <ChevronDown className="h-3 w-3 text-slate-400" />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-full mt-2 w-56 rounded-md border border-slate-100 bg-white p-1 shadow-md">
              <Link
                href="/dashboard"
                onClick={() => setMenuOpen(false)}
                className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-xs text-ink hover:bg-slate-50"
              >
                Switch to customer view
              </Link>
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
