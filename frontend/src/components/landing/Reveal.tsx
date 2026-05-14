"use client";

// Scroll-triggered fade-up reveal. One small client component used across
// every marketing section so the sections themselves stay server-rendered
// and tiny. Motion direction matches UX_PRINCIPLES.md — calm, ≤ 500ms,
// subtle Y offset, no bounce.

import { motion, useReducedMotion } from "framer-motion";
import type { Variants } from "framer-motion";
import type { ReactNode } from "react";

type Direction = "up" | "left" | "right" | "none";

type RevealProps = {
  children: ReactNode;
  direction?: Direction;
  delay?: number;
  /** When `false` (default), plays only once on first view. */
  replay?: boolean;
  /** Convert to a different intrinsic element (default `div`). */
  as?: "div" | "section" | "li" | "header" | "article";
  className?: string;
};

function offsetFor(direction: Direction) {
  switch (direction) {
    case "left":
      return { x: -16, y: 0 };
    case "right":
      return { x: 16, y: 0 };
    case "none":
      return { x: 0, y: 0 };
    case "up":
    default:
      return { x: 0, y: 16 };
  }
}

export function Reveal({
  children,
  direction = "up",
  delay = 0,
  replay = false,
  as = "div",
  className,
}: RevealProps) {
  const prefersReducedMotion = useReducedMotion();
  const offset = offsetFor(direction);

  const variants: Variants = prefersReducedMotion
    ? { hidden: { opacity: 1 }, visible: { opacity: 1 } }
    : {
        hidden: { opacity: 0, ...offset },
        visible: {
          opacity: 1,
          x: 0,
          y: 0,
          transition: {
            duration: 0.6,
            delay,
            ease: [0.16, 1, 0.3, 1], // matches `transitionTimingFunction.zk`
          },
        },
      };

  const common = {
    className,
    initial: "hidden" as const,
    whileInView: "visible" as const,
    viewport: { once: !replay, amount: 0.2 },
    variants,
  };

  // framer-motion 12 removed the `motion[tag]` dynamic accessor; route
  // each supported element explicitly so this stays a server-rendered
  // boundary safe component.
  switch (as) {
    case "section":
      return <motion.section {...common}>{children}</motion.section>;
    case "li":
      return <motion.li {...common}>{children}</motion.li>;
    case "header":
      return <motion.header {...common}>{children}</motion.header>;
    case "article":
      return <motion.article {...common}>{children}</motion.article>;
    case "div":
    default:
      return <motion.div {...common}>{children}</motion.div>;
  }
}

// `staggerDelay` lives in ./stagger.ts so it stays a plain, server-callable
// utility — re-exporting it from this `"use client"` module would mark it
// as a client reference and server components would resolve it to
// `undefined` at render time, crashing static-page generation.
