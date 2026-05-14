// English (en-MY) translation table — Slice 86.
//
// Keys are dot-namespaced by surface ("nav.*", "dashboard.*",
// "customers.*", etc.). New keys must land here first; the BM
// table is populated from this one.
//
// Variables in strings use `{name}` syntax — see translate() for
// substitution rules.

const en: Record<string, string> = {
  // Navigation (AppShell sidebar)
  "nav.dashboard": "Dashboard",
  "nav.inbox": "Inbox",
  "nav.invoices": "Invoices",
  "nav.approvals": "Approvals",
  "nav.customers": "Customers",
  "nav.items": "Items",
  "nav.connectors": "Connectors",
  "nav.compliance_posture": "Compliance posture",
  "nav.audit": "Audit log",
  "nav.engines": "Engine activity",
  "nav.settings": "Organization",
  "nav.help": "Help center",
  "nav.workflow": "Workflow",
  "nav.compliance": "Compliance",
  "nav.settings_group": "Settings",
  "nav.signout": "Sign out",

  // Dashboard
  "dashboard.title": "Dashboard",
  "dashboard.recent_uploads": "Recent uploads",
  "dashboard.empty.title": "No invoices yet",
  "dashboard.empty.body": "Drop your first invoice — PDF, image, Excel — to see it land here.",

  // Customers
  "customers.title": "Customers",
  "customers.subtitle": "Buyers ZeroKey has learned from your invoices",
  "customers.count": "{count} total",
  "customers.empty.title": "No customers yet",
  "customers.empty.body":
    "Customers appear here automatically as you submit invoices. Each new buyer ZeroKey reads creates a master record; subsequent invoices for that buyer auto-fill from it.",

  // Items
  "items.title": "Items",
  "items.subtitle": "Line-item descriptions ZeroKey has learned from your invoices",
  "items.empty.title": "No items yet",

  // Common actions
  "action.save": "Save corrections",
  "action.discard": "Discard",
  "action.upload": "Upload",
  "action.cancel": "Cancel",
  "action.confirm": "Confirm",
  "action.dropFirst": "Drop your first invoice →",

  // Auth
  "auth.signin.title": "Sign in",
  "auth.signin.email": "Email",
  "auth.signin.password": "Password",
  "auth.signin.submit": "Sign in",
  "auth.signin.error": "Invalid email or password.",

  // Settings — language picker
  "settings.language.title": "Language",
  "settings.language.helper":
    "Choose the language you'd like to see ZeroKey in. The data itself isn't translated.",

  // ──────────────────────────────────────────────────────────────────────
  // Marketing / landing surface. Keys here drive the public site:
  // header, hero, footer, final CTA, and the top-line of each section.
  // Section bodies are intentionally NOT translated yet — they need a
  // qualified translator pass before they go in front of customers.
  // ──────────────────────────────────────────────────────────────────────

  // Header
  "landing.header.nav.product": "Product",
  "landing.header.nav.pricing": "Pricing",
  "landing.header.nav.customers": "Customers",
  "landing.header.nav.resources": "Resources",
  "landing.header.signin": "Sign in",
  "landing.header.cta": "Start free trial",
  "landing.header.lang_label": "Language",

  // Hero
  "landing.hero.live_pill": "Live for LHDN Phase 4",
  "landing.hero.headline": "LHDN e-invoicing without the headaches.",
  "landing.hero.tagline_part1": "Drop the PDF.",
  "landing.hero.tagline_part2": "Drop the Keys.",
  "landing.hero.subhead":
    "Malaysian SMEs face penalties up to RM 20,000 per non-compliant invoice from January 2027. ZeroKey handles every invoice from upload to LHDN — accurate, audited, and fast.",
  "landing.hero.cta_primary": "Start free trial",
  "landing.hero.cta_secondary": "Book a demo",
  "landing.hero.trust.symprio": "A product of Symprio Sdn Bhd",
  "landing.hero.trust.mdec": "MDEC accredited",
  "landing.hero.trust.lhdn": "LHDN registered software intermediary",

  // Section H2s
  "landing.problem.headline":
    "From January 2027, every non-compliant invoice has a price tag.",
  "landing.howitworks.headline_a": "From a PDF to a validated LHDN submission, ",
  "landing.howitworks.headline_em": "without typing",
  "landing.trust.headline_a": "Built to BFSI standards. ",
  "landing.trust.headline_em": "Sold for SMEs.",
  "landing.pricing.headline": "Pricing that fits the invoices you actually send.",
  "landing.pricing.sub":
    "All plans include LHDN MyInvois submission. Free trial requires no credit card. Switch plans any time.",
  "landing.pricing.note":
    "All prices in MYR. 30-day money-back guarantee. Annual billing saves 15%.",
  "landing.faq.headline": "Frequently asked questions",
  "landing.whyzerokey.headline_a": "Three alternatives, three trade-offs. ",
  "landing.whyzerokey.headline_em": "Here is where we fit.",
  "landing.builtformy.eyebrow": "Built for Malaysian businesses",
  "landing.builtformy.headline_a": "Not an international product translated. ",
  "landing.builtformy.headline_em": "Malaysian.",
  "landing.builtformy.sub":
    "MyInvois has Malaysia-shaped requirements. The MSIC codes, the cancellation window, the regional languages, the local accounting systems. We started from those.",
  "landing.personas.headline_a": "Different shoes, ",
  "landing.personas.headline_em": "same regulator.",
  "landing.personas.sub":
    "Whichever side of the invoice you sit on, this is the shape of working with us.",

  // Final CTA
  "landing.cta_final.headline": "Stop dreading e-invoicing season.",
  "landing.cta_final.sub":
    "Drop a PDF. We sign, submit, and track. Your team keeps their day job.",
  "landing.cta_final.cta_primary": "Start free trial",
  "landing.cta_final.cta_secondary": "Book a demo",
  "landing.cta_final.note": "Free 14-day trial. No credit card. Cancel anytime.",

  // Footer
  "landing.footer.col.product": "Product",
  "landing.footer.col.resources": "Resources",
  "landing.footer.col.company": "Company",
  "landing.footer.col.legal": "Legal",
  "landing.footer.parent": "A product of Symprio Sdn Bhd",
  "landing.footer.copyright": "© {year} Symprio Sdn Bhd. All rights reserved.",
};

export default en;
