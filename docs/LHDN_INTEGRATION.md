# LHDN INTEGRATION — ZeroKey

> The complete specification of how ZeroKey interacts with the Inland Revenue Board of Malaysia's MyInvois platform. This document is the source of truth for every regulatory decision the system makes. When LHDN updates its specification — and they will — this document is updated first, then the implementation, never the other way around.

## Why this document exists

The MyInvois integration is the one part of ZeroKey where we have zero design freedom. LHDN defines the rules. We implement them. Misimplementing them does not result in degraded user experience; it results in penalties for our customers and ultimately liability for ZeroKey. This document captures every aspect of that integration in operational detail so that anyone working on the codebase — human or AI — can reason about MyInvois behavior without having to chase fragmented official documentation.

It is also the document that protects us from drift. LHDN publishes updates regularly. If we do not have a single canonical record of what we are integrating against, we will end up with extraction logic targeting the 2024 spec, validation logic targeting the 2025 spec, and submission logic targeting the 2026 spec. This document prevents that.

When LHDN issues a new specification version, the engineering process is: read the changelog, update this document with the diff, update the implementation, update the test suite, deploy. In that order. The document leads the code.

## What MyInvois actually is

MyInvois is the Inland Revenue Board of Malaysia's centralized e-invoicing platform. Every taxable business invoice transacted in Malaysia must be submitted to MyInvois for real-time validation before it can be issued to the buyer as a final invoice. The validated invoice receives a unique identifier and a QR code, both of which must appear on the invoice document the seller delivers to the buyer.

The platform serves three distinct functions simultaneously. First, it is a real-time validation gateway: every invoice is checked against tax rules, format conventions, and reference data before it is accepted. Second, it is a centralized record store: LHDN retains every validated invoice indefinitely as the authoritative version. Third, it is an audit and analytics platform: LHDN uses the structured invoice data for tax compliance monitoring and revenue analysis.

For ZeroKey, MyInvois is the destination. Everything our pipeline does — ingestion, extraction, enrichment, validation — exists to produce a valid submission that MyInvois accepts on the first try. Our success metric is first-submission validation rate, not invoice volume.

## The phases and the timeline that matter

LHDN rolls out the e-invoicing mandate in phases keyed to business revenue thresholds. As of April 2026, the relevant phases for ZeroKey customers are Phase 3 (RM 5 million to RM 25 million annual revenue, mandatory since July 2025) and Phase 4 (RM 1 million to RM 5 million, mandatory since January 2026). Businesses below RM 1 million in annual revenue are exempt as of the most recent policy update, removing what was originally going to be Phase 5.

The penalty regime is the operational reality our customers care about most. Phase 4 entered a relaxation period from January 2026 through December 2026 during which validation failures and submission delays do not trigger penalties. From January 1, 2027, full penalty enforcement begins: RM 200 to RM 20,000 per non-compliant invoice, applied per occurrence. The transactions-over-RM-10,000 rule has been fully enforced from day one with no relaxation.

ZeroKey is built to keep our customers below the penalty threshold. Our entire validation, retry, and exception-handling architecture exists in service of that goal.

## The submission shape

Every e-invoice submitted to MyInvois follows a structured format conforming to the OASIS Universal Business Language (UBL) version 2.1 specification, with Malaysia-specific extensions defined in LHDN's published implementation guidelines. The submission is either an XML document or a JSON document; LHDN accepts both formats and treats them as semantically equivalent. ZeroKey emits XML for production submissions because XML is the historical UBL native format and has slightly more reliable LHDN tooling support.

A complete submission includes the invoice document itself, the digital signature applied by the seller's certificate, and the API call envelope that authenticates ZeroKey to MyInvois on the customer's behalf. The signed invoice cannot be modified after signing without invalidating the signature; this means our pre-flight validation must be complete before signing, and any user correction must trigger re-signing on the new payload.

## The fifty-five mandatory data fields

LHDN's specification defines a substantial set of mandatory fields organized into logical groups. The total count varies depending on whether self-billing, consolidated invoicing, or foreign supplier scenarios apply, but for the standard B2B invoice the core mandatory field count is fifty-five. ZeroKey's extraction pipeline targets all of them. This section documents each group and the operational considerations for each.

### Supplier identification fields

The supplier identification block identifies the entity issuing the invoice. The mandatory fields here include the supplier's legal name as registered with SSM (the Companies Commission of Malaysia), the supplier's Tax Identification Number (TIN) as issued by LHDN, the supplier's business registration number from SSM, the supplier's MSIC code (the primary industry classification of the supplier's business), the supplier's full registered business address with postal code, the supplier's contact telephone number, and the supplier's SST registration number if the supplier is registered for Sales and Service Tax.

Operationally, the supplier identification block is filled once during onboarding and rarely changes. ZeroKey stores the validated supplier identification on the customer's organization record and applies it to every outgoing invoice automatically. The supplier's TIN is verified against LHDN's verification endpoint at onboarding time and re-verified periodically (default every ninety days) to detect any changes.

### Buyer identification fields

The buyer identification block identifies the entity receiving the invoice. The mandatory fields include the buyer's legal name, the buyer's TIN, the buyer's business registration number, the buyer's MSIC code (the buyer's primary industry classification, which can differ from the supplier's), the buyer's full registered business address with postal code, the buyer's contact telephone number, and the buyer's SST registration number if applicable.

For consumer (B2C) invoices where no buyer TIN exists, LHDN provides specific placeholder values that ZeroKey applies automatically. For foreign buyers, country-specific identifiers replace the Malaysian TIN. The buyer identification is the field set most likely to require enrichment from external sources during extraction; the customer master accumulates verified buyer records over time, dramatically improving auto-fill accuracy.

### Invoice header fields

The invoice header block describes the invoice itself as a document. Mandatory fields include the invoice number assigned by the supplier (must be unique within the supplier's invoice sequence), the invoice issue date, the invoice currency code (in ISO 4217 format), the invoice type code (which distinguishes among standard invoice, credit note, debit note, refund note, and self-billed variants), and the original invoice reference number for credit and debit notes that adjust a prior invoice.

The invoice number is sensitive territory. LHDN expects strict uniqueness within a supplier's sequence. ZeroKey's job is to detect duplicates within our customer's namespace and warn before submission. We never auto-renumber an invoice, since that would conflict with the customer's accounting system records.

### Line item fields

Each line item in the invoice carries its own mandatory field set. For each line item, the mandatory fields include the line item number (a sequential integer within the invoice), the item description, the unit of measurement (using LHDN-published UOM codes), the quantity, the unit price excluding tax, the line item subtotal excluding tax, the tax type and rate applied, the tax amount on this line, the line item total including tax, the classification code identifying the type of supply (LHDN-published classification codes, distinct from MSIC), and where applicable, a discount or charge amount with its reason.

The line item field set is the most variable across customers. A trading business has line items with concrete physical product descriptions. A professional services firm has line items with task descriptions. A construction subcontractor has line items with project milestones. ZeroKey's extraction pipeline must handle all of these, and the item master accumulates per-customer recurring patterns to accelerate future extractions.

### Tax and total fields

The tax and totals block summarizes the financial figures of the invoice. Mandatory fields include the invoice subtotal (sum of all line items excluding tax), the total tax amount (sum of tax across all line items), the invoice grand total (subtotal plus tax), any discount or charge applied at the invoice level with a reason code, and the payable amount in the supplier's currency.

For multi-currency invoices, the equivalent MYR amount is also mandatory, calculated using the Bank Negara Malaysia daily exchange rate for the invoice issue date. ZeroKey fetches this rate automatically and includes both the original currency amounts and the MYR equivalents.

The arithmetic of the tax and totals block must be internally consistent: the sum of line items must equal the subtotal, the tax must equal the calculated tax based on rates, and the grand total must equal the subtotal plus tax minus any invoice-level discount. ZeroKey's pre-flight validation enforces this consistency to a tolerance of one cent per line and one ringgit per invoice; differences within tolerance are corrected automatically (rounding adjustments distributed to the largest line item), differences outside tolerance are surfaced for human review.

### Payment and reference fields

The payment block describes how the invoice is paid. Mandatory fields include the payment terms code, the due date, and a reference number for matching payments back to the invoice in the supplier's accounting system. The reference number is opaque to LHDN and exists for the supplier's own reconciliation.

### Special-case fields

Several fields are mandatory only when specific scenarios apply. Self-billed invoices require an additional self-billed indicator and the original supplier's identification (since in a self-billed scenario the buyer issues the invoice on the supplier's behalf). Consolidated B2C invoices require a consolidation period indicator and the count of underlying transactions consolidated. Foreign supplier invoices require the supplier's country code, the supplier's foreign tax identification, and an indication of whether the invoice is subject to imported services tax.

ZeroKey detects these scenarios automatically based on the input data — a foreign country code on the supplier's address, the absence of a Malaysian TIN, certain transaction patterns — and applies the appropriate field treatment. The detection logic is conservative: when in doubt, we surface a question to the user rather than silently apply a special treatment.

## Field validation rules

LHDN's published validation rules define what makes a submitted field valid. ZeroKey's pre-flight validation enforces these rules locally before submission, dramatically reducing rejection rates.

The TIN format follows specific patterns based on the entity type: individual taxpayers use a thirteen-character format starting with a letter prefix; corporate entities use a different alphanumeric format. ZeroKey validates TINs syntactically before live verification against LHDN's API. Syntactic failures are caught immediately; semantic failures (the TIN is well-formed but does not exist) are caught by the live verification.

Date fields must conform to ISO 8601 format with explicit timezone information. ZeroKey emits dates in Malaysia Standard Time (UTC+8) explicitly to avoid any ambiguity.

Currency codes must be valid ISO 4217 three-letter codes. Currency amounts must be expressed with the appropriate decimal precision for the currency (two decimals for MYR, USD, SGD; zero decimals for JPY, KRW; etc.).

MSIC codes must match valid five-digit codes from the published MSIC catalog. ZeroKey caches the MSIC catalog locally and refreshes it monthly. Invalid or deprecated codes are caught immediately.

Classification codes must match valid codes from LHDN's published classification list. ZeroKey caches this catalog as well.

Tax type codes and tax rates must be consistent with each other. SST registered suppliers apply specific tax types; non-registered suppliers apply different types. Exempt and zero-rated supplies have their own type codes. ZeroKey looks up the correct tax type based on the supplier's registration status and the line item's classification.

UOM codes must be from LHDN's published unit-of-measure list. ZeroKey infers UOM from the line item description and pattern-matches against the catalog, surfacing low-confidence matches for review.

## The transaction-over-RM-10,000 rule

LHDN treats individual transactions exceeding RM 10,000 with special seriousness. These transactions cannot be consolidated into a B2C summary invoice; they must be submitted as standalone invoices with full buyer identification, even if the buyer is a consumer who does not normally have a TIN. The penalty for misclassifying a transaction as part of a consolidated invoice when it should be standalone is one of the categories with no relaxation period — it has been enforced from day one of the mandate.

ZeroKey's logic enforces this rule at multiple layers. During extraction, any line item or invoice total approaching or exceeding RM 10,000 triggers a flag. During the consolidation flow (for retail customers using consolidated B2C invoicing), the system refuses to include qualifying transactions in the consolidation and instead routes them to the standalone path. The user sees a clear explanation of why a particular transaction cannot be consolidated.

## The foreign supplier scenario

When a Malaysian business receives an invoice from a foreign (non-Malaysian) supplier, the standard supplier-issued e-invoice flow does not apply because the foreign supplier is not registered with LHDN and does not have access to MyInvois. Malaysian tax law requires the Malaysian buyer to issue a self-billed e-invoice on the foreign supplier's behalf, declaring the imported goods or services and applying any applicable imported services tax.

ZeroKey detects this scenario by examining the supplier identification on the input invoice: foreign country code on the supplier's address, missing Malaysian TIN, presence of a foreign tax identifier. When detected, the system prompts the user to confirm self-billed treatment and switches to the self-billed invoice flow. The customer's own identification becomes the issuer; the foreign entity becomes the original supplier referenced in the self-billed extension fields.

## The consolidated B2C invoice scenario

For retail businesses issuing many small consumer transactions, LHDN allows consolidation into a single end-of-day invoice rather than requiring per-transaction submission. Consolidation has three constraints: each individual transaction must be below the RM 10,000 threshold, the consolidation must occur within the same business day, and the underlying transaction detail must be retained by the supplier for audit even though only the consolidated total is submitted.

ZeroKey's consolidation flow accepts a batch of B2C transactions, validates each one against the threshold, builds the consolidated invoice payload with the underlying transaction count and period, and retains the per-transaction detail in the customer's archive linked to the consolidated invoice's UUID for future audit reference.

## The credit note and debit note flow

When a previously-validated invoice needs to be adjusted — a return, a price correction, a discount applied after issue — LHDN does not allow the original invoice to be modified. Instead, the supplier issues a credit note (for amounts to be refunded or reduced) or a debit note (for amounts to be added) that references the original invoice's UUID. The credit or debit note is itself an e-invoice that goes through the same submission and validation flow.

ZeroKey's credit and debit note flow is initiated from the original validated invoice in the dashboard. The user clicks "Issue credit note" or "Issue debit note" and is presented with a pre-populated form that references the original invoice's UUID, copies the buyer identification, and asks the user to specify the line items and amounts to adjust. The submitted credit or debit note flows through the same pipeline as a standard invoice.

## The cancellation flow

LHDN allows cancellation of a validated invoice within seventy-two hours of validation. Beyond seventy-two hours, the invoice cannot be cancelled and any adjustment must be made via credit note. ZeroKey surfaces the cancellation option clearly on validated invoices that are still within the seventy-two-hour window. The dashboard shows a countdown for invoices approaching the cancellation deadline.

The cancellation API call submits a cancellation request to MyInvois with the invoice's UUID and a reason code. MyInvois processes the cancellation, which is itself an event that updates the invoice's state from Validated to Cancelled in their system. The original UUID and QR code remain in our archive but are marked as cancelled.

## Authentication and API access

Submission to MyInvois requires authenticated API access. The authentication is two-tiered: ZeroKey itself authenticates as a software intermediary using LHDN-issued client credentials, and within each authenticated session, the specific customer on whose behalf the submission is made is identified through the customer's TIN.

The customer's digital certificate is what makes the submission legally binding. The certificate is issued to the customer by LHDN as part of their MyInvois registration. ZeroKey collects the certificate from the customer at onboarding, stores the encrypted blob in object storage with KMS-backed envelope encryption, and uses the certificate transiently inside an isolated signing service for each submission. The certificate is never exposed to the application database or to any service outside the signing path.

The complete cryptographic and key-management architecture is detailed in `SECURITY.md`. The principle is: ZeroKey holds the certificate as a custodian, not as an owner. The customer can revoke and replace the certificate at any time. ZeroKey can never decrypt or use the certificate without the active runtime context of the signing service.

## Rate limits and submission throttling

LHDN's MyInvois API enforces rate limits on submission and verification calls. The exact limits are subject to LHDN's published policies but as of April 2026 are approximately one hundred submissions per minute per intermediary, with separate limits for verification and lookup calls. ZeroKey aggregates submissions across all customers and respects these limits by queuing submissions when necessary and prioritizing by customer plan tier.

The customer never sees the rate limit directly. From their perspective, an invoice submits within seconds of approval. Internally, the submission queue may delay submission by up to a few minutes during peak periods to stay below the LHDN rate limit. The queue is visible in the operations dashboard and is monitored for backlog growth.

## Status polling and notification

After a successful submission, MyInvois performs validation asynchronously. Validation typically completes in seconds but can take up to several minutes during peak periods or for complex invoices. ZeroKey polls MyInvois for validation status with an exponential backoff schedule starting at one second and increasing to a maximum of thirty seconds between polls.

Final validation states are Validated, Rejected, and Cancelled. Each state triggers appropriate user-facing notifications via the customer's configured channels (in-app, email, optionally WhatsApp on Growth and above). The polling continues until a final state is reached or until a timeout (default fifteen minutes) is exceeded, at which point the invoice moves to a Stuck state requiring operator intervention.

## Handling LHDN platform outages

MyInvois is a government-operated platform and like all such platforms occasionally experiences outages or degraded service. ZeroKey's customer-facing posture during these events is calm and informative. We display a clear in-product banner stating that MyInvois is currently unavailable, explain that submissions are queued and will be sent automatically when service returns, and email customers when the outage is resolved. Customers are not asked to retry manually.

Internally, the submission queue continues to accept new submissions during the outage; they accumulate in a paused state. When MyInvois service returns, the queue drains in priority order with appropriate rate limit respect. Customers see their accumulated submissions process within minutes of service restoration.

The status of MyInvois itself is monitored continuously by ZeroKey's operations stack with health checks every thirty seconds and alerting on extended unavailability.

## Error code translation

LHDN's MyInvois platform returns errors with structured codes (such as DS302, BR-CL-21, CF-322) that are useful to system integrators but meaningless to SME customers. ZeroKey maintains a translation layer that maps every known LHDN error code to a plain-language explanation in each supported language, along with a suggested user action.

The translation layer is maintained as a structured catalog in the codebase, versioned alongside this document. When a new LHDN error code is encountered that is not in the catalog, the system gracefully falls back to displaying the code itself with a generic "we encountered an unexpected error" framing while engineering investigates and adds the new code to the catalog. The "raw" LHDN error code is always available to the user in an expandable "technical details" section, useful for accountants and for anyone needing to communicate with LHDN directly.

## Reference data caching

Several pieces of LHDN-published reference data are required for invoice construction: the MSIC catalog, the classification code list, the UOM code list, the tax type codes, the payment terms codes, and the country code list. These catalogs are relatively stable but do change. ZeroKey caches all reference data locally with monthly refresh cycles and immediate refresh on detected changes (LHDN sometimes publishes urgent corrections).

The cache is versioned. Every invoice submission records the reference data version it was constructed against, enabling later audit traceability. If LHDN deprecates a code that an old invoice referenced, the historical invoice remains accurate to its time even though that code would no longer be acceptable for new submissions.

## Sandbox and test environment

LHDN provides a MyInvois sandbox environment for software intermediaries to test their integration before going live with real customer data. ZeroKey maintains a complete sandbox integration in parallel with production. Every change to the integration code is tested against the sandbox before deployment to production. The sandbox is also available to higher-tier customers (Pro and Custom) for their own integration testing, particularly when they are using the API ingestion channel.

The sandbox uses different credentials, different endpoints, and different data than production. There is no path by which a sandbox submission could ever reach production MyInvois. The separation is enforced at the network and credential layer.

## Versioning and migration

LHDN publishes new versions of the MyInvois specification periodically. Each version may introduce new mandatory fields, change validation rules, deprecate old codes, or refine existing behaviors. ZeroKey's integration is versioned. The current production version is recorded in this document and in the codebase. When LHDN publishes a new version with a future enforcement date, we plan the migration to that version with adequate lead time, run both versions in parallel during the transition period if needed, and switch over before the enforcement date.

Customers do not see the version migration. The operational complexity is absorbed entirely by us. Customers see only that their invoices continue to validate without disruption.

## How this document evolves

When LHDN publishes a specification update, this document is the first artifact updated. The update describes the change, references the LHDN announcement, and identifies the implementation work required. The implementation, the test suite, and the reference data catalogs are then updated to match.

When the integration encounters an undocumented LHDN behavior in production — a new error code, an unexpected validation rule, a non-obvious edge case — the discovery is recorded in this document with the date and context. The document grows over time as our operational knowledge of MyInvois deepens.

When LHDN's specification and our implementation diverge, this document is the authority for resolving the discrepancy. The resolution is either to update the implementation to match the specification or to file a clarification request with LHDN; we never resolve the divergence by silently letting the implementation drift.