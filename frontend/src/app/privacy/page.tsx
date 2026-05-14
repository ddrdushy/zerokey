// /privacy — privacy policy. Copy is a reasonable starting point pending
// counsel review for GA. The PDPA notice at /legal/pdpa is the
// Malaysia-specific complement.

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Prose, LastUpdated } from "@/components/marketing/Prose";

export default function PrivacyPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Privacy"
        headline="Privacy policy"
        description="How ZeroKey collects, uses, and protects your information."
      />
      <Prose>
        <LastUpdated date="14 May 2026" />

        <p>
          ZeroKey is a product of Symprio Sdn Bhd. This policy explains what personal data we
          collect, why we collect it, how we use it, and the choices you have. We follow the
          Malaysian Personal Data Protection Act 2010 (PDPA) and apply the same standards
          regardless of where in the region you sign up from.
        </p>

        <h2>What we collect</h2>
        <p>We collect three kinds of information.</p>
        <ul>
          <li>
            <strong>Account information</strong>: your name, email, organisation name, business
            registration number, LHDN TIN, and the role you choose when you sign in.
          </li>
          <li>
            <strong>Invoice content you upload or send to us</strong>: PDFs, images, spreadsheets,
            structured payloads, and the data we extract from them — buyers, suppliers, items,
            amounts.
          </li>
          <li>
            <strong>Usage and security signals</strong>: IP address, browser, device type, the
            actions you take in the product, and the timestamps. Used for security and audit only.
          </li>
        </ul>

        <h2>How we use it</h2>
        <p>
          We use the data to deliver the service, to talk to you about your account, to keep your
          account secure, to meet our regulatory obligations under PDPA and LHDN MyInvois rules,
          and to improve the product. We do not sell your data. We do not use your invoice content
          for advertising or for training general-purpose models.
        </p>

        <h2>Where it lives</h2>
        <p>
          Your data is stored in a Malaysian data centre. We replicate to Singapore for disaster
          recovery only — failover, not regular operation. We do not move customer data outside
          the region without explicit consent.
        </p>

        <h2>Who we share with</h2>
        <p>
          We share data with vendors that help us operate (hosting, monitoring, AI extraction,
          payments) and only the minimum needed. We list our sub-processors publicly and notify
          customers before adding new ones materially involved in handling personal data.
        </p>

        <h2>Retention</h2>
        <p>
          We keep your data while your account is active. After cancellation, we retain it for the
          period required by Malaysian tax law (currently seven years for invoice records) and
          then delete it. You can export everything we have on you at any time from the dashboard.
        </p>

        <h2>Your rights</h2>
        <p>Under PDPA, you can:</p>
        <ul>
          <li>Access the personal data we hold about you.</li>
          <li>Correct anything that is wrong.</li>
          <li>Withdraw consent for non-essential processing.</li>
          <li>Request deletion (subject to legal retention obligations).</li>
        </ul>
        <p>
          Email <a href="mailto:privacy@symprio.com">privacy@symprio.com</a> to exercise any of
          the above. We respond within ten business days.
        </p>

        <h2>Changes to this policy</h2>
        <p>
          We update this page when the practice changes. The &ldquo;last updated&rdquo; date at
          the top reflects the most recent change. Material changes that affect your rights are
          notified by email.
        </p>

        <hr />
        <p>
          <strong>Note for launch.</strong> This policy is a working draft pending review by
          counsel for general availability. If you are evaluating ZeroKey for a regulated
          deployment, ask for the GA version before signing.
        </p>
      </Prose>
    </MarketingPage>
  );
}
