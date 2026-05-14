// /terms — terms of service. Plain-English draft pending counsel review.

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Prose, LastUpdated } from "@/components/marketing/Prose";

export default function TermsPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Terms"
        headline="Terms of service"
        description="The contract between you and Symprio Sdn Bhd when you use ZeroKey."
      />
      <Prose>
        <LastUpdated date="14 May 2026" />

        <p>
          These terms govern your use of ZeroKey, a software service provided by Symprio Sdn Bhd
          (&ldquo;<strong>Symprio</strong>&rdquo;, &ldquo;<strong>we</strong>&rdquo;,
          &ldquo;<strong>us</strong>&rdquo;). By creating an account or using the service, you
          accept these terms.
        </p>

        <h2>The service</h2>
        <p>
          ZeroKey ingests, validates, signs and submits e-invoices on your behalf to LHDN MyInvois,
          and keeps an auditable record. The features available to you depend on your plan; we
          publish the plan inclusions on the pricing page.
        </p>

        <h2>Your account</h2>
        <p>
          You are responsible for keeping your account credentials secure, for the actions taken
          under your account, and for ensuring your team members are authorised to act on your
          behalf. Tell us immediately if you suspect unauthorised access.
        </p>

        <h2>Your data</h2>
        <p>
          You own the invoice content you upload and the data we extract from it. We process that
          data only to provide the service. See the <a href="/privacy">privacy policy</a> for the
          details.
        </p>

        <h2>Acceptable use</h2>
        <p>
          You agree to use ZeroKey lawfully and consistently with our{" "}
          <a href="/legal/acceptable-use">acceptable use policy</a>. We may suspend accounts that
          violate it.
        </p>

        <h2>Fees</h2>
        <p>
          Plan fees are billed monthly or annually as you select. Overages are billed per
          invoice at the published rate for your tier. You can change plans or cancel any time
          from the billing page. Cancellation takes effect at the end of the current billing
          period.
        </p>

        <h2>Money-back guarantee</h2>
        <p>
          If you cancel within thirty days of your first paid invoice and let us know in writing,
          we refund the most recent payment in full. The guarantee applies once per organisation.
        </p>

        <h2>Service availability</h2>
        <p>
          We aim for high availability but do not promise uninterrupted service. We&apos;ll
          announce planned maintenance in advance. Operational status is published at{" "}
          <a href="/status">/status</a>.
        </p>

        <h2>Liability</h2>
        <p>
          To the extent permitted by Malaysian law, our total liability under these terms is
          limited to the fees you paid us in the twelve months preceding the claim. Neither party
          is liable for indirect or consequential losses.
        </p>

        <h2>Termination</h2>
        <p>
          You can close your account any time. We can terminate or suspend your account if you
          materially breach these terms and don&apos;t fix the breach after a reasonable notice
          period.
        </p>

        <h2>Governing law</h2>
        <p>
          These terms are governed by the laws of Malaysia. Disputes are subject to the
          jurisdiction of the Malaysian courts.
        </p>

        <h2>Changes</h2>
        <p>
          We may update these terms when the service or the law evolves. We notify you of
          material changes by email at least thirty days before they take effect.
        </p>

        <hr />
        <p>
          <strong>Note for launch.</strong> This is a working draft pending review by counsel for
          general availability. Enterprise prospects should ask for the GA version (and the
          template DPA at <a href="/legal/dpa">/legal/dpa</a>) before signing.
        </p>
      </Prose>
    </MarketingPage>
  );
}
