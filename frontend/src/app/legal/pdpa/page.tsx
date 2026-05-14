// /legal/pdpa — Malaysian PDPA notice. Sits alongside the global privacy
// policy at /privacy and addresses the PDPA-specific obligations.

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Prose, LastUpdated } from "@/components/marketing/Prose";

export default function PdpaPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Legal"
        headline="PDPA notice"
        description="Our notice under the Malaysian Personal Data Protection Act 2010."
      />
      <Prose>
        <LastUpdated date="14 May 2026" />

        <p>
          This notice is provided under the Personal Data Protection Act 2010 (&ldquo;<strong>PDPA</strong>&rdquo;).
          It explains how Symprio Sdn Bhd (&ldquo;<strong>we</strong>&rdquo;) collects and
          processes personal data through the ZeroKey service.
        </p>

        <h2>Personal data we collect</h2>
        <ul>
          <li>Account profile — name, business email, organisation name, role.</li>
          <li>Organisation profile — business registration number, LHDN TIN, address.</li>
          <li>
            Invoice content — buyer and supplier names, addresses, contact numbers, identification
            numbers, line items, amounts.
          </li>
          <li>Usage records — IP address, browser, actions taken, timestamps.</li>
        </ul>

        <h2>Purpose</h2>
        <p>
          We process personal data for these purposes: to provide the service you subscribed to,
          to communicate with you about your account, to comply with Malaysian tax and e-invoicing
          regulations, to investigate security incidents, and to improve the product. We do not
          use your invoice content for advertising.
        </p>

        <h2>Disclosure</h2>
        <p>
          We disclose personal data to: LHDN (for invoice submission, with your authorisation),
          our processing vendors (hosting, monitoring, payments) under written contracts, our
          professional advisors, and regulators where legally required.
        </p>

        <h2>Cross-border transfer</h2>
        <p>
          Your personal data is stored in a Malaysian data centre. We replicate to Singapore for
          disaster recovery only and apply equivalent protections in both locations.
        </p>

        <h2>Retention</h2>
        <p>
          We retain personal data while your account is active and for the period required by
          Malaysian tax law after closure (currently seven years for invoice records). After that
          period, we delete it.
        </p>

        <h2>Your rights</h2>
        <p>You have the right to:</p>
        <ul>
          <li>Request access to the personal data we hold about you.</li>
          <li>Request correction of inaccurate data.</li>
          <li>Withdraw consent for non-essential processing.</li>
          <li>Lodge a complaint with the Personal Data Protection Commissioner of Malaysia.</li>
        </ul>

        <h2>Contact</h2>
        <p>
          Email <a href="mailto:contact@symprio.com">contact@symprio.com</a> for any PDPA matter.
          We respond within ten business days.
        </p>

        <hr />
        <p>
          <strong>Note for launch.</strong> This notice is a working draft pending review by
          counsel for general availability.
        </p>
      </Prose>
    </MarketingPage>
  );
}
