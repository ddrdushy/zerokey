// /legal/acceptable-use — what you can and cannot do with ZeroKey.

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Prose, LastUpdated } from "@/components/marketing/Prose";

export default function AcceptableUsePage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Legal"
        headline="Acceptable use policy"
        description="What you can and cannot do with ZeroKey. Short by design."
      />
      <Prose>
        <LastUpdated date="14 May 2026" />

        <p>
          We trust customers to use ZeroKey to do their work. The rules below exist to keep the
          platform safe and to protect other customers.
        </p>

        <h2>You must not</h2>
        <ul>
          <li>Submit invoices on behalf of a business you are not authorised to represent.</li>
          <li>Use the service to commit fraud, tax evasion or any other unlawful act.</li>
          <li>Upload content that does not belong to you or that infringes someone else&apos;s rights.</li>
          <li>Attempt to circumvent rate limits, security controls, or the published API contract.</li>
          <li>Scrape, mirror, or otherwise harvest the service or our marketing site.</li>
          <li>Attempt to reverse-engineer, decompile, or disassemble the service.</li>
          <li>Use the service to send unsolicited bulk communications.</li>
          <li>Share account credentials with unauthorised parties.</li>
        </ul>

        <h2>What happens if you do</h2>
        <p>
          If we detect a violation we will contact you to investigate. Severity dictates the
          response — from a warning, to suspension, to termination. We cooperate with lawful
          requests from Malaysian authorities where required.
        </p>

        <h2>Report abuse</h2>
        <p>
          If you spot something that looks like a violation, email{" "}
          <a href="mailto:contact@symprio.com">contact@symprio.com</a>. We take reports
          seriously and acknowledge within one business day.
        </p>
      </Prose>
    </MarketingPage>
  );
}
