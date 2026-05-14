// Marketing help-center articles. Plain customer-facing content — the
// validation error decoder at lib/help-articles.ts is a separate concern.
//
// Articles are grouped by topic for the index page, and individually
// addressable at /help/<slug>. Topic ordering is editorial.

export type HelpTopicId =
  | "getting-started"
  | "invoices"
  | "connectors"
  | "team"
  | "billing"
  | "settings";

export type HelpArticleMeta = {
  slug: string;
  title: string;
  topic: HelpTopicId;
  /** One-sentence summary for the index card. */
  summary: string;
  /** Estimated read time in minutes. */
  readingMinutes: number;
};

export type HelpArticle = HelpArticleMeta & {
  /** Long-form body as ordered sections. Each section gets an <h2>. */
  sections: { heading: string; paragraphs: string[]; bullets?: string[] }[];
  /** Optional "see also" slugs surfaced at the bottom. */
  seeAlso?: string[];
};

export const HELP_TOPICS: Record<HelpTopicId, { title: string }> = {
  "getting-started": { title: "Getting started" },
  invoices: { title: "Working with invoices" },
  connectors: { title: "Connectors" },
  team: { title: "Team & permissions" },
  billing: { title: "Billing" },
  settings: { title: "Settings & account" },
};

// All articles are inlined here. v1 is small; the structure scales by
// adding entries below — each one is automatically routable and
// searchable.
export const HELP_ARTICLES: HelpArticle[] = [
  {
    slug: "create-your-account",
    title: "Create your account and your first organisation",
    topic: "getting-started",
    summary:
      "Sign up, set up your organisation profile, and invite your first teammate.",
    readingMinutes: 3,
    sections: [
      {
        heading: "Before you start",
        paragraphs: [
          "ZeroKey is a multi-tenant product — every account belongs to one or more organisations (we sometimes call these tenants). When you first sign up, ZeroKey creates an organisation for you automatically. You can add more later if you operate multiple businesses.",
        ],
      },
      {
        heading: "Sign up",
        paragraphs: [
          "Visit /sign-up and enter your work email. We send a one-time link to confirm the address. After confirmation you set your password and you're in.",
          "You don't need a credit card. The free trial gives you 20 invoices and 14 days — plenty to see whether ZeroKey fits.",
        ],
      },
      {
        heading: "Set up your organisation",
        paragraphs: [
          "From the dashboard, open Settings → Organisation. Fill in:",
        ],
        bullets: [
          "Registered business name (matches your SSM record)",
          "Business registration number (BRN)",
          "LHDN TIN — we can look this up from your BRN automatically",
          "Registered address and contact details",
        ],
      },
      {
        heading: "Invite a teammate",
        paragraphs: [
          "Settings → Members → Invite. Pick a role (admin, reviewer, accountant) and we send them an email. They get access as soon as they accept.",
        ],
      },
    ],
    seeAlso: ["upload-your-lhdn-certificate", "send-your-first-invoice"],
  },

  {
    slug: "upload-your-lhdn-certificate",
    title: "Upload your LHDN certificate",
    topic: "getting-started",
    summary:
      "How to register with LHDN, generate your signing certificate, and load it into ZeroKey.",
    readingMinutes: 5,
    sections: [
      {
        heading: "What is the LHDN certificate?",
        paragraphs: [
          "Every invoice submitted to MyInvois must be digitally signed by the taxpayer. LHDN issues each registered business a signing certificate that proves it was you. ZeroKey uses your certificate to sign your invoices on your behalf — we never store the plain key.",
        ],
      },
      {
        heading: "If you haven't registered with LHDN yet",
        paragraphs: [
          "You need an active MyTax account first (mytax.hasil.gov.my). From there, request access to MyInvois. Approval typically takes 1–3 business days. We can guide you through this during onboarding — write to contact@symprio.com.",
        ],
      },
      {
        heading: "Generate the certificate",
        paragraphs: [
          "Inside MyInvois, navigate to Profile → Digital Certificate. Generate a new certificate and download the .p12 (or .pfx) file. You'll also set a passphrase — keep this somewhere safe; you need it once during upload.",
        ],
      },
      {
        heading: "Upload to ZeroKey",
        paragraphs: [
          "In ZeroKey, open Settings → Compliance → LHDN certificate. Click Upload, choose your .p12 file, and enter the passphrase. ZeroKey encrypts the certificate immediately and stores it sealed — even our staff cannot read it.",
          "Once uploaded, the Status pill shows ‘Valid until …’ with the certificate's expiry date. We email you 30 days before expiry so you can rotate without scrambling.",
        ],
      },
    ],
    seeAlso: ["create-your-account", "send-your-first-invoice"],
  },

  {
    slug: "send-your-first-invoice",
    title: "Send your first invoice end-to-end",
    topic: "getting-started",
    summary: "Drop a PDF, review what we extracted, approve, and watch the LHDN UUID come back.",
    readingMinutes: 4,
    sections: [
      {
        heading: "Drop the file",
        paragraphs: [
          "From the dashboard, click ‘Drop an invoice’ or drag a file onto the page. PDFs, images, and Excel spreadsheets all work. We start processing immediately.",
        ],
      },
      {
        heading: "Review what we extracted",
        paragraphs: [
          "Within seconds, you'll see the parsed invoice next to the original. Fields with high confidence are shown calmly; low-confidence ones are highlighted for your attention. Every field is editable — click to fix anything.",
        ],
      },
      {
        heading: "Approve",
        paragraphs: [
          "When everything looks right, click ‘Approve & submit’. ZeroKey signs the invoice with your certificate and sends it to LHDN.",
        ],
      },
      {
        heading: "Confirmation",
        paragraphs: [
          "Within 10 seconds, the invoice page updates with the LHDN UUID, the validated status, and the QR code that goes on the buyer-facing PDF. You can download the validated PDF, email it to the buyer, or hand off to your accounting system.",
        ],
      },
    ],
    seeAlso: ["cancel-an-invoice", "what-validated-really-means"],
  },

  {
    slug: "what-validated-really-means",
    title: "What ‘Validated’ really means",
    topic: "invoices",
    summary:
      "Validated is LHDN's acceptance status — and there are a few states it can transition into. Here's the map.",
    readingMinutes: 3,
    sections: [
      {
        heading: "Validated",
        paragraphs: [
          "Your invoice has been signed by you, accepted by LHDN, and assigned a UUID. The buyer can verify it independently from MyInvois. This is the happy path.",
        ],
      },
      {
        heading: "Cancelled (within 72 hours)",
        paragraphs: [
          "LHDN allows you to cancel a validated invoice within 72 hours of validation. After that window, you cannot cancel — you can only issue a credit note. ZeroKey lets you cancel from the invoice page with one click.",
        ],
      },
      {
        heading: "Rejected by buyer",
        paragraphs: [
          "Your buyer can reject an invoice within the 72-hour window. The invoice transitions to ‘rejected’ and is no longer a valid e-invoice. Issue a credit note or correct the invoice and resubmit.",
        ],
      },
      {
        heading: "Failed validation",
        paragraphs: [
          "If LHDN rejects the submission, ZeroKey shows the validation error in plain English and links to a fix. Common causes: wrong TIN format, missing MSIC code, totals that don't add up.",
        ],
      },
    ],
  },

  {
    slug: "cancel-an-invoice",
    title: "Cancel an invoice within the 72-hour window",
    topic: "invoices",
    summary:
      "How and when to cancel a validated invoice — and what to do after the window closes.",
    readingMinutes: 2,
    sections: [
      {
        heading: "When you can cancel",
        paragraphs: [
          "LHDN allows cancellation within 72 hours of validation. The clock starts the moment LHDN returns a Validated status, not when you click Approve.",
        ],
      },
      {
        heading: "How to cancel",
        paragraphs: [
          "Open the invoice page and click ‘Cancel invoice’. You'll be asked for a brief reason — LHDN requires this. ZeroKey submits the cancellation request, and the invoice transitions to Cancelled within seconds.",
        ],
      },
      {
        heading: "After the 72-hour window",
        paragraphs: [
          "You can't cancel. You can either issue a credit note for the difference, or — if the entire invoice is wrong — issue a refund credit note and reissue a new one. Both are routine operations and ZeroKey supports both directly.",
        ],
      },
    ],
  },

  {
    slug: "connect-sql-account",
    title: "Connect SQL Account",
    topic: "connectors",
    summary:
      "How to wire SQL Account into ZeroKey so customer master and invoice history stay in step.",
    readingMinutes: 4,
    sections: [
      {
        heading: "What gets synced",
        paragraphs: [
          "ZeroKey can two-way sync with SQL Account: customer master (read/write), item catalog (read/write), invoice posting (write into SQL), and submission status (write back into ZeroKey).",
        ],
      },
      {
        heading: "Set up the connection",
        paragraphs: [
          "In ZeroKey, open Connectors → Add new → SQL Account. You'll be asked for your SQL Account server address (or local network path), the company file name, and a service-account username and password that has read+write on the relevant modules. We test the connection immediately and report any issues.",
        ],
      },
      {
        heading: "Initial sync",
        paragraphs: [
          "On first connection, ZeroKey pulls your customer and item lists and creates a mapping table. You can review and adjust mappings before they go live. Future syncs run on a schedule (every 15 minutes by default) or on-demand.",
        ],
      },
      {
        heading: "Resolving conflicts",
        paragraphs: [
          "If the same customer is edited in both systems before a sync, ZeroKey flags the conflict in Connectors → Conflicts. You pick which side wins. The other side updates automatically and the conflict closes.",
        ],
      },
    ],
  },

  {
    slug: "team-roles-explained",
    title: "Roles explained",
    topic: "team",
    summary: "What each role can and cannot do, and how to map your team's responsibilities to roles.",
    readingMinutes: 3,
    sections: [
      {
        heading: "The four roles",
        paragraphs: ["ZeroKey ships with four built-in roles."],
        bullets: [
          "Admin — full access to all settings, billing, members, and the LHDN certificate. The role that signed up first.",
          "Reviewer — can upload, review, edit, and approve invoices. Cannot change billing or members.",
          "Accountant — read access plus the ability to download audit bundles and export data. Cannot edit invoices.",
          "Read-only — view-only access to dashboards and invoices.",
        ],
      },
      {
        heading: "Approval flows",
        paragraphs: [
          "Admins can enable an approval flow that requires two-step approval for invoices above a threshold. The reviewer who created the invoice cannot also approve it — segregation of duties enforced automatically.",
        ],
      },
      {
        heading: "Custom roles",
        paragraphs: [
          "Available on the Scale and Pro plans. Create your own roles with fine-grained permissions per surface area. Write to contact@symprio.com if you need help mapping a custom workflow.",
        ],
      },
    ],
  },

  {
    slug: "export-your-data",
    title: "Export your data",
    topic: "settings",
    summary: "How to export your invoices, customer master, and audit log — at any time.",
    readingMinutes: 2,
    sections: [
      {
        heading: "What's exportable",
        paragraphs: [
          "Everything we store about you is exportable. Invoice data (CSV or JSON), customer master (CSV), item catalog (CSV), audit log (signed JSON bundle), original uploaded files (ZIP of the originals), and LHDN-validated PDFs (ZIP).",
        ],
      },
      {
        heading: "How to export",
        paragraphs: [
          "Settings → Data → Export. Pick what you want, the date range, and the format. ZeroKey assembles the bundle and emails you a download link when ready — usually within a minute, longer for large exports.",
        ],
      },
      {
        heading: "Privacy and retention",
        paragraphs: [
          "Exports are encrypted and the download link expires after 7 days. After cancellation, we retain your data for the period required by Malaysian tax law (currently 7 years for invoice records) and then delete it. You can export everything we hold before that point.",
        ],
      },
    ],
  },
];

export function findArticle(slug: string): HelpArticle | undefined {
  return HELP_ARTICLES.find((a) => a.slug === slug);
}

export function articlesByTopic(topic: HelpTopicId): HelpArticleMeta[] {
  return HELP_ARTICLES.filter((a) => a.topic === topic);
}
