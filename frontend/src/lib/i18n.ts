// ZeroKey i18n scaffold (Slice 86).
//
// We use a small client-side translation layer instead of
// route-segment-based i18n (Next.js App Router's preferred
// pattern) — for the SME audience the URL doesn't need to carry
// the locale, and adopting /[locale]/... would be a high-blast-
// radius restructure of the entire dashboard tree.
//
// Resolution order at boot:
//   1. localStorage("zk_locale") — last user choice (instant flip).
//   2. /api/v1/identity/me's preferred_language — server source of
//      truth, written when the user picks from the language menu.
//   3. navigator.language — browser hint.
//   4. "en-MY" — final fallback.
//
// Keys not present in the active locale fall back to the English
// table; missing keys log a warning in dev so an untranslated
// string is visible in the console rather than silently English.
//
// **Usage:** in a client component
//
//     import { useT } from "@/lib/i18n";
//     const t = useT();
//     return <h1>{t("dashboard.title")}</h1>;
//
// or, outside React (rare):
//
//     import { translate, getLocale } from "@/lib/i18n";
//     translate(getLocale(), "dashboard.title");

"use client";

import { useEffect, useState } from "react";

export const SUPPORTED_LOCALES = ["en-MY", "bm-MY", "zh-MY", "ta-MY"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];

export const LOCALE_LABELS: Record<Locale, string> = {
  "en-MY": "English",
  "bm-MY": "Bahasa Malaysia",
  "zh-MY": "中文",
  "ta-MY": "தமிழ்",
};

const STORAGE_KEY = "zk_locale";

import en from "@/locales/en";
import bm from "@/locales/bm";

// Translation tables. ZH + TA share the EN table for Slice 86 —
// they're listed as supported because the spec says they will be,
// but the strings themselves haven't been translated yet. Keys
// not present fall back to EN.
const TABLES: Record<Locale, Record<string, string>> = {
  "en-MY": en,
  "bm-MY": bm,
  "zh-MY": en,
  "ta-MY": en,
};

function isLocale(value: string): value is Locale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

export function getLocale(): Locale {
  if (typeof window === "undefined") return "en-MY";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored && isLocale(stored)) return stored;
  const nav = window.navigator.language;
  // Map common browser-language hints to our supported set.
  if (nav.startsWith("ms")) return "bm-MY";
  if (nav.startsWith("zh")) return "zh-MY";
  if (nav.startsWith("ta")) return "ta-MY";
  return "en-MY";
}

export function setLocale(locale: Locale) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, locale);
  // Notify subscribers — listeners on the locale event re-render.
  window.dispatchEvent(new CustomEvent("zk-locale-change", { detail: locale }));
}

/** Translate a key for the given locale, falling back to EN. */
export function translate(
  locale: Locale,
  key: string,
  vars?: Record<string, string | number>,
): string {
  const table = TABLES[locale] ?? TABLES["en-MY"];
  let value = table[key];
  if (value === undefined && locale !== "en-MY") {
    value = TABLES["en-MY"][key];
  }
  if (value === undefined) {
    if (process.env.NODE_ENV !== "production") {
      // eslint-disable-next-line no-console
      console.warn(`[i18n] missing key: ${key}`);
    }
    return key;
  }
  if (vars) {
    return value.replace(/\{(\w+)\}/g, (_m, name: string) =>
      vars[name] !== undefined ? String(vars[name]) : `{${name}}`,
    );
  }
  return value;
}

/** React hook — returns a `t` function that re-renders on locale change. */
export function useT() {
  const [locale, setActive] = useState<Locale>("en-MY");

  useEffect(() => {
    setActive(getLocale());
    function onChange(event: Event) {
      const detail = (event as CustomEvent<Locale>).detail;
      if (detail && isLocale(detail)) setActive(detail);
    }
    window.addEventListener("zk-locale-change", onChange);
    return () => window.removeEventListener("zk-locale-change", onChange);
  }, []);

  return (key: string, vars?: Record<string, string | number>) => translate(locale, key, vars);
}

/** React hook — returns the current locale. */
export function useLocale(): Locale {
  const [locale, setActive] = useState<Locale>("en-MY");
  useEffect(() => {
    setActive(getLocale());
    function onChange(event: Event) {
      const detail = (event as CustomEvent<Locale>).detail;
      if (detail && isLocale(detail)) setActive(detail);
    }
    window.addEventListener("zk-locale-change", onChange);
    return () => window.removeEventListener("zk-locale-change", onChange);
  }, []);
  return locale;
}
