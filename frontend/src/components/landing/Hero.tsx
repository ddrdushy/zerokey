"use client";

// Section 2 — hero. Headline (8–12 words, customer outcome), tagline with the
// italics device, subhead naming pain + audience + timing + scope, dual CTAs,
// trust strip.
//
// Hero visual is a layered product mock: a realistic-looking validated
// invoice card on top, a faded sibling card peeking behind to suggest
// volume, and a floating "submitted to LHDN" badge that drops in once the
// "Validated" pill pops. Animation respects prefers-reduced-motion.

import { motion, useReducedMotion } from "framer-motion";
import type { Variants } from "framer-motion";
import { Calendar, CheckCircle2, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

const HERO_EASE = [0.16, 1, 0.3, 1] as const;

function buildVariants(reduced: boolean): { container: Variants; item: Variants } {
  if (reduced) {
    return {
      container: { hidden: { opacity: 1 }, visible: { opacity: 1 } },
      item: { hidden: { opacity: 1 }, visible: { opacity: 1 } },
    };
  }
  return {
    container: {
      hidden: {},
      visible: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } },
    },
    item: {
      hidden: { opacity: 0, y: 16 },
      visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: HERO_EASE } },
    },
  };
}

export function Hero() {
  const t = useT();
  const reduced = useReducedMotion();
  const { container, item } = buildVariants(!!reduced);

  const TRUST_LABELS = [
    t("landing.hero.trust.symprio"),
    t("landing.hero.trust.mdec"),
    t("landing.hero.trust.lhdn"),
  ];

  return (
    <section className="relative overflow-hidden border-b border-slate-100">
      {/* Decorative signal/glow blobs — pinned, low contrast, behind content. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-32 -top-32 h-96 w-96 rounded-full bg-signal opacity-20 blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -left-40 bottom-0 h-96 w-96 rounded-full bg-glow opacity-30 blur-3xl"
      />
      {/* Subtle dot grid layered behind the visual side. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 right-0 hidden w-1/2 md:block"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, rgba(10,14,26,0.06) 1px, transparent 0)",
          backgroundSize: "24px 24px",
        }}
      />

      <motion.div
        className="relative mx-auto grid max-w-7xl gap-12 px-4 py-16 md:grid-cols-2 md:px-8 md:py-24"
        initial="hidden"
        animate="visible"
        variants={container}
      >
        <div className="flex flex-col items-start gap-6">
          <motion.span
            variants={item}
            className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/60 px-3 py-1 text-2xs font-semibold uppercase tracking-wider text-ink backdrop-blur"
          >
            <span className="relative inline-flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-signal opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-signal" />
            </span>
            {t("landing.hero.live_pill")}
          </motion.span>

          <motion.h1
            variants={item}
            className="font-display text-4xl font-bold leading-[1.05] tracking-tight md:text-5xl lg:text-6xl"
          >
            {t("landing.hero.headline")}
          </motion.h1>

          <motion.p variants={item} className="font-display text-lg text-slate-600">
            {t("landing.hero.tagline_part1")}{" "}
            <em className="not-italic text-ink">{t("landing.hero.tagline_part2")}</em>
          </motion.p>

          <motion.p variants={item} className="max-w-xl text-lg text-slate-600">
            {t("landing.hero.subhead")}
          </motion.p>

          <motion.div variants={item} className="flex flex-wrap items-center gap-3">
            <Button variant="primary" size="lg">
              {t("landing.hero.cta_primary")}
            </Button>
            <Button variant="outline" size="lg">
              {t("landing.hero.cta_secondary")}
            </Button>
          </motion.div>

          <motion.ul
            variants={item}
            className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-2xs uppercase tracking-wider text-slate-400"
          >
            {TRUST_LABELS.map((label) => (
              <li key={label} className="flex items-center gap-2">
                <ShieldCheck size={12} className="text-slate-400" />
                {label}
              </li>
            ))}
          </motion.ul>
        </div>

        <motion.div variants={item} className="flex items-center justify-center">
          <HeroVisual reduced={!!reduced} />
        </motion.div>
      </motion.div>
    </section>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Hero visual — a realistic validated-invoice card. Layered behind it is a
// faded sibling card to suggest volume. A floating "Submitted to LHDN"
// pill drops in after the Validated state appears.

const LINE_ITEMS = [
  { desc: "Cloud subscription · Q2 2026", qty: 1, amount: "1,200.00" },
  { desc: "Implementation services", qty: 14, amount: "4,200.00" },
  { desc: "Annual support fee", qty: 1, amount: "800.00" },
];

function HeroVisual({ reduced }: { reduced: boolean }) {
  // Per-row entrance for the invoice lines.
  const row: Variants = reduced
    ? { hidden: { opacity: 1 }, visible: { opacity: 1 } }
    : {
        hidden: { opacity: 0, x: -8 },
        visible: (i: number) => ({
          opacity: 1,
          x: 0,
          transition: { delay: 0.6 + i * 0.1, duration: 0.4, ease: HERO_EASE },
        }),
      };

  return (
    <div aria-hidden="true" className="relative w-full max-w-md">
      {/* Sibling card behind — slightly rotated + faded, suggests volume. */}
      <div className="pointer-events-none absolute -right-4 top-4 h-full w-full -rotate-3 rounded-2xl border border-slate-100 bg-white/70 shadow-sm" />
      <div className="pointer-events-none absolute -left-3 top-2 h-full w-full rotate-2 rounded-2xl border border-slate-100 bg-white/60 shadow-sm" />

      {/* Main card — the actual invoice. */}
      <motion.article
        initial={reduced ? false : { opacity: 0, y: 12 }}
        animate={reduced ? undefined : { opacity: 1, y: 0 }}
        transition={{ delay: 0.2, duration: 0.6, ease: HERO_EASE }}
        className="relative rounded-2xl border border-slate-100 bg-white p-6 shadow-xl shadow-ink/5"
      >
        {/* Header */}
        <header className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <div className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-ink font-display text-2xs font-bold text-paper">
                S
              </div>
              <div className="text-xs font-semibold text-ink">Symprio Trading</div>
            </div>
            <div className="mt-3 flex items-center gap-3 text-2xs text-slate-400">
              <span className="font-mono">INV-2026-0418</span>
              <span className="text-slate-200">·</span>
              <span className="flex items-center gap-1">
                <Calendar size={11} /> 18 Apr 2026
              </span>
            </div>
          </div>
          <motion.span
            initial={reduced ? false : { scale: 0.85, opacity: 0 }}
            animate={reduced ? undefined : { scale: 1, opacity: 1 }}
            transition={{ delay: 1.3, duration: 0.4, ease: HERO_EASE }}
            className="inline-flex items-center gap-1 rounded-full bg-signal px-2.5 py-0.5 text-2xs font-semibold text-ink"
          >
            <CheckCircle2 size={11} strokeWidth={2.5} />
            Validated
          </motion.span>
        </header>

        {/* Divider */}
        <div className="mt-5 h-px w-full bg-slate-100" />

        {/* Line items */}
        <div className="mt-4 grid grid-cols-[1fr_auto_auto] gap-x-4 gap-y-2 text-2xs">
          <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">
            Description
          </div>
          <div className="text-right text-2xs font-medium uppercase tracking-wider text-slate-400">
            Qty
          </div>
          <div className="text-right text-2xs font-medium uppercase tracking-wider text-slate-400">
            Amount
          </div>
          {LINE_ITEMS.map((row_, i) => (
            <motion.div
              key={row_.desc}
              custom={i}
              variants={row}
              initial="hidden"
              animate="visible"
              className="contents"
            >
              <span className="truncate text-ink">{row_.desc}</span>
              <span className="text-right tabular-nums text-slate-600">{row_.qty}</span>
              <span className="text-right tabular-nums font-medium text-ink">{row_.amount}</span>
            </motion.div>
          ))}
        </div>

        {/* Totals */}
        <motion.div
          initial={reduced ? false : { opacity: 0 }}
          animate={reduced ? undefined : { opacity: 1 }}
          transition={{ delay: 1.0, duration: 0.4 }}
          className="mt-4 grid grid-cols-[1fr_auto] gap-y-1 border-t border-slate-100 pt-3 text-2xs tabular-nums"
        >
          <span className="text-slate-400">Subtotal</span>
          <span className="text-slate-600">RM 6,200.00</span>
          <span className="text-slate-400">SST (8%)</span>
          <span className="text-slate-600">RM 496.00</span>
          <span className="font-display font-bold text-ink">Total</span>
          <span className="font-display font-bold tabular-nums text-ink">RM 6,696.00</span>
        </motion.div>

        {/* LHDN footer */}
        <motion.div
          initial={reduced ? false : { opacity: 0, y: 6 }}
          animate={reduced ? undefined : { opacity: 1, y: 0 }}
          transition={{ delay: 1.2, duration: 0.4, ease: HERO_EASE }}
          className="mt-5 flex items-end justify-between gap-3 rounded-lg border border-slate-100 bg-paper/60 p-3"
        >
          <div className="min-w-0 flex-1">
            <div className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
              LHDN MyInvois
            </div>
            <div className="mt-1 font-mono text-2xs text-ink">a3f9···7d21</div>
            <div className="mt-1 text-2xs text-slate-400">Submitted 12s ago</div>
          </div>
          <QrPattern reduced={reduced} />
        </motion.div>

        {/* Decorative top accent strip */}
        <div className="absolute inset-x-6 top-0 h-px bg-gradient-to-r from-transparent via-signal/60 to-transparent" />
      </motion.article>

      {/* Floating "Submitted to LHDN" toast */}
      <motion.div
        initial={reduced ? false : { opacity: 0, y: 12, scale: 0.95 }}
        animate={reduced ? undefined : { opacity: 1, y: 0, scale: 1 }}
        transition={{ delay: 1.6, duration: 0.5, ease: HERO_EASE }}
        className="absolute -bottom-6 -left-4 flex items-center gap-2 rounded-full border border-slate-100 bg-white px-3 py-1.5 shadow-lg shadow-ink/10"
      >
        <span className="grid h-5 w-5 place-items-center rounded-full bg-signal">
          <CheckCircle2 size={12} className="text-ink" strokeWidth={2.5} />
        </span>
        <span className="text-2xs font-semibold text-ink">Submitted to LHDN</span>
        <span className="text-2xs text-slate-400">· 312ms</span>
      </motion.div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// QR pattern — 9×9 grid with three 3×3 finder corners (TL, TR, BL). Body
// cells follow a fixed deterministic seed so the dots are stable across
// renders and the pattern reads as a real QR rather than random noise.

const QR_SIZE = 9;
const FINDER_CORNERS: Array<[number, number]> = [
  [0, 0],
  [0, QR_SIZE - 3],
  [QR_SIZE - 3, 0],
];

function isFinderCell(r: number, c: number): boolean | null {
  for (const [fr, fc] of FINDER_CORNERS) {
    if (r >= fr && r < fr + 3 && c >= fc && c < fc + 3) {
      // Outer ring = dark; inner cell = dark center; the donut middle ring = light
      const inner = r === fr + 1 && c === fc + 1;
      const outer = r === fr || r === fr + 2 || c === fc || c === fc + 2;
      return inner || outer;
    }
  }
  return null;
}

// Deterministic "noise" — same cells dark on every render.
function bodyDark(r: number, c: number): boolean {
  return (r * 7 + c * 13 + r * c) % 3 === 0;
}

function QrPattern({ reduced }: { reduced: boolean }) {
  const cells: { r: number; c: number; dark: boolean }[] = [];
  for (let r = 0; r < QR_SIZE; r++) {
    for (let c = 0; c < QR_SIZE; c++) {
      const finder = isFinderCell(r, c);
      const dark = finder !== null ? finder : bodyDark(r, c);
      cells.push({ r, c, dark });
    }
  }
  return (
    <div className="grid h-14 w-14 grid-cols-9 grid-rows-9 gap-px rounded-md bg-white p-1 ring-1 ring-slate-100">
      {cells.map(({ r, c, dark }, i) => (
        <motion.div
          key={`${r}-${c}`}
          initial={reduced ? false : { opacity: 0 }}
          animate={reduced ? undefined : { opacity: 1 }}
          transition={{ delay: 0.5 + i * 0.005, duration: 0.15 }}
          className={dark ? "bg-ink" : "bg-paper"}
        />
      ))}
    </div>
  );
}
