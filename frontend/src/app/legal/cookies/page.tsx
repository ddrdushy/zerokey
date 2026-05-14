// /legal/cookies — cookies policy.

import { MarketingPage } from "@/components/marketing/MarketingPage";
import { PageHero } from "@/components/marketing/PageHero";
import { Prose, LastUpdated } from "@/components/marketing/Prose";

export default function CookiesPage() {
  return (
    <MarketingPage>
      <PageHero
        eyebrow="Legal"
        headline="Cookies policy"
        description="The cookies ZeroKey uses and the choices you have."
      />
      <Prose>
        <LastUpdated date="14 May 2026" />

        <p>
          ZeroKey uses a small number of cookies and equivalent technologies (local storage,
          session storage) to operate the service and to understand how the marketing site is
          used. This page explains what each one does.
        </p>

        <h2>Strictly necessary</h2>
        <p>
          These keep you signed in and protect the service from abuse. They cannot be switched
          off. They include the session cookie set when you sign in and an anti-forgery token on
          form submissions.
        </p>

        <h2>Preferences</h2>
        <p>
          These remember your language, theme, and a small set of UI choices. They are optional
          but the product feels worse without them.
        </p>

        <h2>Analytics</h2>
        <p>
          We use a privacy-respecting analytics tool to count visitors and understand which pages
          they find useful. We do not use Google Analytics on the marketing site for tracking, and
          we do not share analytics data with third parties for advertising.
        </p>

        <h2>Your choices</h2>
        <p>
          You can decline non-essential cookies on first visit and change your choice any time
          from the cookie banner. You can also delete all ZeroKey cookies from your browser
          settings — you&apos;ll be signed out and your preferences reset.
        </p>

        <hr />
        <p>
          <strong>Note for launch.</strong> A consent banner ships when analytics is wired up
          in production; until then no non-essential cookies are set.
        </p>
      </Prose>
    </MarketingPage>
  );
}
