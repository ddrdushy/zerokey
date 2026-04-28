"use client";

import { Line, LineChart, ResponsiveContainer } from "recharts";
import { ArrowDownRight, ArrowUpRight, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

// Vuexy's statistics strip → ZeroKey's KPI tiles. Four metrics that matter
// in our domain: ingestion volume, work in flight, validated outcomes,
// audit trail length.

export type Stat = {
  label: string;
  value: string;
  delta?: number;
  spark?: number[];
  icon: LucideIcon;
  tone?: "neutral" | "success" | "warning" | "info";
};

export function StatsStrip({ stats }: { stats: Stat[] }) {
  return (
    <section className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {stats.map((stat) => (
        <StatTile key={stat.label} stat={stat} />
      ))}
    </section>
  );
}

function StatTile({ stat }: { stat: Stat }) {
  const Icon = stat.icon;
  const data = (stat.spark ?? [4, 6, 5, 8, 6, 9, 7]).map((value, i) => ({ i, value }));
  const tone = stat.tone ?? "neutral";

  return (
    <div className="rounded-xl border border-slate-100 bg-white p-5">
      <div className="flex items-center justify-between">
        <div
          className={cn(
            "grid h-9 w-9 place-items-center rounded-lg",
            tone === "success" && "bg-success/10 text-success",
            tone === "warning" && "bg-warning/10 text-warning",
            tone === "info" && "bg-info/10 text-info",
            tone === "neutral" && "bg-slate-50 text-slate-600",
          )}
        >
          <Icon className="h-4 w-4" />
        </div>
        {stat.delta != null && (
          <div
            className={cn(
              "flex items-center gap-1 text-2xs font-medium",
              stat.delta >= 0 ? "text-success" : "text-error",
            )}
          >
            {stat.delta >= 0 ? (
              <ArrowUpRight className="h-3 w-3" />
            ) : (
              <ArrowDownRight className="h-3 w-3" />
            )}
            {Math.abs(stat.delta).toFixed(1)}%
          </div>
        )}
      </div>
      <div className="mt-4 text-2xs font-medium uppercase tracking-wider text-slate-400">
        {stat.label}
      </div>
      <div className="mt-1 flex items-end justify-between gap-3">
        <div className="font-display text-3xl font-bold tracking-tight text-ink">{stat.value}</div>
        <div className="h-10 w-24">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <Line
                type="monotone"
                dataKey="value"
                stroke="#0A0E1A"
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
