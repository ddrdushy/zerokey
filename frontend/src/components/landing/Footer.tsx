"use client";

// Section 13 — footer. Same on every marketing page. Symprio attribution and
// the four language switchers; legal column near the copyright. Language
// buttons are functional — they flip the locale via the existing i18n layer.

import { Check } from "lucide-react";

import {
  LOCALE_LABELS,
  SUPPORTED_LOCALES,
  setLocale,
  useT,
  useLocale,
} from "@/lib/i18n";

const COLUMNS_FACTORY = (t: ReturnType<typeof useT>) => [
  {
    heading: t("landing.footer.col.product"),
    links: [
      { label: "Features", href: "/product" },
      { label: t("landing.header.nav.pricing"), href: "/pricing" },
      { label: "Integrations", href: "/integrations" },
      { label: "Security", href: "/security" },
      { label: "Changelog", href: "/changelog" },
    ],
  },
  {
    heading: t("landing.footer.col.resources"),
    links: [
      { label: "Documentation", href: "/docs" },
      { label: "Blog", href: "/blog" },
      { label: "Help center", href: "/help" },
      { label: "Status", href: "/status" },
      { label: "API reference", href: "/api" },
    ],
  },
  {
    heading: t("landing.footer.col.company"),
    links: [
      { label: "About / Symprio", href: "/about" },
      { label: "Careers", href: "/careers" },
      { label: "Contact", href: "/contact" },
      { label: "Privacy", href: "/privacy" },
      { label: "Terms", href: "/terms" },
    ],
  },
  {
    heading: t("landing.footer.col.legal"),
    links: [
      { label: "PDPA notice", href: "/legal/pdpa" },
      { label: "Cookies", href: "/legal/cookies" },
      { label: "Acceptable use", href: "/legal/acceptable-use" },
      { label: "DPA template", href: "/legal/dpa" },
    ],
  },
];

export function Footer() {
  const t = useT();
  const locale = useLocale();
  const columns = COLUMNS_FACTORY(t);

  return (
    <footer className="border-t border-slate-100 bg-paper">
      <div className="mx-auto max-w-7xl px-4 py-12 md:px-8">
        <div className="grid gap-10 md:grid-cols-5">
          <div className="md:col-span-1">
            <div className="font-display text-xl font-bold tracking-tight">ZeroKey</div>
            <p className="mt-2 text-2xs text-slate-400">{t("landing.footer.parent")}</p>
          </div>
          {columns.map((col) => (
            <div key={col.heading}>
              <div className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                {col.heading}
              </div>
              <ul className="mt-3 space-y-2">
                {col.links.map((link) => (
                  <li key={link.href}>
                    <a className="text-xs text-slate-600 hover:text-ink" href={link.href}>
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-12 flex flex-col gap-4 border-t border-slate-100 pt-8 text-2xs text-slate-400 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap gap-1">
            {SUPPORTED_LOCALES.map((l) => (
              <button
                key={l}
                type="button"
                onClick={() => setLocale(l)}
                className={[
                  "inline-flex items-center gap-1 rounded-md px-2 py-1 transition-colors duration-ack",
                  l === locale ? "bg-slate-100 text-ink" : "text-slate-400 hover:text-ink",
                ].join(" ")}
              >
                {l === locale ? <Check size={10} /> : null}
                <span>{LOCALE_LABELS[l]}</span>
              </button>
            ))}
          </div>
          <div>{t("landing.footer.copyright", { year: new Date().getFullYear() })}</div>
        </div>
      </div>
    </footer>
  );
}
