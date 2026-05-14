// Stagger-delay helper. Lives in its own module (no "use client") so server
// components can call it directly during render — re-exporting it from the
// "use client" Reveal module would turn it into a client reference and the
// server-side call would resolve to undefined at runtime.

export function staggerDelay(index: number, base = 0.06): number {
  return Math.min(base * index, 0.32);
}
