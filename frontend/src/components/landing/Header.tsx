"use client";

// Section 1 of LANDING_PAGE.md — sticky navigation. Wordmark left, primary
// nav, language switcher, dual CTAs. Mobile collapses to a hamburger but
// keeps the trial CTA visible (per spec). Nav links get a subtle underline
// reveal on hover via the `zk` motion curve.

import { useEffect, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Menu, X } from "lucide-react";

import { Button } from "@/components/ui/button";

const NAV = [
  { href: "/product", label: "Product" },
  { href: "/pricing", label: "Pricing" },
  { href: "/customers", label: "Customers" },
  { href: "/resources", label: "Resources" },
];

const HEADER_EASE = [0.16, 1, 0.3, 1] as const;

export function Header() {
  const reduced = useReducedMotion();
  const [open, setOpen] = useState(false);

  // Close the mobile sheet whenever we cross the md breakpoint so the
  // sheet isn't stuck open with no visible trigger.
  useEffect(() => {
    if (!open) return;
    const mq = window.matchMedia("(min-width: 768px)");
    const close = () => setOpen(false);
    mq.addEventListener("change", close);
    return () => mq.removeEventListener("change", close);
  }, [open]);

  // Body scroll lock while sheet is open.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  return (
    <header className="sticky top-0 z-50 border-b border-slate-100 bg-paper/80 backdrop-blur supports-[backdrop-filter]:bg-paper/70">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 md:px-8">
        <Link
          href="/"
          className="font-display text-xl font-bold tracking-tight transition-opacity duration-ack hover:opacity-70"
        >
          ZeroKey
        </Link>

        <nav className="hidden items-center gap-8 md:flex" aria-label="Primary">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="group relative text-xs font-medium text-slate-600 transition-colors duration-ack hover:text-ink"
            >
              <span>{item.label}</span>
              <span
                aria-hidden="true"
                className="absolute inset-x-0 -bottom-1 h-0.5 origin-left scale-x-0 bg-ink transition-transform duration-panel ease-zk group-hover:scale-x-100"
              />
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-3">
          <button
            type="button"
            className="hidden text-xs font-medium text-slate-600 transition-colors duration-ack hover:text-ink md:inline"
            aria-label="Switch language"
          >
            EN
          </button>
          <Link
            href="/sign-in"
            className="hidden text-xs font-medium text-slate-600 transition-colors duration-ack hover:text-ink md:inline"
          >
            Sign in
          </Link>
          <Link href="/sign-up">
            <Button size="sm" variant="primary">
              Start free trial
            </Button>
          </Link>

          {/* Hamburger — visible on mobile only */}
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="ml-1 grid h-9 w-9 place-items-center rounded-md border border-slate-200 text-ink transition-colors duration-ack hover:bg-slate-50 md:hidden"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
          >
            {open ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>
      </div>

      <AnimatePresence>
        {open ? (
          <motion.div
            key="mobile-sheet"
            initial={reduced ? false : { opacity: 0, y: -8 }}
            animate={reduced ? undefined : { opacity: 1, y: 0 }}
            exit={reduced ? undefined : { opacity: 0, y: -8 }}
            transition={{ duration: 0.22, ease: HEADER_EASE }}
            className="border-t border-slate-100 bg-paper md:hidden"
          >
            <nav className="mx-auto flex max-w-7xl flex-col gap-1 px-4 py-4" aria-label="Mobile">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setOpen(false)}
                  className="rounded-md px-3 py-2.5 text-base font-medium text-ink transition-colors duration-ack hover:bg-slate-50"
                >
                  {item.label}
                </Link>
              ))}
              <div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-3">
                <Link
                  href="/sign-in"
                  onClick={() => setOpen(false)}
                  className="text-sm font-medium text-slate-600 hover:text-ink"
                >
                  Sign in
                </Link>
                <button type="button" className="text-2xs font-medium text-slate-400 hover:text-ink">
                  EN · BM · 中文 · தமிழ்
                </button>
              </div>
            </nav>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </header>
  );
}
