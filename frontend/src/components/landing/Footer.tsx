// Section 13 — footer. Same on every marketing page. Symprio attribution and
// the four language switchers; legal column near the copyright.

const COLUMNS: { heading: string; links: { label: string; href: string }[] }[] = [
  {
    heading: "Product",
    links: [
      { label: "Features", href: "/product" },
      { label: "Pricing", href: "/pricing" },
      { label: "Integrations", href: "/integrations" },
      { label: "Security", href: "/security" },
      { label: "Changelog", href: "/changelog" },
    ],
  },
  {
    heading: "Resources",
    links: [
      { label: "Documentation", href: "/docs" },
      { label: "Blog", href: "/blog" },
      { label: "Help center", href: "/help" },
      { label: "Status", href: "/status" },
      { label: "API reference", href: "/api" },
    ],
  },
  {
    heading: "Company",
    links: [
      { label: "About / Symprio", href: "/about" },
      { label: "Careers", href: "/careers" },
      { label: "Contact", href: "/contact" },
      { label: "Privacy", href: "/privacy" },
      { label: "Terms", href: "/terms" },
    ],
  },
  {
    heading: "Legal",
    links: [
      { label: "PDPA notice", href: "/legal/pdpa" },
      { label: "Cookies", href: "/legal/cookies" },
      { label: "Acceptable use", href: "/legal/acceptable-use" },
      { label: "DPA template", href: "/legal/dpa" },
    ],
  },
];

const LANGUAGES = ["English", "Bahasa Malaysia", "中文", "தமிழ்"];

export function Footer() {
  return (
    <footer className="border-t border-slate-100 bg-paper">
      <div className="mx-auto max-w-7xl px-4 py-12 md:px-8">
        <div className="grid gap-10 md:grid-cols-5">
          <div className="md:col-span-1">
            <div className="font-display text-xl font-bold tracking-tight">ZeroKey</div>
            <p className="mt-2 text-2xs text-slate-400">A product of Symprio Sdn Bhd</p>
          </div>
          {COLUMNS.map((col) => (
            <div key={col.heading}>
              <div className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                {col.heading}
              </div>
              <ul className="mt-3 space-y-2">
                {col.links.map((link) => (
                  <li key={link.href}>
                    <a className="text-xs text-slate-600 hover:text-ink" href={link.href}>
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-12 flex flex-col gap-4 border-t border-slate-100 pt-8 text-2xs text-slate-400 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap gap-3">
            {LANGUAGES.map((lang) => (
              <button key={lang} type="button" className="hover:text-ink">
                {lang}
              </button>
            ))}
          </div>
          <div>© 2026 Symprio Sdn Bhd. All rights reserved.</div>
        </div>
      </div>
    </footer>
  );
}
