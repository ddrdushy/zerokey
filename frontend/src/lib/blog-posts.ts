// Blog post catalog. Posts live inline as structured data — readable
// enough that a marketer can write a new one by copy/pasting the shape.
// When we have a real CMS this module becomes the seed source.

export type BlogPostMeta = {
  slug: string;
  title: string;
  /** ISO-ish display date — June 2026 etc. */
  date: string;
  author: string;
  authorTitle: string;
  /** Pull quote shown on the index card. */
  excerpt: string;
  readingMinutes: number;
};

export type BlogPost = BlogPostMeta & {
  /** Body as ordered sections — each gets an <h2>. */
  sections: { heading: string; paragraphs: string[]; bullets?: string[] }[];
};

export const BLOG_POSTS: BlogPost[] = [
  {
    slug: "what-phase-4-means-may-2026",
    title: "What Phase 4 means for a small business in May 2026",
    date: "May 2026",
    author: "Dushy",
    authorTitle: "Founder, Symprio",
    excerpt:
      "Phase 4 went live on 1 January 2026. Penalty enforcement starts 1 January 2027. Here's what to do this month, what to defer to July, and what you can stop worrying about altogether.",
    readingMinutes: 6,
    sections: [
      {
        heading: "The dates that actually matter",
        paragraphs: [
          "Phase 4 — businesses with annual turnover RM 1M–5M — became mandatory on 1 January 2026. That date has passed. From then on, every B2B and B2G invoice you issue is supposed to go through MyInvois.",
          "But there's a softer date most people miss. LHDN said penalty enforcement begins 1 January 2027 — RM 200 to RM 20,000 per non-compliant invoice. So technically you're inside the regime now, but the meter on penalties hasn't started ticking yet. You have roughly 7 months to clean up.",
        ],
      },
      {
        heading: "What to do in May 2026",
        paragraphs: [
          "Three things, in order of pain-reduction:",
        ],
        bullets: [
          "Register for MyInvois if you haven't. Even if your invoice volume is low, you need an active account before you can submit anything.",
          "Generate your LHDN signing certificate. It's a one-time setup and takes about 30 minutes inside MyTax.",
          "Pick one e-invoicing path: build it yourself (don't), wait for your accounting vendor (risky timing), or use a tool built for this (us, or one of our peers).",
        ],
      },
      {
        heading: "What you can defer to July",
        paragraphs: [
          "If your invoice volume is under ~10 per month, you can survive on the LHDN portal until July. It's clunky but it works. Use the May-June period to get certificates and accounts in place; switch to automation by July if your team's spending more than 4 hours a week on invoicing.",
        ],
      },
      {
        heading: "What you can stop worrying about",
        paragraphs: [
          "Consumer-facing invoices (B2C). If you sell to individuals, the LHDN placeholder TIN (EI00000000010) covers you. You don't need each buyer's TIN.",
          "Pre-2026 historical invoices. Phase 4 is forward-looking; you don't have to retroactively submit January's invoices.",
          "Self-billed invoices (mostly). If you're not in a self-billed industry (insurance, healthcare), this won't come up.",
        ],
      },
      {
        heading: "If you want help",
        paragraphs: [
          "Write to contact@symprio.com — we read every email. If you tell us your invoice volume and your accounting system, we can usually give you a yes/no on whether ZeroKey is the right fit in one reply.",
        ],
      },
    ],
  },

  {
    slug: "reading-myinvois-rejection-without-panicking",
    title: "Reading a MyInvois rejection without panicking",
    date: "Apr 2026",
    author: "Dushy",
    authorTitle: "Founder, Symprio",
    excerpt:
      "The five most common rejection codes and the one-line fix for each. Print this and pin it near your accountant.",
    readingMinutes: 4,
    sections: [
      {
        heading: "Rejections are routine. Treat them that way.",
        paragraphs: [
          "MyInvois rejects invoices for predictable reasons. Most rejections happen because a field is the wrong shape, not because anything is fundamentally wrong with the sale. Once you know the patterns, fixing a rejection is a 30-second job.",
        ],
      },
      {
        heading: "ERR202 — TIN format invalid",
        paragraphs: [
          "Your buyer's TIN doesn't match LHDN's format. Malaysian corporate TINs start with C and have 10–13 digits. Individuals start with IG.",
          "Fix: ask the buyer for the correct TIN. If they're an individual customer (B2C), use the placeholder EI00000000010.",
        ],
      },
      {
        heading: "ERR204 — TIN not registered",
        paragraphs: [
          "The TIN format is right, but LHDN doesn't recognise it. Usually a typo.",
          "Fix: double-check the TIN against the buyer's letterhead. ZeroKey can also do a lookup from the BRN if you have it.",
        ],
      },
      {
        heading: "ERR301 — MSIC code missing",
        paragraphs: [
          "Every line item needs an industry classification code. If the invoice has none, LHDN rejects.",
          "Fix: pick the MSIC code that matches the type of work you're invoicing for. ZeroKey suggests the right code based on the item description.",
        ],
      },
      {
        heading: "ERR405 — Totals don't match",
        paragraphs: [
          "The sum of line items doesn't match the invoice total, or the SST line doesn't add up. Usually a rounding issue from your accounting system.",
          "Fix: ZeroKey catches this before submission. If you've hit it, the invoice page shows which line is off by how much.",
        ],
      },
      {
        heading: "ERR501 — Outside cancellation window",
        paragraphs: [
          "You tried to cancel an invoice more than 72 hours after validation. LHDN won't allow it.",
          "Fix: you can't cancel. Issue a credit note instead. ZeroKey supports both in one click each.",
        ],
      },
    ],
  },

  {
    slug: "self-billed-invoices-three-calm-paragraphs",
    title: "Self-billed invoices, in three calm paragraphs",
    date: "Mar 2026",
    author: "Dushy",
    authorTitle: "Founder, Symprio",
    excerpt:
      "When you should use self-billed, when you really shouldn't, and how to switch a customer from one mode to the other without breaking history.",
    readingMinutes: 5,
    sections: [
      {
        heading: "What self-billed actually means",
        paragraphs: [
          "Normally, the supplier issues the invoice. ‘Self-billed’ flips that — the buyer issues the invoice on behalf of the supplier. LHDN allows this in a handful of industries where the buyer is the one that knows the price (insurance commissions, certain healthcare arrangements, foreign-supplier scenarios).",
          "Self-billed invoices have all the same validation rules as supplier-issued ones; only the role flag changes. From LHDN's perspective, what matters is that exactly one valid invoice exists per real-world transaction.",
        ],
      },
      {
        heading: "When you should use it",
        paragraphs: [
          "If your industry is on the LHDN self-billed allow-list and your buyers expect it. If the regulatory or operational reality means the buyer has the data and the supplier doesn't, self-billed is the right path.",
        ],
      },
      {
        heading: "When you really shouldn't",
        paragraphs: [
          "If your industry isn't on the allow-list. Don't try to make a non-self-billed transaction self-billed just because it's operationally easier. LHDN will reject and you'll create more work cleaning up. Stick to standard supplier-issued for anything outside the explicit allow-list.",
        ],
      },
      {
        heading: "Switching a customer between modes",
        paragraphs: [
          "If a customer needs to switch from supplier-issued to self-billed (or vice versa) mid-fiscal-year, the historical invoices stay as they are — you don't reissue. From the switch date forward, the new mode applies. ZeroKey lets you set the mode per customer, so the right rules apply automatically.",
        ],
      },
    ],
  },
];

export function findPost(slug: string): BlogPost | undefined {
  return BLOG_POSTS.find((p) => p.slug === slug);
}
