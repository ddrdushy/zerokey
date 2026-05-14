// /legal/dpa — data processing addendum (template). Enterprise customers
// typically want a signed DPA alongside the master agreement; this page
// outlines what ours covers and provides a request path for the executable
// PDF.

import { FileDown, FileText, Mail } from "lucide-react";

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Prose, LastUpdated } from "@/components/marketing/Prose";
import { Reveal } from "@/components/landing/Reveal";

export default function DpaPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Legal"
        headline="Data processing addendum"
        description="Our standard DPA for customers that need one. Available on request and signable through your usual flow."
      />

      <section className="border-b border-slate-100 bg-paper">
        <div className="mx-auto max-w-3xl px-4 py-12 md:px-8 md:py-16">
          <Reveal>
            <div className="grid gap-4 md:grid-cols-2">
              <a
                href="mailto:contact@symprio.com?subject=DPA%20request"
                className="flex items-center justify-between rounded-xl border border-slate-100 bg-white p-6 transition-all duration-panel ease-zk hover:-translate-y-1 hover:shadow-lg"
              >
                <div className="flex items-center gap-3">
                  <span className="grid h-10 w-10 place-items-center rounded-md bg-ink/5 text-ink">
                    <Mail size={18} />
                  </span>
                  <div>
                    <div className="text-base font-semibold text-ink">Request the DPA</div>
                    <div className="text-2xs text-slate-400">We send a signable PDF within 1 business day</div>
                  </div>
                </div>
                <FileText size={18} className="text-slate-400" />
              </a>
              <a
                href="mailto:contact@symprio.com?subject=DPA%20with%20edits"
                className="flex items-center justify-between rounded-xl border border-slate-100 bg-white p-6 transition-all duration-panel ease-zk hover:-translate-y-1 hover:shadow-lg"
              >
                <div className="flex items-center gap-3">
                  <span className="grid h-10 w-10 place-items-center rounded-md bg-ink/5 text-ink">
                    <FileDown size={18} />
                  </span>
                  <div>
                    <div className="text-base font-semibold text-ink">Have your own template?</div>
                    <div className="text-2xs text-slate-400">Send it over for review</div>
                  </div>
                </div>
                <FileText size={18} className="text-slate-400" />
              </a>
            </div>
          </Reveal>
        </div>
      </section>

      <Prose>
        <LastUpdated date="14 May 2026" />

        <h2>What our DPA covers</h2>
        <p>
          Our standard DPA covers Symprio&apos;s obligations when we process personal data on
          your behalf as part of the ZeroKey service. It is designed to satisfy Malaysian PDPA
          requirements and is consistent with international good practice for cross-region
          enterprise customers.
        </p>

        <h2>Headline terms</h2>
        <ul>
          <li>
            <strong>Roles.</strong> You are the data controller for the personal data you submit
            to ZeroKey; we are the data processor.
          </li>
          <li>
            <strong>Purpose.</strong> We process only as instructed by you and as needed to deliver
            the service.
          </li>
          <li>
            <strong>Security.</strong> We commit to specific organisational and technical
            measures, listed in the schedule.
          </li>
          <li>
            <strong>Sub-processors.</strong> Listed with the contract; we notify you before
            material changes.
          </li>
          <li>
            <strong>Sub-processor flow-down.</strong> Sub-processors are bound by terms no less
            protective than the ones we sign with you.
          </li>
          <li>
            <strong>Data subject requests.</strong> We assist you in responding to access,
            correction, and deletion requests.
          </li>
          <li>
            <strong>Breach notification.</strong> We notify you within 72 hours of becoming aware
            of a breach affecting your data.
          </li>
          <li>
            <strong>Audit rights.</strong> You have the right to audit our practices on
            reasonable notice and at your own cost.
          </li>
          <li>
            <strong>Return / deletion.</strong> On termination, we return or delete your data per
            your instruction, subject to legal retention.
          </li>
        </ul>

        <h2>Process</h2>
        <p>
          Email <a href="mailto:contact@symprio.com">contact@symprio.com</a> with your company name
          and your preferred signing flow (DocuSign / Adobe Sign / printed copy). We send a
          signable PDF within one business day.
        </p>

        <hr />
        <p>
          <strong>Note for launch.</strong> The published DPA is a working template pending
          review by counsel for general availability. Enterprise customers should ask for the GA
          version before signing.
        </p>
      </Prose>
    </MarketingPage>
  );
}
