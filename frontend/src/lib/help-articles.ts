// LHDN + ZeroKey validation error decoder (Slice 93).
//
// Each entry maps a stable error ``code`` (the same string the backend
// puts on ``ValidationIssue.code``) to a plain-language explanation,
// what it means, why LHDN cares, and how to fix it. Help-center
// articles come from this map so the experience is consistent
// whether the user is staring at an inline issue pill (with a "?"
// link) or browsing /dashboard/help.
//
// Adding new codes:
// 1. Land the rule in ``backend/apps/validation/rules.py`` first.
// 2. Add an entry below using the SAME code string.
// 3. The unknown-code fallback covers anything missing — the issue
//    still renders the rule's message; we just don't have a long-form
//    article for it yet.

export type HelpArticle = {
  code: string;
  title: string;
  /** Plain-English summary the user should be able to act on
   *  without ever opening an LHDN PDF. */
  summary: string;
  /** Why LHDN (or our pre-flight) cares, in one sentence. */
  why: string;
  /** Concrete step-by-step fix. */
  howToFix: string[];
  /** Optional reference, e.g. "LHDN MyInvois SDK §3.4". Surface
   *  for users who DO want the source of truth. */
  reference?: string;
};

export const HELP_ARTICLES: Record<string, HelpArticle> = {
  // -- TIN format & identification -----------------------------------------
  "supplier.tin.format": {
    code: "supplier.tin.format",
    title: "Supplier TIN format is invalid",
    summary:
      "Your supplier (you) must be identified by a Malaysian TIN. The format is one letter followed by 10–13 digits.",
    why: "LHDN's HITS validator rejects any TIN that doesn't match a registered taxpayer. Wrong format = ERR206 even when the number is real.",
    howToFix: [
      "Find your TIN in the LHDN MyTax portal (mytax.hasil.gov.my).",
      "Corporate TINs start with C (e.g. C20880050010).",
      "Individual sole-trader TINs start with IG (e.g. IG12345678901).",
      "Government TINs start with G; non-profit start with N.",
      "Paste the value into the Supplier TIN field on the review screen and save.",
    ],
    reference: "LHDN e-Invoice Guideline §6.2 (Supplier identification)",
  },
  "buyer.tin.format": {
    code: "buyer.tin.format",
    title: "Buyer TIN format is invalid",
    summary:
      "The buyer on a B2B invoice must be identified by their Malaysian TIN. The format is one letter followed by 10–13 digits.",
    why: "LHDN matches buyer TIN against HITS to confirm the buyer is a real registered taxpayer. A B2C invoice should use the EI00000000010 placeholder TIN instead.",
    howToFix: [
      "Ask the buyer for their TIN — it's printed on their company stationery or available in their MyTax portal.",
      "Use C-prefix for corporate buyers, IG-prefix for individuals.",
      "For B2C (consumer) sales, use the LHDN-issued placeholder TIN: EI00000000010.",
      "Paste into the Buyer TIN field and save.",
    ],
    reference: "LHDN e-Invoice Guideline §6.3 (Buyer identification)",
  },
  "buyer.tin.missing": {
    code: "buyer.tin.missing",
    title: "Buyer TIN is required",
    summary: "Every LHDN invoice must identify the buyer with a TIN.",
    why: "LHDN treats the buyer TIN as the audit handle that links the invoice to the buyer's tax filing. No TIN = no submission.",
    howToFix: [
      "For business buyers, request their TIN.",
      "For consumer (B2C) sales, use the placeholder TIN EI00000000010.",
      "If you bill foreign customers, set Buyer Country to the right ISO code first — LHDN allows missing TIN only for non-Malaysian buyers.",
    ],
  },

  // -- Required-field rules ------------------------------------------------
  "required.line_items": {
    code: "required.line_items",
    title: "Invoice has no line items",
    summary: "An invoice must list at least one billable item.",
    why: "Empty invoices can't be submitted to LHDN — the system has nothing to compute tax on.",
    howToFix: [
      "Click 'Add line' below the line-items table.",
      "Fill in description, quantity, unit price, and tax rate.",
      "Save and the invoice will revalidate.",
    ],
  },

  // -- Date checks ---------------------------------------------------------
  "dates.due_in_past": {
    code: "dates.due_in_past",
    title: "Due date is in the past",
    summary: "Most invoices are issued with a future due date.",
    why: "A due date already past usually means a typo in the date field, or the invoice was issued for an already-paid bill. LHDN accepts past dates but it's worth confirming.",
    howToFix: [
      "Check the source document — is the due date what you intended?",
      "If the invoice is for an already-paid bill, this is fine; the warning is informational and won't block submission.",
      "Otherwise, edit the Due date field on the review screen.",
    ],
  },
  "dates.due_before_issue": {
    code: "dates.due_before_issue",
    title: "Due date is before issue date",
    summary: "The due date can't be earlier than when the invoice was issued.",
    why: "LHDN rejects invoices with logically impossible date ranges.",
    howToFix: [
      "Verify both dates against the source document.",
      "If the issue date was extracted incorrectly, edit it on the review screen.",
      "If 'due on receipt', set the due date equal to the issue date.",
    ],
  },
  "dates.issue_in_future": {
    code: "dates.issue_in_future",
    title: "Issue date is in the future",
    summary: "An invoice can't be issued for a date that hasn't happened yet.",
    why: "LHDN's submission window opens on the issue date — a future-dated invoice can't be submitted today.",
    howToFix: [
      "Confirm the issue date matches the source document.",
      "If you're scheduling a future invoice, wait until the issue date arrives before submitting.",
    ],
  },

  // -- Total reconciliation ------------------------------------------------
  "totals.subtotal.mismatch": {
    code: "totals.subtotal.mismatch",
    title: "Header subtotal doesn't match the line items",
    summary:
      "The subtotal on the invoice header should equal the sum of each line's subtotal (quantity × unit price).",
    why: "LHDN reconciles totals against line items. A mismatch means one number is wrong; we can't tell you which without your input.",
    howToFix: [
      "Open the line items table. Sum the per-line subtotals.",
      "Compare to the Header → Subtotal field.",
      "Edit whichever is wrong. The most common cause is a missing line item or a miss-keyed quantity.",
    ],
  },
  "totals.tax.mismatch": {
    code: "totals.tax.mismatch",
    title: "Header total tax doesn't match the per-line tax amounts",
    summary:
      "The total-tax field should equal the sum of each line's tax_amount.",
    why: "Same reconciliation as subtotal — LHDN compares the two and rejects mismatches.",
    howToFix: [
      "Check that each line has a tax_amount filled in (we auto-derive it from rate × subtotal when blank).",
      "If the header value differs, edit it on the review screen.",
      "Common cause: SST exemption on one line not reflected in the header total.",
    ],
  },
  "totals.grand_total.mismatch": {
    code: "totals.grand_total.mismatch",
    title: "Grand total doesn't reconcile",
    summary: "Grand total should equal subtotal + tax − discount.",
    why: "LHDN computes the expected grand total from the components and rejects deviations beyond the 1 MYR rounding tolerance.",
    howToFix: [
      "Verify subtotal, total tax, and discount are all correct.",
      "If one of them is fixed by a separate edit, the grand total will reconcile automatically.",
      "If you hand-type the grand total, make sure it matches the math.",
    ],
  },
  "line.subtotal.mismatch": {
    code: "line.subtotal.mismatch",
    title: "Line subtotal doesn't match quantity × unit price",
    summary:
      "Each line's subtotal_excl_tax should equal quantity × unit_price_excl_tax.",
    why: "Lines whose math doesn't reconcile typically indicate a typo in one of the three columns. LHDN treats these as a hard error.",
    howToFix: [
      "Re-do the math for the flagged line.",
      "Edit whichever value is wrong (most often the subtotal column was miscopied).",
    ],
  },
  "line.total.mismatch": {
    code: "line.total.mismatch",
    title: "Line total doesn't match subtotal + tax",
    summary:
      "Each line's total_incl_tax should equal subtotal_excl_tax + tax_amount.",
    why: "Same as line subtotal — LHDN expects the math to work.",
    howToFix: [
      "Check the line's subtotal, tax_amount, and line_total.",
      "If tax_amount was blank, the system derives it from rate × subtotal — review the auto-derived value.",
    ],
  },

  // -- Currency / classification -------------------------------------------
  "currency.format": {
    code: "currency.format",
    title: "Currency code is malformed",
    summary: "Currency must be a 3-letter ISO 4217 code (e.g. MYR, USD, SGD).",
    why: "LHDN won't accept non-ISO currency codes.",
    howToFix: [
      "Set the currency to MYR for ringgit invoices.",
      "For foreign currency, use the ISO code (USD, EUR, SGD, etc.).",
      "Capital letters only.",
    ],
  },
  "currency.unsupported": {
    code: "currency.unsupported",
    title: "Currency code isn't in the LHDN catalog",
    summary:
      "ZeroKey caches LHDN's currency catalog; this code isn't on the list.",
    why: "LHDN maintains a fixed list of accepted ISO codes for MyInvois submission.",
    howToFix: [
      "Switch to a supported code (MYR, USD, EUR, SGD, etc.).",
      "If you genuinely need a code we haven't seen, contact support — we may need to refresh the catalog.",
    ],
  },
  "line.classification.unknown": {
    code: "line.classification.unknown",
    title: "Line classification code isn't recognised",
    summary:
      "The LHDN classification code on this line isn't in the published catalog.",
    why: "LHDN rejects classification codes outside the 022 set.",
    howToFix: [
      "Open the line and pick a code from the dropdown (we suggest the closest match).",
      "If you don't know which code to use, leave it blank — the validator will tell you which categories are required.",
    ],
  },
  "line.tax_type.unknown": {
    code: "line.tax_type.unknown",
    title: "Tax type code isn't recognised",
    summary: "The tax_type_code on this line isn't in LHDN's tax type catalog.",
    why: "LHDN's tax types are fixed (01 = SST, E = exempt, etc.).",
    howToFix: [
      "Use 01 for SST.",
      "Use E for exempt items.",
      "Leave blank if no tax applies.",
    ],
  },
  "line.uom.unknown": {
    code: "line.uom.unknown",
    title: "Unit of measurement isn't a valid UN/ECE code",
    summary: "LHDN expects UN/ECE Recommendation 20 codes (e.g. EA, KGM, HUR).",
    why: "These are the international standard for trade documents.",
    howToFix: [
      "EA (each) for countable items.",
      "KGM for kilograms, HUR for hours, MTR for metres.",
      "If unsure, leave blank and a default will be applied.",
    ],
    reference: "UN/ECE Rec 20 — Codes for units of measure used in international trade",
  },

  // -- Special cases -------------------------------------------------------
  "invoice_type.self_billed_suggested": {
    code: "invoice_type.self_billed_suggested",
    title: "This looks like a self-billed invoice",
    summary:
      "The supplier has no Malaysian TIN — usually means the buyer (you) is paying a foreign or unregistered supplier and needs to issue the invoice on their behalf.",
    why: "LHDN treats self-billed invoices differently — they use doc types 11–14 instead of 01–04. Submitting a foreign-supplier transaction as a regular invoice (type 01) misrepresents who's responsible for the tax filing.",
    howToFix: [
      "If the supplier really is foreign / unregistered → change the Invoice type to the matching Self-Billed variant (Invoice → Self-Billed Invoice; Credit Note → Self-Billed Credit Note; etc.).",
      "If the supplier IS Malaysian and you just don't have their TIN yet → ask them for it. LHDN won't accept the submission without one.",
      "If the supplier is government / exempt → you may need a different doc-type. Check LHDN's e-Invoice Guideline §5.",
    ],
    reference: "LHDN e-Invoice Guideline §5 (Document types)",
  },
  "invoice_number.duplicate": {
    code: "invoice_number.duplicate",
    title: "Invoice number already exists",
    summary:
      "You've already issued an invoice with this number to this buyer. LHDN doesn't allow duplicates.",
    why: "Duplicate invoice numbers can't be reconciled — LHDN's audit chain depends on uniqueness.",
    howToFix: [
      "Bump the suffix (e.g. INV-001 → INV-001-A) for the new invoice.",
      "If this is a correction to a previous submission, issue a Credit Note or Debit Note instead.",
    ],
  },
  "sst.no_tax_on_registered_supplier": {
    code: "sst.no_tax_on_registered_supplier",
    title: "SST-registered supplier with zero tax",
    summary:
      "Your SST registration number is on the invoice but every line has zero tax.",
    why: "If you're SST-registered, LHDN expects tax on taxable items. Zero across the board may indicate a missing tax-rate setup.",
    howToFix: [
      "Check that each line's tax_rate is set correctly (typically 6% for taxable goods/services).",
      "If the goods are exempt, set tax_type_code = E on each line.",
      "If you're not actually SST-registered, clear the supplier_sst_number field.",
    ],
  },
  "buyer.country.format": {
    code: "buyer.country.format",
    title: "Buyer country code is malformed",
    summary: "Country must be a 2-letter ISO 3166-1 code (e.g. MY, SG, US).",
    why: "LHDN uses ISO country codes to determine which invoice rules apply.",
    howToFix: [
      "MY for Malaysia, SG for Singapore, etc.",
      "Capital letters only.",
    ],
  },
  "buyer.country.unknown": {
    code: "buyer.country.unknown",
    title: "Buyer country code isn't recognised",
    summary: "The 2-letter code you provided isn't in LHDN's country catalog.",
    why: "LHDN keeps a fixed catalog of accepted ISO codes.",
    howToFix: [
      "Pick from the standard ISO 3166-1 alpha-2 list.",
      "If you've used the right code but the validator rejects it, contact support — the catalog may need a refresh.",
    ],
  },
  "currency.precision": {
    code: "currency.precision",
    title: "Decimal precision exceeds 2 places",
    summary: "Monetary fields can have at most 2 decimal places.",
    why: "MYR is a 2-decimal currency. LHDN treats higher precision as an input error.",
    howToFix: [
      "Round to 2 decimal places (e.g. 1234.567 → 1234.57).",
      "If the source document has higher precision, that's a vendor formatting issue — round and proceed.",
    ],
  },
};

export function getHelpArticle(code: string): HelpArticle | null {
  return HELP_ARTICLES[code] ?? null;
}

export function listHelpArticles(): HelpArticle[] {
  return Object.values(HELP_ARTICLES).sort((a, b) => a.title.localeCompare(b.title));
}
