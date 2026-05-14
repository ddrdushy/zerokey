// Shared marketing-route shell: Header + main slot + Footer. Used by every
// non-application marketing route (/integrations, /security, /about, the
// legal pages, etc.) so each route file stays tight and consistent.

import type { ReactNode } from "react";

import { Header } from "@/components/landing/Header";
import { Footer } from "@/components/landing/Footer";

export function MarketingPage({ children }: { children: ReactNode }) {
  return (
    <>
      <Header />
      <main>{children}</main>
      <Footer />
    </>
  );
}
