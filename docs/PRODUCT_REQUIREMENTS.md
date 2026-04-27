# PRODUCT REQUIREMENTS — ZeroKey

> The complete catalog of what ZeroKey does. Features are organized by domain and prioritized P0 through P3. P0 is required for first paying customer. P1 is required for general availability. P2 is required for enterprise readiness. P3 is post-GA roadmap.

## How to read this document

Every feature in ZeroKey lives somewhere in this catalog. The feature is named, described in user terms, justified against `PRODUCT_VISION.md`, prioritized for sequencing, and given clear acceptance criteria expressed as user-observable behavior rather than implementation detail. Implementation choices live in `ARCHITECTURE.md`, `ENGINE_REGISTRY.md`, and elsewhere; this document is what we are building, not how.

The priority labels are sequencing tools, not value judgments. A P3 feature is not less important than a P0 feature in absolute terms; it is simply not blocking the next milestone. The roadmap document `ROADMAP.md` translates these priorities into a calendar.

When a feature appears in this document, it is committed. When a feature is removed, it is removed by deliberate edit, not silent omission. When ambiguity exists about scope, this document is the authority.

## Domain 1 — Ingestion

The ingestion domain governs how invoices enter ZeroKey. Our differentiator in this domain is omnivorous acceptance: any reasonable channel and any reasonable format.

The **drag-and-drop web upload** is the foundational ingestion channel and is P0. The user drags one or more files onto the dashboard or upload screen. Files accepted include PDF (native and scanned), JPEG and PNG images, Excel and CSV, screenshots, and ZIP archives containing any combination of the above. Files larger than 25 MB show a clear error before upload begins. Files in unsupported formats show a friendly explanation. Multiple files dropped simultaneously are processed in parallel and appear as separate jobs in the dashboard. Upload progress is visible per file. The drop zone uses the ZeroKey Signal accent color when a valid file is being dragged over it.

The **email forwarding ingestion channel** is P0. Each customer is provisioned with a unique email address at signup, in the form `customername-randomstring@in.zerokey.symprio.com`. Any email sent to this address is processed: attachments become invoice jobs, email body content is captured as a fallback or as supporting context, and reply threads are linked to the originating job for audit purposes. Emails from unrecognized senders are quarantined for the customer's review rather than auto-processed, to prevent spam-induced billing surprises. The email address is shown in the dashboard with a one-click copy.

The **WhatsApp ingestion channel** is P0 for Growth tier and above. The customer registers their WhatsApp number, and a shared ZeroKey number receives photos and PDFs sent to it. The system uses the registered phone number to attribute incoming messages to the right customer. A simple bot interaction confirms receipt, returns extraction status, and offers a link back to the dashboard. The bot is conversational only enough to support upload and status — it is not a general-purpose chat agent.

The **API ingestion channel** is P0 but gated to Scale tier and above. A documented REST endpoint accepts file uploads with metadata. API keys are managed in the customer's settings area, with the ability to create, name, scope, and revoke keys. API responses include the job ID for status tracking via webhook or polling. Detailed API behavior is specified in `API_DESIGN.md`.

The **database connector ingestion** is P1 for Scale tier and above. Read-only connectors to SQL Account, AutoCount, and Sage UBS pull newly issued sales invoices on a configurable schedule (default fifteen minutes). The connector is configured per customer with their database credentials, which are stored encrypted using KMS-backed envelope encryption. The connector is non-destructive — it never writes back to the source database — and provides clear logs of what was synced.

The **bulk ZIP upload** is P0. A single ZIP file containing many invoices uploads as a single action and unpacks into individual jobs. The user sees a progress summary as the jobs run.

The **browser extension ingestion** is P2. A Chrome and Edge extension lets users send any web page or PDF they are viewing into ZeroKey with a single click. Useful for the user who receives an invoice via supplier portal or as a Gmail attachment they did not forward to the email channel.

The **mobile app camera capture** is P2. A native or progressive-web-app camera flow lets users photograph paper invoices with auto-cropping, perspective correction, and multi-page batching. Acceptance criteria include a usable capture experience on a typical Malaysian mid-range Android phone in low-light office conditions.

## Domain 2 — Extraction and structuring

Once an invoice is in ZeroKey, the extraction domain transforms the raw input into structured invoice data ready for LHDN.

The **routed extraction pipeline** is P0. The pipeline classifies each incoming file by type and selects an appropriate extraction strategy. Native PDFs route through text extraction (using a library such as pdfplumber) followed by language-model field structuring. Scanned PDFs and images route through optical character recognition followed by language-model structuring, with a vision-language-model fallback for low-confidence cases. Excel and CSV files route through structured parsing with column inference and language-model normalization. Email body content routes through plain-text language-model structuring. The routing logic is testable, observable, and configurable per customer plan tier. Detailed routing rules and engine choices live in `ENGINE_REGISTRY.md`.

The **fifty-five field extraction** is P0. The pipeline extracts every LHDN-mandatory field from the invoice: supplier identification (TIN, name, address, SST registration), buyer identification, invoice metadata (date, number, type, currency), line items (description, quantity, unit price, MSIC code, classification code), tax calculations (SST amount, tax rate, exemption codes), and totals. Each extracted field carries a confidence score. The complete LHDN field specification lives in `LHDN_INTEGRATION.md`.

The **per-field confidence scoring** is P0. Every field returned by the pipeline carries a confidence value from 0 to 1. Fields above a configurable threshold are auto-populated and treated as extraction-passed. Fields below the threshold are flagged for human review and visually highlighted in the review screen. The threshold is initially 0.85 but is admin-configurable per plan or per customer.

The **review and correction interface** is P0. After extraction, the user sees a side-by-side view: the original document on the left, the extracted fields on the right. Low-confidence fields are highlighted with a calm amber outline. The user can click any field to edit it, can reject any line item, can split or merge line items, and can correct the auto-detected document orientation if needed. All edits are tracked.

The **learn-from-corrections system** is P0. When a user corrects an extraction error, the correction is captured and used to improve future extractions for that customer. Customer-specific patterns (recurring suppliers, recurring item descriptions, recurring tax treatments) accumulate in the customer master and item master. The next time the same supplier or item appears, the prior correction influences the extraction. This is the heart of our compounding-intelligence moat.

The **multi-page invoice handling** is P0. Invoices that span multiple pages are processed as single logical invoices. Page breaks within line item tables are reconciled. Continuation totals are validated.

The **multi-invoice document handling** is P1. A single PDF that contains multiple separate invoices (common in batch supplier statements) is split into multiple invoice jobs automatically, with the user able to confirm or correct the split.

The **handwritten field tolerance** is P2. For photographed paper invoices with handwritten amendments (corrected prices, scribbled approval signatures, marginal notes), the pipeline degrades gracefully and surfaces the relevant region for human review rather than silently misreading.

## Domain 3 — Enrichment

The enrichment domain fills in fields that are not directly extractable from the source document but are required by LHDN.

The **customer master** is P0. Every buyer the customer has ever invoiced is recorded with TIN, name, address, classification code, and contact details. New invoices auto-suggest matched buyers. Updates to a buyer's record propagate to future invoices but never to past invoices. The customer master is searchable, editable, exportable, and importable from CSV.

The **item master** is P0. Every item or service the customer has invoiced is recorded with name variations, MSIC code, classification code, default tax treatment, and unit. New line items auto-suggest matched items. The item master suggests MSIC codes for new items based on description similarity to existing items.

The **TIN live verification** is P0. The customer's and buyer's TIN are checked against LHDN's verification endpoint before submission. Invalid TINs are flagged with the LHDN response so the user can correct them. Verified TINs are cached for a configurable duration (default 90 days) to avoid repeated lookups.

The **MSIC code suggestion** is P0. The Malaysia Standard Industrial Classification system contains thousands of codes; an SME owner cannot be expected to know them. ZeroKey suggests the right code based on the item description, the customer's industry, and prior usage patterns. Suggestions are presented with confidence ranking; the user picks one or accepts the top suggestion. Suggestions are powered by a Qdrant-backed semantic search over the MSIC catalog combined with language-model reasoning over the item context.

The **classification code suggestion** is P0. LHDN classification codes (separate from MSIC) are suggested in the same way. The pairing between MSIC and classification is also remembered per customer.

The **currency conversion handling** is P1. Invoices in foreign currency are detected, the exchange rate at invoice date is fetched from a reliable source (Bank Negara Malaysia daily rates), and the MYR equivalent is calculated for LHDN submission. The user sees both currencies clearly.

The **self-billed invoice detection** is P1. Foreign supplier scenarios that require self-billed invoices are detected based on the supplier's TIN absence and country code. The user is prompted to confirm self-billed treatment, and the invoice is structured accordingly.

The **consolidated B2C invoice support** is P2. For retail businesses issuing many small B2C transactions, end-of-day consolidation into a single LHDN-compliant consolidated invoice is supported. Per-transaction detail is retained internally for audit while the consolidation is what gets submitted.

## Domain 4 — Validation

The validation domain catches errors before they hit LHDN, dramatically improving first-submission success rates.

The **pre-flight validation** is P0. Before any invoice is submitted, every field is checked against LHDN's published validation rules: required fields present, format conventions met (TIN structure, date format, currency code), referential integrity (line item totals match invoice totals within tolerance), tax calculations correct, classification codes valid for the supplier's MSIC. Failures are reported in plain language with specific field references and one-click suggested fixes.

The **error message translation** is P0. LHDN error codes returned at any stage (pre-flight or post-submission) are translated to plain language in the user's preferred locale. The original LHDN code is shown in a "technical details" section the user can expand if they want to share with their accountant.

The **threshold rule enforcement** is P0. Specific LHDN rules with hard thresholds — the RM10,000 single-invoice rule, the consolidation eligibility threshold, the foreign supplier rule — are enforced in pre-flight. Users cannot accidentally consolidate a transaction that should be standalone.

The **batch validation summary** is P1. When a batch of invoices is uploaded, the dashboard surfaces a summary: how many passed pre-flight, how many need attention, what the most common errors are. The user fixes errors in a single review pass rather than per-invoice.

The **custom validation rules** is P2 for Scale tier and above. Customers can define their own pre-flight rules: enforce a minimum line item description length, require a particular field to match a regex, block submission if the buyer's address country is not Malaysia. Rules are managed in the customer's settings area.

## Domain 5 — Signing and submission

The signing and submission domain is where ZeroKey turns a validated invoice into an LHDN-acknowledged record.

The **digital certificate management** is P0. The customer's LHDN-issued digital certificate is uploaded once, with KMS-backed envelope encryption, and used for all signing. The certificate is never copied to the application database; the encrypted blob lives in object storage with an access policy gated by KMS, and signing operations happen inside an isolated signing service that decrypts the certificate transiently. Certificate expiry is tracked, and the customer is reminded thirty, fourteen, and three days before expiry.

The **invoice signing service** is P0. The signing service receives a validated invoice payload, retrieves the customer's certificate via KMS, applies the digital signature according to LHDN's specifications, and returns the signed XML. The service runs in isolation with audited access logs.

The **MyInvois API submission** is P0. The signed invoice is submitted to LHDN's MyInvois API. The system handles retries for transient errors (rate limiting, temporary unavailability), backs off appropriately, and surfaces persistent errors to the customer. Successful submissions return an LHDN UUID and QR code, which are stored and displayed.

The **submission status polling** is P0. After submission, MyInvois validation can take from seconds to several minutes. The system polls for validation status and updates the customer's dashboard in real-time. Final states (Validated, Rejected) trigger appropriate user notifications via the customer's preferred channel.

The **scheduled submission** is P1. The customer can configure a delay between invoice creation and submission (for example, "submit at end of day"). This supports workflows where invoices are drafted by junior staff and submitted by senior staff at a fixed time, and provides a window for last-minute corrections.

The **batch submission** is P1. Many invoices can be submitted as a single batch operation, with batch-level status tracking and per-invoice results.

The **invoice cancellation** is P0. LHDN allows invoice cancellation within 72 hours of submission. ZeroKey surfaces this option clearly on validated invoices and handles the cancellation API flow.

The **rejection and rework** is P0. Invoices rejected by LHDN are returned to the user's exception inbox with the rejection reason translated to plain language and a path to fix and resubmit.

## Domain 6 — Customer and team management

This domain governs how customers are organized, who has access, and how multi-user organizations work.

The **organization and user model** is P0. Each customer subscription is an organization. Each organization has one or more users with assigned roles. Roles include Owner (full access including billing), Admin (full access excluding billing), Approver (can approve and submit invoices), Submitter (can create invoices, cannot approve), and Viewer (read-only). Multi-user is gated to Growth tier and above.

The **single sign-on** is P1 for Pro tier and above. SAML 2.0 and OpenID Connect SSO are supported via providers like Okta, Microsoft Entra ID, and Google Workspace. The customer admin configures SSO and can require it for all users in the organization.

The **multi-entity support** is P1 for Pro tier and above. Accounting firms managing multiple client SMEs see all their entities in a single dashboard with consistent navigation. Each entity has its own customer master, item master, audit log, and submission stream. Users can be granted access to specific entities.

The **invitation and onboarding flow** is P0. The Owner or Admin invites new users via email. The invited user accepts, sets up their credentials (or signs in via SSO), and is dropped into the organization with their assigned role. The invitation flow respects the user's preferred language.

The **API key management** is P0 for Scale tier and above. API keys are created, named, scoped to specific operations, and revoked from the settings area. Each key carries an audit trail of when it was created, by whom, and when it was last used.

## Domain 7 — Workflow and approvals

This domain supports customers whose internal process requires multiple steps.

The **single-step approval** is P0. The default workflow is that the user who creates an invoice is also the one who submits it. No approval gate.

The **two-step approval workflow** is P1 for Growth tier and above. Customers can require that invoices be approved by an Approver-role user before submission. The Approver sees a queue of pending invoices, reviews them, and approves or rejects with a comment.

The **multi-step approval workflow** is P1 for Scale tier and above. Customers can configure custom approval chains based on invoice properties: amount thresholds (invoices over RM50,000 require senior approval), buyer types, item categories. Chains can have multiple sequential or parallel approvers.

The **approval delegation** is P2. Approvers can delegate their approval authority to another user for a specified date range (for vacations, leave). Delegations are auditable and revokable.

## Domain 8 — Customer dashboard and inbox

This domain is the customer's daily working surface.

The **main dashboard** is P0. The dashboard shows: today's submission count and status, the exception inbox count, recent submissions list, current plan usage and remaining quota, and contextual prompts for any setup steps still incomplete. It is calm, scannable, and respects Principle 8 (progressive disclosure).

The **exception inbox** is P0. Every invoice that needs human attention — low-confidence extractions, validation failures, LHDN rejections — appears in the exception inbox. Items are sorted by urgency and age. Clearing the inbox is a daily ritual the design supports.

The **submission stream** is P0. A live-updating list of all submissions with status, supplier or buyer, amount, and timestamp. Filterable, searchable, and exportable.

The **invoice detail view** is P0. A complete view of any invoice: original document preview, all extracted fields, the signed XML, the LHDN UUID and QR code, the audit trail of every action taken on this invoice, and any attached communications.

The **status notifications** is P0. The customer receives notifications via their preferred channels (email, in-app, optionally WhatsApp on Growth and above) for: validation failures, LHDN rejections, approaching plan limit, completed batch submissions, and events the customer has subscribed to. Notification preferences are configurable per user.

The **search and filter** is P0. Across the entire submission history, the customer can search by buyer, by amount, by date range, by status, by classification, or by free text. Search results return in under one second.

The **export and reporting** is P1. The customer can export submission data to CSV or Excel for accounting reconciliation, and can generate standard reports (monthly submission summary, top buyers, top suppliers, validation failure rate). Custom reports are P2.

## Domain 9 — Audit and compliance surface

This domain is what allows ZeroKey to be trusted with regulated work.

The **immutable audit log** is P0. Every action — every upload, every extraction, every edit, every approval, every submission, every cancellation, every settings change — is recorded to an immutable hash-chained audit log. The log cannot be modified or deleted. Detailed specification lives in `AUDIT_LOG_SPEC.md`.

The **audit log inspection UI** is P0. The customer can browse their audit log, filter by user, by action type, by date range, and view the full chain of any individual invoice. The hash-chain integrity can be verified visibly.

The **audit log export** is P0. The customer can export their audit log in a tamper-evident format (signed JSON or signed CSV) for their auditors. Export operations are themselves audit-logged.

The **compliance dashboard** is P1. A summary view shows the customer's compliance posture: validation success rate, average submission time, percent of submissions in the relaxation window versus penalty window, and any open compliance risks. Useful for customers preparing for an LHDN audit.

The **historical archive** is P0. Submitted invoices are retained according to the customer's plan retention policy (default seven years for compliance, configurable up to indefinite for Custom-tier customers). Archived invoices remain searchable and downloadable.

## Domain 10 — Billing and self-service

This domain handles money, plans, and the self-service surface that lets ZeroKey scale without sales touch on lower tiers.

The **plan selection and signup** is P0. The pricing page shows all tiers, the trial CTA leads to signup, and signup completes in under two minutes. No credit card required for trial. Upgrade to paid happens in the billing settings.

The **trial-to-paid conversion** is P0. Toward the end of the trial, the customer is prompted to choose a plan. If they do not, the account remains accessible in read-only mode for fourteen additional days, after which it is suspended and after another thirty days its data is purged according to the deletion schedule in `COMPLIANCE.md`.

The **payment method management** is P0. The customer can add, change, and remove payment methods (credit card via Stripe, FPX bank transfer for Malaysian customers). Failed payments trigger automated retry with customer notification. After three failed retries, the account moves to read-only mode with clear in-product banners.

The **invoice and receipt history** is P0. The customer can view and download their ZeroKey-to-customer invoices (yes, we issue our own e-invoices for our subscription fees, the meta-loop is not lost on us) and payment receipts at any time.

The **plan upgrade and downgrade** is P0. The customer can change plans self-serve. Upgrades are immediate and prorated. Downgrades take effect at the next billing cycle.

The **usage meter** is P0. The customer's current month's usage against their quota is visible on the dashboard with appropriate amber and red thresholds. Approaching-limit notifications are sent at 80%, 90%, and 100%.

The **cancellation flow** is P0. Cancellation completes in three clicks. No retention dialogue, no friction. The customer chooses immediate cancellation (with prorated refund per terms) or end-of-cycle cancellation. Their data is retained per the deletion schedule.

The **money-back guarantee processing** is P0. Refund requests within the guarantee window are processed without question. The customer service team can issue refunds; the system enforces the guarantee window and logs every refund event.

## Domain 11 — Super-admin (internal operations)

This domain is the internal-only surface used by the ZeroKey team to operate the platform. Per `BUSINESS_MODEL.md`, this is also where pricing, plans, feature flags, and similar configuration live.

The **plan and pricing administration** is P0. The super-admin console exposes all plan parameters as editable: name, prices, quotas, overage rates, included features, billing cadence, trial parameters, retention policies. Changes are versioned and effective-dated. Existing customers stay on grandfathered plan versions unless migrated explicitly.

The **feature flag administration** is P0. Every feature in the product is gated by a feature flag at the plan level, the customer level, or the global level. The super-admin can enable or disable any feature for any customer for any reason. Flag changes are audit-logged.

The **engine registry administration** is P0. The OCR engines and language-model engines registered in the routing system are managed from the super-admin console: which engines are active, which engines are eligible for which plan tiers, what the cost and quality calibration values are, what the fallback chains are. Detail in `ENGINE_REGISTRY.md`.

The **customer support tools** is P0. Authorized support staff can: view a customer's account state (with appropriate access logging), impersonate a customer's view of their dashboard for troubleshooting (with consent and audit), reset a customer's two-factor authentication, manually retry stuck invoices, and waive overage charges in defined circumstances.

The **billing operations** is P1. Refunds, credits, and invoice adjustments can be applied by authorized staff with reason codes recorded in the audit log.

The **system health dashboard** is P0. Real-time health view of every critical subsystem: ingestion queue depth, extraction pipeline latency, signing service availability, MyInvois API status, payment processor status. Detail in `OPERATIONS.md`.

The **partner and white-label administration** is P2. Partner organizations are configured here: their pricing tier, their branding overrides, their revenue share, and their list of managed customer entities.

## Domain 12 — Integrations

This domain covers everything that connects ZeroKey to other systems. Detailed catalog in `INTEGRATION_CATALOG.md`.

The **outbound webhooks** is P0 for Scale tier and above. Customers configure webhook endpoints to receive real-time notifications when invoices are validated, rejected, or experience state changes. Webhook delivery includes retries with exponential backoff and a dead-letter queue visible to the customer.

The **read-only accounting connectors** is P1 for Scale tier and above. SQL Account, AutoCount, and Sage UBS connectors as described in the ingestion domain.

The **write-back connectors** is P2. Once a ZeroKey invoice is validated by LHDN, the resulting UUID and QR code can be written back to the source accounting system. Optional, configurable, and clearly disclosed.

The **Zapier and Make integrations** is P2. Generic automation platform integrations let customers wire ZeroKey into hundreds of tools without writing code.

The **government API integrations** is P0 (LHDN MyInvois) and P3 (other Malaysian government APIs that may emerge: SST returns, customs declarations, etc.).

## Domain 13 — Trust, security, and observability

This domain is the foundation of enterprise readiness. Detailed in `SECURITY.md`, `COMPLIANCE.md`, and `OPERATIONS.md`.

The **authentication and authorization** is P0. Email-and-password authentication with mandatory 2FA option, magic-link login as alternative, SSO for Pro and above, role-based access control throughout. Session management is secure (httpOnly cookies, CSRF protection, appropriate timeouts) and the customer can review and revoke active sessions.

The **field-level encryption for PII** is P0. Personally identifiable information stored at rest is encrypted at the field level using KMS-backed keys, separate from infrastructure-level encryption.

The **multi-tenant data isolation** is P0. PostgreSQL Row-Level Security ensures that a customer's data cannot be accessed by another customer's user under any circumstance. Tested as part of the security audit. Detail in `DATA_MODEL.md`.

The **rate limiting and DDoS protection** is P0. All public endpoints are rate-limited per customer plan tier. DDoS protection is provided at the edge via Cloudflare WAF.

The **observability stack** is P0. Centralized logs, metrics, and distributed traces are in place from day one. Critical alerts route to on-call. The status page is real and reflects actual system health.

The **incident response process** is P0. Clear runbooks for common incident classes, on-call rotation (initially the founder, then the team), post-incident reviews for customer-impacting events.

The **disaster recovery posture** is P0. Detail in `DISASTER_RECOVERY.md`. Recovery time objective of 4 hours, recovery point objective of 1 hour.

## Domain 14 — Help, education, and onboarding

This domain is the supporting layer that makes self-service actually work.

The **in-product onboarding** is P0. New customers see a guided empty-state experience that gets them to their first successful submission in under ten minutes. No mandatory walkthrough modal; helpful inline copy and just-in-time tooltips.

The **help center** is P0. A searchable help center with categories for getting started, ingestion channels, extraction and review, LHDN-specific guidance, billing, and security. Articles in all four languages.

The **LHDN error code decoder** is P0 and high marketing value. Every LHDN error code has a dedicated help article explaining what it means, why it happens, and how to fix it. These articles also rank in search and bring in inbound traffic.

The **video tutorials** is P1. Short (under 90 seconds) video tutorials for the most common tasks, embedded in relevant help articles and product surfaces.

The **support channels** is P0. Email support for all paid customers, priority email for Growth and above, chat for Scale and above, dedicated success manager for Custom. SLAs per tier are specified in `BUSINESS_MODEL.md` and are themselves admin-configurable.

The **community presence** is P2. A user community on a platform like Discord or a self-hosted Discourse, supplemented by office-hours events. Useful for accountants and bookkeepers to share tips.

## Domain 15 — Future and adjacent

These are explicitly P3 — out of scope for v1 but worth noting now to inform architectural decisions.

The **SST returns automation** is P3. The data we already have makes generating SST 02 returns plausible. Worth noting in architecture so the data model does not foreclose this path.

The **purchase invoice receivable workflow** is P3. ZeroKey's MVP focuses on the customer's outbound (sales) invoices. The mirror workflow — receiving and processing supplier invoices — is a natural extension. The data model accommodates this distinction from the start.

The **e-invoicing for adjacent jurisdictions** is P3. Singapore InvoiceNow, Indonesian e-Faktur, Philippine e-Invoice mandate are all on regional roadmaps. ZeroKey's pluggable architecture is built so the LHDN-specific logic is one module among potential others rather than baked into the core.

The **reconciliation and BI on invoice data** is P3. Once we hold years of structured invoice data per customer, analytics on that data becomes valuable: top buyers, top suppliers, payment cycle analysis, fraud detection, cash flow forecasting. The data model is built so this is straightforward to layer on.

The **payment integration** is explicitly out of scope and not a P3. We are not a payments processor. We may integrate with payment platforms but never become one.

---

## Acceptance criteria philosophy

Every feature in this catalog will be expanded into specific user stories with acceptance criteria as it enters development. The acceptance criteria are always expressed as user-observable behavior: "the user sees X within Y seconds", "the action results in Z visible state", "the error scenario surfaces W in the user's preferred language". Implementation criteria (which library, which database, which queue) are recorded in the engineering documentation, not here.

When a feature ships, this document is updated to reflect any deviation from what was specified. When a feature is renamed, the rename is reflected here. When a feature is removed (because it did not work, because the market did not want it, because we found a better path), it is removed by deliberate edit and dated as removed.

This document is the contract between intent and execution. It is owned by the product team — initially the founder — and updated as the product evolves.