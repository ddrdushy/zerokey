// /help — help-center landing. Functional search that filters the article
// list by title + summary; topic cards group articles for browsing.

import { Header } from "@/components/landing/Header";
import { Footer } from "@/components/landing/Footer";
import { PageHero } from "@/components/marketing/PageHero";
import { HelpIndex } from "@/components/marketing/HelpIndex";

export default function HelpPage() {
  return (
    <>
      <Header />
      <main>
        <PageHero
          eyebrow="Help center"
          headline={
            <>
              Answers to the questions <em>customers actually ask</em>.
            </>
          }
          description="Browse by topic, search by keyword, or write to contact@symprio.com. We'd rather respond directly than make you guess."
        />
        <HelpIndex />
      </main>
      <Footer />
    </>
  );
}
