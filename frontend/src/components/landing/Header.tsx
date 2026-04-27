// Section 1 of LANDING_PAGE.md — sticky navigation. Wordmark left, primary nav,
// language switcher, dual CTAs. Mobile collapses to a hamburger but keeps the
// trial CTA visible (per spec).

import Link from "next/link";
import { Button } from "@/components/ui/button";

const NAV = [
  { href: "/product", label: "Product" },
  { href: "/pricing", label: "Pricing" },
  { href: "/customers", label: "Customers" },
  { href: "/resources", label: "Resources" },
];

export function Header() {
  return (
    <header className="sticky top-0 z-50 border-b border-slate-100 bg-paper/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 md:px-8">
        <Link href="/" className="font-display text-xl font-bold tracking-tight">
          ZeroKey
        </Link>
        <nav className="hidden items-center gap-8 md:flex">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="text-xs font-medium text-slate-600 hover:text-ink"
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          <button
            type="button"
            className="hidden text-xs font-medium text-slate-600 hover:text-ink md:inline"
            aria-label="Switch language"
          >
            EN
          </button>
          <Link
            href="/sign-in"
            className="hidden text-xs font-medium text-slate-600 hover:text-ink md:inline"
          >
            Sign in
          </Link>
          <Button size="sm" variant="primary">
            Start free trial
          </Button>
        </div>
      </div>
    </header>
  );
}
