# DATA MODEL — ZeroKey

> The complete entity model for ZeroKey. Every table that exists in PostgreSQL is documented here in the language of the domain, not the language of SQL. This document is the source of truth for what data exists, how entities relate to each other, how multi-tenancy isolation is enforced, and how retention works.

## How to read this document

Entities are described in prose with their attributes and relationships explained. SQL DDL is not in this document; it lives in Django migrations. The reasoning is that DDL changes constantly during development, and a document that mirrors DDL becomes stale within hours. This document captures the durable shape of the model — what entities exist, why, and how they relate — which changes much more slowly.

When a new entity is introduced or an existing one fundamentally changes, this document is updated as part of the migration. When a column is added or renamed without changing the entity's meaning, this document is not updated; the migration is enough.

## Multi-tenancy as a foundational concept

Every customer-facing entity in ZeroKey carries a `tenant_id` column referencing the `Organization` that owns it. PostgreSQL Row-Level Security policies attached to every such table filter rows by the current session's tenant context, set on every database connection by Django middleware at the start of each authenticated request.

The effect of this design is that a query without proper tenant context returns zero rows — not a permission error, just an empty result. A bug in application logic that fails to filter by tenant cannot leak another customer's data because the database itself refuses to return it. This is enforcement at two layers: application logic for normal-path correctness, and database policies for defense in depth.

The few entities that are not tenant-scoped are explicitly system-level: the `Plan` catalog, the `EngineRegistry`, the global `FeatureFlag` definitions, the `MSICCode` and `ClassificationCode` reference data, and similar shared catalogs. These have no `tenant_id` and are readable by all tenants.

The super-admin context is a special role that bypasses RLS via a separate session variable. Only specific service accounts can elevate to this role, and every elevation is audit-logged with the reason.

## Identity domain entities

The identity domain holds users, organizations, roles, and authentication state.

**Organization** is the customer entity. Every paying customer is one Organization. Every user belongs to exactly one Organization. The Organization holds the company's legal name, the registered TIN, the SST number if applicable, the registered address, the primary contact details, the configured billing currency (always MYR for v1), the assigned plan version, the trial state, the active subscription state, the certificate state (uploaded or not, expiry date, KMS key reference), the brand preferences (logo, color overrides for invoice templates), the language preference, and the timezone.

The Organization is the boundary of multi-tenancy. Every customer-facing entity has a foreign key to Organization that doubles as the `tenant_id` for RLS purposes.

For accounting firms managing multiple client entities, each managed client is itself an Organization, and the accounting firm's users are granted access through `OrganizationMembership` records that span multiple Organizations. This is how multi-entity support is structurally modeled.

**User** is an individual person with login credentials. A User has an email, a hashed password (or null if SSO-only), a two-factor authentication state, a preferred language, a preferred timezone, and a set of recovery codes. Users can authenticate by password, magic link, or SSO depending on their Organization's configuration.

**OrganizationMembership** is the link between User and Organization. It carries the user's role within that Organization (Owner, Admin, Approver, Submitter, Viewer), the date they joined, the user who invited them, and any per-membership overrides. A User may have multiple memberships if they belong to an accounting firm that manages multiple Organizations or if they are a partner with access to several customer entities.

**Role** is a system-defined entity describing a permission set. Roles are not customer-editable in v1 (they are fixed: Owner, Admin, Approver, Submitter, Viewer); customer-defined custom roles are a P3 feature.

**Permission** is a fine-grained capability that a Role grants. Examples include `invoice.create`, `invoice.approve`, `invoice.submit`, `customer_master.write`, `audit_log.export`, `billing.manage`, `team.invite`. Service-layer permission checks reference permissions, never roles directly, so that the role-to-permission mapping can evolve without rewriting service code.

**Session** represents an authenticated session. Sessions are stored in Redis with the user ID, the active Organization ID (in case of multi-membership), the IP address, the user agent, the creation timestamp, the last activity timestamp, and a flag for whether two-factor authentication has been completed in this session. Sessions are revocable from the user's settings.

**APIKey** is a credential for programmatic access. Each API Key has a name, a scope (which permissions it grants), a creation timestamp, a last-used timestamp, an optional expiry, and a status (active or revoked). The actual key material is hashed; only a prefix and a hash are stored. API keys are scoped to a specific Organization.

**SSOConfiguration** holds the SSO setup for an Organization on Pro tier and above. It includes the protocol (SAML 2.0 or OpenID Connect), the identity provider's metadata or issuer URL, the certificate for SAML signature verification, the attribute mapping (which IdP attribute corresponds to which User field), and a flag for whether SSO is required (forcing all users to authenticate via SSO) or optional.

## Billing domain entities

The billing domain holds plans, subscriptions, payments, and usage metering.

**Plan** is a subscription tier definition. Each Plan has a unique code (e.g., "starter", "growth", "scale", "pro"), a display name in each supported language, a base price in MYR, the included invoice quota per billing period, the per-invoice overage rate, the included number of user seats, the per-additional-seat rate, the supported ingestion channels, the enabled feature flags, the support tier, the retention period, the API rate limit ceiling, the webhook concurrency cap, the trial duration, the trial invoice limit, the billing cadence options, the annual discount percentage, the effective date range, a version number, and an active flag.

Plans are versioned. When the founder edits a Plan, a new version is created and effective-dated; existing customers continue on their grandfathered version unless explicitly migrated. This is the architectural realization of the configurability principle from `BUSINESS_MODEL.md`.

**Subscription** links an Organization to a specific Plan version. It holds the start date, the end date (null for active subscriptions), the billing cadence (monthly or annual), the next billing date, the current period start and end, and the status (trialing, active, past_due, suspended, cancelled). On plan change, the existing Subscription is closed and a new one is created.

**SubscriptionAddOn** represents an optional add-on attached to a Subscription, for features sold separately from the base tier.

**PromoCode** is a configurable promotional discount. Each code has its discount type (percentage or fixed), discount value, applicable plans, applicable durations (first month, first three months, lifetime), eligibility rules, expiration, and usage limits.

**PaymentMethod** holds a customer's saved payment instrument. The actual card data lives at Stripe; we store only the Stripe reference, the last four digits, the card brand, the expiry month and year, and the holder name. FPX bank transfer methods are similarly stored as Stripe references.

**Payment** records each successful or failed payment attempt with the amount, currency, payment method, Stripe charge ID, status, timestamp, and a link to the resulting customer-facing invoice (yes, ZeroKey issues its own e-invoices for its subscription fees).

**CustomerInvoice** is the invoice ZeroKey issues to the customer for their subscription. It has the line items (base subscription, overage charges, add-ons, discounts), the total, the issue date, the due date, the payment status, and a link to the LHDN UUID and QR code for the e-invoice we submitted on our own behalf.

**UsageEvent** records a single billable event — a successfully validated e-invoice submission. Each event has a timestamp, the Organization, the invoice ID, the engine route used (for cost analysis), and the billing period it counts toward. Usage events are aggregated for invoice generation and for the customer's usage dashboard.

**Refund** records refund operations with the amount, the reason code, the requesting actor (customer self-serve or staff override), and a link back to the original payment.

## Ingestion domain entities

The ingestion domain holds incoming files and the jobs spawned from them.

**IngestionJob** represents a single ingestion event. It carries the source channel (web upload, email forward, WhatsApp, API, database connector), the source identifier (the email message ID, the WhatsApp message ID, the API request ID, etc.), the original filename, the file size, the file MIME type, the S3 object key for the original file, the upload timestamp, the status (received, classifying, extracting, enriching, validating, ready_for_review, awaiting_approval, signing, submitting, validated, rejected, cancelled, error), and the chain of state transitions with timestamps.

A single email forward with three attachments produces three IngestionJobs, one per attachment.

**EmailIngestionAddress** is the unique forwarding address provisioned for each Organization. It includes the Organization reference, the local-part of the address, the creation timestamp, and an active flag.

**WhatsAppLink** records the binding between a phone number and an Organization. It includes the phone number, the Organization, the verification timestamp, and an active flag.

**ConnectorConfiguration** holds the setup for accounting system connectors (SQL Account, AutoCount, Sage UBS). Credentials are stored as KMS-encrypted blobs.

## Extraction domain entities

The extraction domain represents the structured invoice extracted from the source file.

**Invoice** is the structured invoice entity, the central object of the system. It has the IngestionJob it originated from, the invoice direction (outbound — issued by us — or inbound — received from a supplier; v1 focuses on outbound), the invoice number assigned by the customer, the invoice type (standard, credit note, debit note, refund note, self-billed variants), the issue date, the currency, the buyer reference, the supplier reference (the Organization), the subtotal, the total tax, the grand total, the MYR equivalent total, the original currency total, the LHDN-validated UUID once submitted, the LHDN QR code, the signed XML S3 key, the validation timestamp, the cancellation timestamp if cancelled, and the current status mirroring the IngestionJob's lifecycle but representing the structured-invoice perspective.

**LineItem** is a row in an invoice. It has the parent Invoice, the sequence number, the item description, the unit of measurement, the quantity, the unit price, the line subtotal, the tax type, the tax rate, the tax amount, the line total, the MSIC code, the classification code, optional discount or charge with reason, and the matched ItemMaster record if any.

**ExtractionResult** holds the raw output of the extraction pipeline before user review. It captures every field with its extracted value, its confidence score, the engine that produced it, the timestamp, and any subsequent user correction. This entity is what powers the "learn from corrections" feedback loop — comparing the original extraction to the user-confirmed final value reveals what the engine got wrong.

**ExtractionCorrection** records each user-applied correction with the field name, the original extracted value, the corrected value, the user, the timestamp, and the affected Invoice. These corrections feed back into customer-specific prompt tuning and customer master updates.

## Enrichment domain entities

**CustomerMaster** holds a known buyer for a specific Organization. It carries the Organization, the buyer's legal name (and any aliases learned from invoices), the buyer's TIN, the TIN verification state, the TIN last-verified timestamp, the buyer's business registration number, the buyer's MSIC code, the registered address, the contact phone, the SST number, the country code, and a usage count (how many invoices have referenced this buyer). Customer master records accumulate over time and are the primary source of switching cost.

**ItemMaster** holds a known item or service for a specific Organization. It carries the Organization, the canonical item name, the alias variations, the default MSIC code, the default classification code, the default tax type, the default unit of measurement, the default unit price (advisory only), and a usage count.

**TINVerificationCache** holds recent TIN lookups against LHDN's verification API. Cached results have a TTL of ninety days by default, configurable per Plan. Stored fields include the TIN, the verified entity name, the verification timestamp, and the verification source.

**ExchangeRate** caches Bank Negara Malaysia daily exchange rates by source currency, target currency (always MYR for our purposes), date, and rate. Rates are fetched once daily and reused for any invoice issued on that date.

**MSICCode** is the reference catalog of Malaysia Standard Industrial Classification codes. Each entry has the code, the official description in English, the Bahasa Malaysia description, the parent code (for hierarchical navigation), and an active flag. The catalog is refreshed monthly from LHDN's published source.

**ClassificationCode** is similar — the LHDN-published classification code list with descriptions, refreshed monthly.

**UnitOfMeasureCode** holds the LHDN UOM catalog.

**TaxTypeCode** holds the LHDN tax type code catalog.

**CountryCode** holds the ISO country code list with their LHDN-recognized representations.

## Validation domain entities

**ValidationResult** holds the outcome of pre-flight validation against an Invoice. It carries the Invoice, the timestamp, the overall status (passed or failed), and a list of issues. Each issue has a field reference, an LHDN rule code, a severity (blocking or warning), a plain-language explanation in the user's language, and a suggested action.

**ValidationRuleVersion** tracks which version of LHDN's published validation rules an Invoice was checked against, so historical Invoices can be audited against the rule version active at their time.

**CustomValidationRule** is a customer-defined validation rule on Scale tier and above. It has the Organization, the rule name, the rule expression (a constrained DSL), the severity, the message template, and an active flag.

## Submission domain entities

**SigningRequest** records each invocation of the signing service. It carries the Invoice, the Organization, the certificate reference (as a KMS key alias), the requested timestamp, the completed timestamp, the signed XML S3 key, the request status, and the requesting service identity. The signing service writes these for audit; the application reads them for traceability.

**MyInvoisSubmission** records each submission attempt to LHDN. It carries the Invoice, the submission timestamp, the LHDN response code, the LHDN response body (truncated and structured), the assigned UUID on success, the validation status (pending, validated, rejected), the rejection reason if rejected, and a retry counter.

**InvoiceCancellation** records cancellation attempts within the seventy-two-hour LHDN window. It carries the Invoice, the cancellation timestamp, the reason code, the reason text, the LHDN response, and the requesting user.

**SubmissionQueue** is the in-flight queue tracking, modeled in PostgreSQL for visibility (separate from Celery's Redis queues for reliable observability). Each entry has the Invoice, the priority, the queue timestamp, the next attempt timestamp, the attempt count, and the current state.

**Certificate** holds metadata about an Organization's uploaded LHDN-issued digital certificate. It carries the Organization, the S3 key of the encrypted certificate blob, the KMS key alias for the envelope key, the certificate's not-before and not-after dates, the certificate's subject DN, the upload timestamp, the upload user, and an active flag. Note that the actual private key material lives only in the encrypted blob, never decrypted into a database row.

## Customer dashboard and inbox entities

**ExceptionInboxItem** represents an Invoice that needs human attention. It carries the Invoice, the reason category (low-confidence extraction, validation failure, LHDN rejection, manual review requested, certificate expiry approaching), the priority (urgent, normal), the created timestamp, the resolved timestamp, the resolving user, and the resolution action.

**Notification** records each notification sent to a user. It carries the recipient User, the channel (email, in-app, WhatsApp), the type (validation_failed, batch_complete, plan_limit_approaching, etc.), the related entity (typically an Invoice), the delivery timestamp, the delivery status, and whether the user acknowledged it.

**SearchIndex** is a derived table optimized for the customer's search queries across their invoice history. It uses PostgreSQL full-text search with appropriate GIN indexes. It is rebuilt incrementally as invoices change state.

## Workflow and approvals entities

**ApprovalChain** describes a multi-step approval configuration for an Organization. It carries the Organization, the chain name, the trigger condition (amount thresholds, buyer types, item categories), the ordered list of approval steps, and an active flag.

**ApprovalRequest** is a pending approval on a specific Invoice. It carries the Invoice, the ApprovalChain reference, the current step, the assigned approver(s), the requested timestamp, the deadline if any, and the resolution.

**ApprovalAction** records each approver's action with the user, the timestamp, the action (approve, reject, delegate), the comment, and the next state.

**ApprovalDelegation** records a temporary delegation of approval authority from one user to another for a date range, on a P2 timeline.

## Integration domain entities

**WebhookEndpoint** is a customer-configured webhook target. It carries the Organization, the URL, the secret used for HMAC signing, the subscribed event types, the active flag, the creation timestamp, and the last-success and last-failure timestamps.

**WebhookDelivery** records each delivery attempt. It carries the WebhookEndpoint, the event, the request body, the HTTP response code, the response body, the attempt count, the next retry timestamp, and the final state. Failed deliveries beyond the retry budget go to a dead-letter queue visible to the customer.

**ConnectorSyncJob** records each accounting connector sync run with the connector configuration, the start time, the end time, the result (success, partial, failure), the count of invoices synced, and any errors.

**NotificationPreference** holds per-user channel preferences, with one entry per (user, notification_type, channel) combination indicating opt-in or opt-out.

## Audit domain entities

**AuditEvent** is the immutable hash-chained log entry. Every business-meaningful action produces an AuditEvent. The structure of AuditEvent and the chain construction is detailed in `AUDIT_LOG_SPEC.md`. Briefly, each event has a sequence number, the Organization (or null for system events), the actor (user or system service), the action type, the affected entity reference, a content hash, the previous event's hash, the event timestamp, and a structured payload describing what happened.

AuditEvents are append-only at the database level (no UPDATE or DELETE permitted by RLS for the tenant role), and the chain integrity is verifiable by anyone with the public verification key.

**AuditExport** records each customer-initiated audit log export with the requesting user, the date range, the format, the resulting S3 object key, and the export timestamp. Exports are themselves audit-logged.

## Administration domain entities

**FeatureFlag** is a global feature flag definition with the flag name, the description, the default state, and the date introduced.

**OrganizationFeatureFlag** is a per-Organization override of a feature flag, set by super-admin staff for specific customer scenarios.

**SuperAdminUser** is an internal staff member with elevated privileges. They are also a User but additionally have a SuperAdminUser record granting them the super-admin role with specific scopes.

**SuperAdminAction** records each super-admin action with the actor, the affected entity, the action, the reason text, and the timestamp. Super-admin actions are stored both here and in the main AuditEvent log so that customers can see when staff accessed their data.

**ImpersonationSession** records support-staff impersonation events. Each carries the staff user, the impersonated User, the consenting customer admin if any, the start time, the end time, and a flag for whether actions taken during impersonation were limited to read-only.

**Plan**, **EngineRoutingRule**, and similar configurable entities are admin-editable but are described in their domain sections; here we just note that the super-admin console is the surface that edits them.

## Engine registry domain entities

These entities are described in detail in `ENGINE_REGISTRY.md`; included here for completeness of the data model.

**Engine** represents a registered AI engine adapter (Azure Document Intelligence, Anthropic Claude, OpenAI GPT, etc.). It carries the engine code, the capability set it implements, the vendor, the version, the cost per call (rough estimate), the average latency, the current health status, and an active flag.

**EngineRoutingRule** defines when an engine is selected for a specific job. Each rule has a priority, a condition (on file type, customer plan, file size, language, etc.), the chosen engine, the fallback engines, and an active flag.

**EngineCallLog** records each engine call with the engine, the job, the request size, the response size, the latency, the cost (computed), the success status, and the confidence outputs. This is the primary data source for engine quality and cost analysis.

## Retention and deletion

Every entity has a retention policy. Most entities are retained indefinitely while the customer is active; certain entities (logs, ephemeral caches) have shorter retention.

When a customer cancels their subscription, their data enters a sixty-day read-only retention period during which they can export anything they need. After sixty days, customer data is permanently deleted in a deliberate sequence: ingestion job blobs in S3 first (largest in volume), then signed XML blobs, then per-invoice records, then customer master and item master records, then the Organization record itself. The deletion process is run as a Celery task with explicit checkpointing so that interrupted deletions can resume cleanly.

The audit log is treated specially. AuditEvents related to a deleted Organization remain in the system for the legally-required retention period (seven years for tax-related events under Malaysian regulation), but are hashed in a way that preserves chain integrity without retaining personally identifying data. The exact privacy-preserving retention strategy is documented in `COMPLIANCE.md`.

Custom retention requirements for Custom-tier customers (longer retention, customer-controlled deletion) are configured per Organization on the Subscription record and respected by the deletion pipeline.

## Indexing strategy

The data model is heavily indexed for the access patterns we know about. The patterns include: filter by Organization (always, for RLS efficiency), filter by Invoice status (for the dashboard and exception inbox), filter by date range (for exports and reports), full-text search across invoice descriptions and line items (for the customer's search bar), foreign-key joins between the main entities (Invoice to LineItem, Invoice to CustomerMaster, etc.), and time-series queries on UsageEvent for billing aggregation.

Indexes are created as part of the migration that introduces the column they cover. Unused indexes are periodically reviewed and dropped. We avoid the trap of over-indexing — every index has a write cost, and a table with twenty indexes is slow at every write.

## Schema migration discipline

All schema changes flow through Django migrations. Every migration is reviewed for backwards compatibility with the previous deployed version (because we deploy with rolling updates that have both versions in flight briefly). Destructive changes (dropping columns, renaming tables) are split across multiple deployments: introduce the new shape, migrate the application to use it, deploy, then drop the old shape in a subsequent deployment.

Migrations that touch tenant-scoped tables are tested for RLS policy correctness before deployment. A migration that adds a new tenant-scoped table without an RLS policy is rejected at code review.

Migrations that affect AuditEvent or any entity feeding the audit chain are reviewed with extra care. The audit chain's integrity guarantees are foundational; a migration that breaks them is a serious incident.

## How this document evolves

When a new entity is introduced, this document is updated in the same pull request as the migration. When an entity is renamed or its meaning changes, this document is updated. When an entity is deprecated, this document marks it as such and explains the migration path.

When this document and the live schema diverge, the divergence is investigated. Either the document is wrong (update it) or the schema is wrong (fix it). Drift is not tolerated.
