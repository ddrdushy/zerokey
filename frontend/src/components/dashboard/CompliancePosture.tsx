"use client";

import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";

// On-brand analogue of Vuexy's circular budget gauge — a compliance posture
// donut showing the share of invoices that landed validated vs flagged.

export function CompliancePosture({
  validated,
  needsReview,
  failed,
}: {
  validated: number;
  needsReview: number;
  failed: number;
}) {
  // Success rate = validated of (validated + failed). This is the
  // SAME definition the /dashboard/compliance page uses — Slice 102
  // unified the two so they don't disagree (the prior denominator
  // included needsReview, which made the donut read "0% validated"
  // for a tenant whose only completed invoice was passing).
  // ``needsReview`` still drives the segment colours below — the
  // donut visualises the work mix, the centre number scores it.
  const terminal = validated + failed;
  const total = terminal + needsReview;
  const score = terminal === 0 ? 0 : Math.round((validated / terminal) * 100);

  const data = [
    { name: "Validated", value: validated, fill: "#3FA568" },
    { name: "Needs review", value: needsReview, fill: "#E8A93A" },
    { name: "Failed", value: failed, fill: "#D4533F" },
  ].filter((d) => d.value > 0);

  // When there's no data, show a flat ring so the gauge still renders
  // rather than a confusing empty state.
  const display = data.length > 0 ? data : [{ name: "Empty", value: 1, fill: "#E8E8E0" }];

  return (
    <section className="flex flex-col rounded-xl border border-slate-100 bg-white p-6">
      <div>
        <h3 className="text-base font-semibold">Compliance posture</h3>
        <p className="text-2xs uppercase tracking-wider text-slate-400">last 30 days</p>
      </div>
      <div className="relative mt-2 h-44">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={display}
              dataKey="value"
              innerRadius={56}
              outerRadius={76}
              startAngle={90}
              endAngle={-270}
              isAnimationActive={false}
              stroke="none"
            >
              {display.map((d, i) => (
                <Cell key={i} fill={d.fill} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <div className="text-center">
            <div className="font-display text-3xl font-bold tracking-tight text-ink">
              {terminal === 0 ? "—" : `${score}%`}
            </div>
            <div className="text-2xs uppercase tracking-wider text-slate-400">
              {terminal === 0 ? "no completions yet" : "success rate"}
            </div>
          </div>
        </div>
      </div>
      <ul className="mt-4 space-y-2 text-2xs text-slate-600">
        <Row dot="bg-success" label="Validated" value={validated} />
        <Row dot="bg-warning" label="Needs review" value={needsReview} />
        <Row dot="bg-error" label="Failed" value={failed} />
      </ul>
    </section>
  );
}

function Row({ dot, label, value }: { dot: string; label: string; value: number }) {
  return (
    <li className="flex items-center justify-between">
      <span className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${dot}`} />
        {label}
      </span>
      <span className="font-mono">{value}</span>
    </li>
  );
}
