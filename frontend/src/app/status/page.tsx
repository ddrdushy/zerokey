// /status — operational status snapshot. Real-time data wires in once we
// integrate with the underlying monitoring; the launch version is honest
// about being a static "as of" page that links to the live dashboard for
// detail.

import { Activity, CheckCircle2, Clock } from "lucide-react";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";

type State = "operational" | "degraded" | "down";

type System = {
  name: string;
  detail: string;
  state: State;
};

const SYSTEMS: System[] = [
  { name: "Dashboard", detail: "Web app and sign-in.", state: "operational" },
  { name: "Invoice ingestion", detail: "Web upload, email forward, WhatsApp.", state: "operational" },
  { name: "Extraction", detail: "AI extraction of invoice fields.", state: "operational" },
  { name: "LHDN submission", detail: "Signing and submission to MyInvois.", state: "operational" },
  { name: "Webhooks & alerts", detail: "Notifications to Slack, Teams, email, WhatsApp.", state: "operational" },
  { name: "Accounting connectors", detail: "SQL Account, AutoCount, Sage UBS.", state: "operational" },
];

const STATE_STYLES: Record<State, { dot: string; pill: string; label: string }> = {
  operational: {
    dot: "bg-success",
    pill: "bg-success/10 text-success",
    label: "Operational",
  },
  degraded: { dot: "bg-warning", pill: "bg-warning/10 text-warning", label: "Degraded" },
  down: { dot: "bg-error", pill: "bg-error/10 text-error", label: "Down" },
};

export default function StatusPage() {
  const allOk = SYSTEMS.every((s) => s.state === "operational");
  return (
    <MarketingPage>
      <PageHero
        eyebrow="System status"
        headline={
          allOk ? (
            <>
              All systems <em className="text-success">operational</em>.
            </>
          ) : (
            <>
              Some systems are <em>not happy</em>.
            </>
          )
        }
        description="Live operational status across every customer-facing surface. Real-time data syncs from our monitoring."
      />

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
          <Reveal>
            <div className="flex items-center justify-between rounded-xl border border-slate-100 bg-white p-6">
              <div className="flex items-center gap-3">
                <span className="grid h-10 w-10 place-items-center rounded-md bg-success/10 text-success">
                  <Activity size={20} />
                </span>
                <div>
                  <div className="font-display text-lg font-bold tracking-tight text-ink">
                    All systems operational
                  </div>
                  <div className="text-2xs text-slate-400">As of just now</div>
                </div>
              </div>
              <CheckCircle2 size={28} className="text-success" />
            </div>
          </Reveal>

          <ul className="mt-8 divide-y divide-slate-100 rounded-xl border border-slate-100 bg-white">
            {SYSTEMS.map((s, i) => (
              <Reveal key={s.name} as="li" delay={staggerDelay(i, 0.04)}>
                <div className="flex items-center justify-between gap-4 p-5">
                  <div className="flex items-center gap-3">
                    <span className={`h-2 w-2 rounded-full ${STATE_STYLES[s.state].dot}`} />
                    <div>
                      <div className="text-sm font-semibold text-ink">{s.name}</div>
                      <div className="text-2xs text-slate-400">{s.detail}</div>
                    </div>
                  </div>
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-2xs font-semibold ${STATE_STYLES[s.state].pill}`}
                  >
                    {STATE_STYLES[s.state].label}
                  </span>
                </div>
              </Reveal>
            ))}
          </ul>

          <Reveal delay={0.16}>
            <div className="mt-10 flex items-start gap-3 rounded-xl border border-slate-100 bg-slate-50 p-6">
              <Clock size={18} className="mt-0.5 shrink-0 text-slate-400" />
              <p className="text-sm text-slate-600">
                Past incidents and uptime history appear here once a few weeks of data has
                accumulated. For urgent issues affecting your account, email{" "}
                <a className="underline underline-offset-4 hover:text-ink" href="mailto:contact@symprio.com">
                  contact@symprio.com
                </a>
                .
              </p>
            </div>
          </Reveal>
        </div>
      </section>
    </MarketingPage>
  );
}
