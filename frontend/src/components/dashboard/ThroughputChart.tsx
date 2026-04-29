"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// Pipeline throughput — the on-brand analogue of Vuexy's "Revenue Report".
// Two series: invoices validated by LHDN vs invoices that needed user review.
// Real series are joined to the EngineCall + AuditEvent rows in a later slice;
// for now we render a 14-day bucket from props with a placeholder dataset
// when no real data is provided.

const PLACEHOLDER = [
  { day: "Mon", validated: 4, review: 1 },
  { day: "Tue", validated: 6, review: 2 },
  { day: "Wed", validated: 8, review: 1 },
  { day: "Thu", validated: 5, review: 3 },
  { day: "Fri", validated: 9, review: 2 },
  { day: "Sat", validated: 2, review: 0 },
  { day: "Sun", validated: 1, review: 0 },
];

export type ThroughputPoint = {
  day: string;
  validated: number;
  review: number;
};

export function ThroughputChart({ data }: { data?: ThroughputPoint[] }) {
  const points = data && data.length > 0 ? data : PLACEHOLDER;
  return (
    <section className="rounded-xl border border-slate-100 bg-white p-6">
      <div className="flex items-baseline justify-between">
        <div>
          <h3 className="text-base font-semibold">Pipeline throughput</h3>
          <p className="text-2xs uppercase tracking-wider text-slate-400">last 7 days</p>
        </div>
        <div className="flex items-center gap-4 text-2xs">
          <Legend2 dot="bg-ink" label="Validated" />
          <Legend2 dot="bg-signal" label="Needs review" />
        </div>
      </div>
      <div className="mt-6 h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={points} barGap={4} barCategoryGap="20%">
            <CartesianGrid stroke="#E8E8E0" vertical={false} />
            <XAxis dataKey="day" stroke="#8A8A7F" tickLine={false} axisLine={false} fontSize={11} />
            <YAxis stroke="#8A8A7F" tickLine={false} axisLine={false} fontSize={11} width={28} />
            <Tooltip
              cursor={{ fill: "rgba(10,14,26,0.04)" }}
              contentStyle={{
                background: "#FAFAF7",
                border: "1px solid #E8E8E0",
                borderRadius: 8,
                fontSize: 12,
                color: "#0A0E1A",
              }}
              labelStyle={{ color: "#4A4A42", fontWeight: 500 }}
            />
            <Bar dataKey="validated" fill="#0A0E1A" radius={[4, 4, 0, 0]} maxBarSize={28} />
            <Bar dataKey="review" fill="#C7F284" radius={[4, 4, 0, 0]} maxBarSize={28} />
            <Legend content={() => null} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function Legend2({ dot, label }: { dot: string; label: string }) {
  return (
    <span className="flex items-center gap-2 text-slate-600">
      <span className={`h-2.5 w-2.5 rounded-full ${dot}`} />
      {label}
    </span>
  );
}
