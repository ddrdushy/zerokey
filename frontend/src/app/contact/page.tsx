// /contact — channels, not a form. We make it clear which channel maps to
// which intent, so visitors self-route without us having to triage.

import { CalendarClock, HelpCircle, Mail, MessageCircle, Phone } from "lucide-react";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Reveal } from "@/components/landing/Reveal";
import { staggerDelay } from "@/components/landing/stagger";

const CHANNELS = [
  {
    icon: MessageCircle,
    label: "Sales",
    detail: "Pricing, demo, custom plans, procurement questions.",
    cta: { label: "sales@symprio.com", href: "mailto:sales@symprio.com?subject=ZeroKey%20enquiry" },
  },
  {
    icon: HelpCircle,
    label: "Support",
    detail: "Existing-customer issues. Faster from inside the product, but email works too.",
    cta: {
      label: "support@symprio.com",
      href: "mailto:support@symprio.com?subject=ZeroKey%20support",
    },
  },
  {
    icon: CalendarClock,
    label: "Book a demo",
    detail: "30-minute walkthrough on Zoom or in person if you&apos;re in KL.",
    cta: { label: "Book a slot", href: "/sign-up?intent=demo" },
  },
  {
    icon: Mail,
    label: "General / press",
    detail: "Anything that doesn&apos;t fit the above — partnerships, media, just-saying-hi.",
    cta: {
      label: "hello@symprio.com",
      href: "mailto:hello@symprio.com?subject=ZeroKey",
    },
  },
];

export default function ContactPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Contact"
        headline={
          <>
            We answer real emails <em>from real people</em>.
          </>
        }
        description="Pick the channel that matches your need. Most replies arrive within one Malaysian business day."
      />

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-7xl px-4 py-16 md:px-8 md:py-24">
          <ul className="grid gap-4 md:grid-cols-2">
            {CHANNELS.map((c, i) => {
              const Icon = c.icon;
              return (
                <Reveal key={c.label} as="li" delay={staggerDelay(i)}>
                  <div className="flex h-full flex-col gap-4 rounded-xl border border-slate-100 bg-white p-8 transition-transform duration-panel ease-zk hover:-translate-y-1 hover:shadow-lg">
                    <div className="flex items-center gap-3">
                      <span className="grid h-10 w-10 place-items-center rounded-md bg-ink/5 text-ink">
                        <Icon size={20} />
                      </span>
                      <h3 className="font-display text-lg font-bold tracking-tight text-ink">
                        {c.label}
                      </h3>
                    </div>
                    <p className="text-base text-slate-600">{c.detail}</p>
                    <a
                      href={c.cta.href}
                      className="mt-auto inline-flex items-center justify-center self-start rounded-md bg-ink px-5 py-2.5 text-sm font-medium text-paper transition-colors duration-ack ease-zk hover:bg-slate-800"
                    >
                      {c.cta.label}
                    </a>
                  </div>
                </Reveal>
              );
            })}
          </ul>
        </div>
      </section>

      <section className="border-b border-slate-100 bg-slate-50">
        <div className="mx-auto max-w-3xl px-4 py-16 md:px-8 md:py-24">
          <Reveal>
            <h2 className="font-display text-3xl font-bold tracking-tight md:text-4xl">
              Where we sit.
            </h2>
          </Reveal>
          <Reveal delay={0.06}>
            <div className="mt-8 grid gap-6 md:grid-cols-2">
              <div className="rounded-xl border border-slate-100 bg-white p-6">
                <div className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                  Symprio Sdn Bhd
                </div>
                <p className="mt-2 text-sm text-slate-600">
                  Kuala Lumpur, Malaysia
                </p>
                <p className="mt-1 text-sm text-slate-600">Asia/Kuala_Lumpur (GMT +8)</p>
              </div>
              <div className="rounded-xl border border-slate-100 bg-white p-6">
                <div className="flex items-center gap-2 text-2xs font-semibold uppercase tracking-wider text-slate-400">
                  <Phone size={12} /> Working hours
                </div>
                <p className="mt-2 text-sm text-slate-600">Mon – Fri, 09:00 – 18:00 MYT</p>
                <p className="mt-1 text-sm text-slate-600">
                  Urgent customer-impacting issues are watched after hours.
                </p>
              </div>
            </div>
          </Reveal>
        </div>
      </section>
    </MarketingPage>
  );
}
