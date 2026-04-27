// Landing page assembly per docs/LANDING_PAGE.md.
//
// Section coverage:
//   1  Header              ✓
//   2  Hero                ✓
//   3  Problem             ✓
//   4  How it works        ✓
//   5  Why ZeroKey         — deferred (positioning copy belongs to marketing pass)
//   6  Built for Malaysia  — deferred
//   7  Trust & security    ✓
//   8  Pricing             ✓ (placeholder numbers; canonical values in BUSINESS_MODEL.md)
//   9  Customer voices     — deferred (Option B placeholder per spec)
//  10  Personas            — deferred (after persona copy review)
//  11  FAQ                 ✓
//  12  Final CTA           ✓
//  13  Footer              ✓
//
// LANDING_PAGE.md §"Technical implementation" calls for the marketing site to
// eventually live in its own Next.js project; for Phase 1 it ships from the
// product app to keep the docker-compose surface small.

import { Header } from "@/components/landing/Header";
import { Hero } from "@/components/landing/Hero";
import { Problem } from "@/components/landing/Problem";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { Trust } from "@/components/landing/Trust";
import { Pricing } from "@/components/landing/Pricing";
import { Faq } from "@/components/landing/Faq";
import { FinalCta } from "@/components/landing/FinalCta";
import { Footer } from "@/components/landing/Footer";

export default function HomePage() {
  return (
    <>
      <Header />
      <main>
        <Hero />
        <Problem />
        <HowItWorks />
        <Trust />
        <Pricing />
        <Faq />
        <FinalCta />
      </main>
      <Footer />
    </>
  );
}
