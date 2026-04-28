"use client";

// Inline SVG sparkline — bars, no axes, no labels. Designed to fit at
// the bottom of a KPI card without competing with the primary number.
//
// We use bars (not a line) because the typical platform-admin signal is
// "uneven daily volume" — a few zero days, a spike, a drop. Bars
// communicate gaps more honestly than a line that interpolates through
// missing days.

import type { SparklinePoint } from "@/lib/api";

type Props = {
  points: SparklinePoint[];
  /** Tailwind class for the bar fill. Default: bg-slate-400. */
  barClass?: string;
  /** Optional explicit max for the y-axis; default = max of points. */
  max?: number;
  /** Height in px. Default 28. */
  height?: number;
};

export function Sparkline({
  points,
  barClass = "fill-slate-400",
  max,
  height = 28,
}: Props) {
  if (!points || points.length === 0) return null;
  const maxValue = max ?? Math.max(1, ...points.map((p) => p.count));
  const width = points.length * 6 - 2; // 4px bar + 2px gap, no trailing gap

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={`14-day trend, max ${maxValue}`}
      preserveAspectRatio="none"
      className="block"
    >
      {points.map((p, i) => {
        const barHeight =
          maxValue > 0 ? Math.max(1, Math.round((p.count / maxValue) * height)) : 1;
        const x = i * 6;
        const y = height - barHeight;
        return (
          <rect
            key={p.date}
            x={x}
            y={y}
            width={4}
            height={barHeight}
            className={barClass}
          >
            <title>
              {p.date}: {p.count}
            </title>
          </rect>
        );
      })}
    </svg>
  );
}
