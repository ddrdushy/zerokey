"use client";

// Section 1 of LANDING_PAGE.md — sticky navigation. Wordmark left, primary
// nav, language switcher, dual CTAs. Mobile collapses to a hamburger but
// keeps the trial CTA visible (per spec). Nav links get a subtle underline
// reveal on hover via the `zk` motion curve.
//
// Language switcher: dropdown with the four launch locales. Switching is
// instant (no page reload) — the client-side i18n layer dispatches a
// `zk-locale-change` event that every `useT()` subscriber re-renders on.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Check, ChevronDown, Globe, Menu, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { LOCALE_LABELS, SUPPORTED_LOCALES, setLocale, useT, useLocale, type Locale } from "@/lib/i18n";

const HEADER_EASE = [0.16, 1, 0.3, 1] as const;

// Two-letter "chip" the language switcher shows when closed. Keeps the
// header tight and recognisable across scripts.
const LOCALE_CHIP: Record<Locale, string> = {
  "en-MY": "EN",
  "bm-MY": "BM",
  "zh-MY": "中",
  "ta-MY": "த",
};

export function Header() {
  const t = useT();
  const locale = useLocale();
  const reduced = useReducedMotion();

  const [open, setOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const langRef = useRef<HTMLDivElement>(null);

  const NAV = [
    { href: "/product", label: t("landing.header.nav.product") },
    { href: "/pricing", label: t("landing.header.nav.pricing") },
    { href: "/customers", label: t("landing.header.nav.customers") },
    { href: "/resources", label: t("landing.header.nav.resources") },
  ];

  // Close mobile sheet at md+
  useEffect(() => {
    if (!open) return;
    const mq = window.matchMedia("(min-width: 768px)");
    const close = () => setOpen(false);
    mq.addEventListener("change", close);
    return () => mq.removeEventListener("change", close);
  }, [open]);

  // Body scroll lock while sheet is open
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Close language popover on outside click / escape
  useEffect(() => {
    if (!langOpen) return;
    function onDown(e: MouseEvent) {
      if (langRef.current && !langRef.current.contains(e.target as Node)) setLangOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setLangOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [langOpen]);

  function pickLocale(l: Locale) {
    setLocale(l);
    setLangOpen(false);
  }

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
          {/* Language switcher */}
          <div ref={langRef} className="relative hidden md:block">
            <button
              type="button"
              onClick={() => setLangOpen((v) => !v)}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold text-ink transition-colors duration-ack hover:bg-slate-100"
              aria-haspopup="listbox"
              aria-expanded={langOpen}
              aria-label={t("landing.header.lang_label")}
            >
              <Globe size={14} className="text-slate-400" />
              <span>{LOCALE_CHIP[locale]}</span>
              <ChevronDown
                size={12}
                className={`text-slate-400 transition-transform duration-ack ${langOpen ? "rotate-180" : ""}`}
              />
            </button>
            <AnimatePresence>
              {langOpen ? (
                <motion.ul
                  role="listbox"
                  initial={reduced ? false : { opacity: 0, y: -4 }}
                  animate={reduced ? undefined : { opacity: 1, y: 0 }}
                  exit={reduced ? undefined : { opacity: 0, y: -4 }}
                  transition={{ duration: 0.18, ease: HEADER_EASE }}
                  className="absolute right-0 mt-2 w-48 overflow-hidden rounded-md border border-slate-100 bg-white shadow-lg"
                >
                  {SUPPORTED_LOCALES.map((l) => (
                    <li key={l}>
                      <button
                        type="button"
                        onClick={() => pickLocale(l)}
                        role="option"
                        aria-selected={l === locale}
                        className="flex w-full items-center justify-between px-3 py-2 text-left text-sm text-ink transition-colors duration-ack hover:bg-slate-50"
                      >
                        <span>{LOCALE_LABELS[l]}</span>
                        {l === locale ? <Check size={14} className="text-ink" /> : null}
                      </button>
                    </li>
                  ))}
                </motion.ul>
              ) : null}
            </AnimatePresence>
          </div>

          <Link
            href="/sign-in"
            className="hidden text-xs font-medium text-slate-600 transition-colors duration-ack hover:text-ink md:inline"
          >
            {t("landing.header.signin")}
          </Link>
          {/* DESKTOP_PIVOT_PLAN — the primary CTA now points at /download
              (installer + license CTA) instead of the old SaaS sign-up. */}
          <Link href="/download">
            <Button size="sm" variant="primary">
              {t("landing.header.cta")}
            </Button>
          </Link>

          {/* Hamburger — mobile only */}
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

              <div className="mt-2 border-t border-slate-100 pt-3">
                <div className="px-3 text-2xs font-semibold uppercase tracking-wider text-slate-400">
                  {t("landing.header.lang_label")}
                </div>
                <ul className="mt-2 grid grid-cols-2 gap-1">
                  {SUPPORTED_LOCALES.map((l) => (
                    <li key={l}>
                      <button
                        type="button"
                        onClick={() => {
                          pickLocale(l);
                          setOpen(false);
                        }}
                        className={`flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors duration-ack ${
                          l === locale ? "bg-slate-100 text-ink" : "text-slate-600 hover:bg-slate-50"
                        }`}
                      >
                        <span>{LOCALE_LABELS[l]}</span>
                        {l === locale ? <Check size={14} /> : null}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="mt-3 border-t border-slate-100 pt-3">
                <Link
                  href="/sign-in"
                  onClick={() => setOpen(false)}
                  className="block rounded-md px-3 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-ink"
                >
                  {t("landing.header.signin")}
                </Link>
              </div>
            </nav>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </header>
  );
}
