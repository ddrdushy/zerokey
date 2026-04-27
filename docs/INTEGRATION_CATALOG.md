# INTEGRATION CATALOG — ZeroKey

> Every external system ZeroKey talks to. This document captures the full inventory of integrations, what they are used for, how we authenticate to them, what data flows between us, and what failure modes matter operationally.

## Why this catalog exists

A modern SaaS product is not a single system; it is a coordination layer over many external services. ZeroKey at v1 already integrates with a dozen distinct external systems, and the count grows over time. Without a single catalog, integrations get added piecemeal, credentials get scattered, failure modes get understood only when they break, and the operational surface area is unknowable.

This document is the central inventory. Every integration listed here is an active dependency. Every credential reference points to where in the secrets infrastructure that credential lives. Every failure mode points to the runbook that handles it. When a new integration is added, this catalog is updated as part of the same pull request.

## How integrations are organized

Integrations are grouped by category: regulatory, billing, AI engines, communication, accounting connectors, observability, security, and infrastructure. Within each category, integrations are listed individually with a consistent structure.

For each integration, we capture: what the integration is for, what data flows in each direction, how we authenticate, what the failure modes are, what their criticality is to the product, what the runbook reference is, and any contractual or commercial notes that affect operations.

## Regulatory integrations

The most critical integrations because failure here is customer-impacting and time-sensitive.

### LHDN MyInvois

The MyInvois platform is the destination for every e-invoice ZeroKey processes. Detailed integration specification is in `LHDN_INTEGRATION.md`.

Authentication is two-tiered: ZeroKey authenticates as a registered software intermediary using LHDN-issued client credentials, and within each authenticated session the specific customer Organization is identified through their TIN and applies the customer's digital certificate to sign each submission. Credentials live in AWS Secrets Manager under a dedicated path and are rotated according to LHDN's policy.

Data flowing to MyInvois consists of structured invoice payloads, signed XML documents, cancellation requests, and status polling queries. Data flowing back consists of validation responses, assigned UUIDs, QR codes, and rejection error codes.

Failure modes include LHDN platform outage (handled by submission queueing, customer-facing status banner, and automatic retry on recovery), rate limiting (handled by internal queue throttling), schema validation rejections (translated to plain-language errors in the customer's language and surfaced in the exception inbox), and credential issues (alerts the operations team immediately).

Criticality is the highest in the system. A sustained failure here means our customers cannot meet their compliance obligations. The runbook lives in `OPERATIONS.md` under "MyInvois disruption response."

### LHDN TIN Verification API

Separate from MyInvois itself, LHDN exposes a TIN verification endpoint for confirming that a given TIN exists and corresponds to a registered entity.

We call this endpoint when a customer adds a buyer to their customer master and periodically to refresh cached verifications. Cached results have a configurable TTL (default 90 days).

Authentication uses the same credentials as MyInvois. Data flowing to LHDN is a TIN string and basic context. Data flowing back is the verified entity name and any verification metadata.

Failure modes include endpoint unavailability (we degrade gracefully, allowing invoice submission with a flag indicating verification was deferred), verification rejections (the customer is notified and the invoice is held in the exception inbox), and rate limiting (we throttle internally).

Criticality is high but not blocking. We can submit invoices with unverified TINs in the customer's preview state; we cannot finalize submission without verification.

### Bank Negara Malaysia exchange rate API

For multi-currency invoices, BNM publishes daily reference rates. We fetch these once daily and cache them.

Authentication is anonymous (the rate API is public). Data flowing in is currency pair and date queries; data flowing back is the rate.

Failure modes are handled by graceful fallback to the most recent cached rate, with an annotation in the invoice that the rate is from a date earlier than the invoice issue date if the gap is significant.

Criticality is medium. Failure does not block customer operations.

## Billing integrations

### Stripe

Stripe handles payment processing for our subscription billing. We support credit card payments globally and FPX bank transfer for Malaysian customers (FPX is exposed through Stripe's local payment methods).

Authentication uses Stripe's restricted API keys with separate keys for live and test modes. Keys live in AWS Secrets Manager and are rotated on a defined schedule.

Data flowing to Stripe consists of customer creation, subscription creation and updates, payment method tokenization, and invoice generation requests. Data flowing back consists of payment confirmations, payment failures, dispute notifications, and subscription state changes.

We use Stripe's webhooks heavily for asynchronous notification of payment events. The webhook handler verifies signatures and updates our local Subscription and Payment records accordingly. Webhook delivery failures are retried by Stripe and we handle idempotency on our side.

Failure modes include payment processor outage (rare but possible; we hold pending payments and retry on recovery), specific card declines (translated to user-friendly messages and surfaced in the customer's billing area with retry options), webhook delivery delays (handled by reconciliation jobs that periodically poll Stripe for any state changes we may have missed), and credential rotation (a managed process with overlap windows so production traffic is never affected).

Criticality is high for billing operations. Customer-facing impact of a Stripe outage is delayed payment posting; product functionality is not affected.

### FPX (via Stripe)

Malaysian customers strongly prefer FPX bank transfer for recurring payments because Malaysian credit card adoption for B2B SaaS is uneven. FPX support is implemented through Stripe's local payment method integration.

Specifics of FPX (the Financial Process Exchange) include real-time bank-to-bank transfer authorization, support across all major Malaysian retail banks, and slightly different reconciliation timing than card payments. Operationally these are handled inside our Stripe integration; we do not maintain a direct FPX integration.

## AI engine integrations

These are the engines that the engine registry routes to. Each is a distinct integration with its own credentials, rate limits, and failure modes. Detailed routing logic is in `ENGINE_REGISTRY.md`; this section captures the operational specifics.

### Anthropic Claude API

Used as the primary engine for FieldStructure and VisionExtract capabilities. Calls are made to the Anthropic Messages API with Claude Sonnet (latest version) as the default model.

Authentication is via API key in the `x-api-key` header. Keys live in AWS Secrets Manager and are scoped to the ZeroKey workspace at Anthropic. Rotation is supported and tested.

Data flowing to Anthropic includes invoice text content, document images for vision calls, and structured prompts for extraction. We do not send any data through Anthropic that we would not want to appear in audit logs; the prompts are carefully designed to minimize PII exposure beyond what is operationally necessary for extraction.

Failure modes include rate limiting (handled by routing fallback to other engines), model unavailability during version transitions (handled by routing to alternate Claude versions or alternate vendors), latency degradation (de-prioritizes Claude in routing for cost-sensitive paths until recovery), and content policy rejections (rare for invoice content but handled by surfacing the affected invoice for human review).

Operational note: Anthropic's prompt caching feature meaningfully reduces our per-call cost for prompts that have a stable prefix; we use this where it applies.

### OpenAI API

Used as a secondary engine for FieldStructure and as a primary embedding engine. Calls cover GPT family (currently GPT-5 mini for cost-sensitive paths and GPT-5 for complex paths) and text-embedding-3-large for embeddings.

Authentication is via API key. Same secrets discipline as Anthropic.

Failure modes are similar to Anthropic. OpenAI has historically had higher rate-limit incidents than other vendors during periods of high industry demand; the routing falls back to Anthropic or Mistral when OpenAI is throttling.

### Google Gemini API

Used as a tertiary engine, particularly strong for Mandarin-heavy documents. Authentication is via Google Cloud service account credentials with appropriate scopes.

### Mistral La Plateforme

Used as a vendor-diversification option for FieldStructure, especially for cost-sensitive paths. Authentication via API key.

### Azure Document Intelligence

Used as the primary OCR engine for scanned PDFs and images. Lives in our Azure subscription with the resource group dedicated to ZeroKey production.

Authentication uses Azure Active Directory service principal credentials, integrated with our broader Azure infrastructure access pattern.

Failure modes include service disruption (routing falls back to AWS Textract or Google Document AI), region-specific outages (we use the Southeast Asia region for data residency), and Azure-specific authentication issues (handled by token refresh logic).

### AWS Textract

Used as a secondary OCR engine, particularly for AWS-only customer deployments. Authentication via IAM roles within our AWS account. Failure modes include service disruption (routing fallback to other engines).

### Google Document AI

Used as a tertiary OCR engine. Authentication via Google Cloud service account.

### Self-hosted PaddleOCR and Tesseract

Run on dedicated GPU instances within our VPC for fully on-premise paths and as fallbacks when external engines are unavailable. Authentication is local. Failure modes include instance health (handled by ECS replacement) and accuracy limitations (handled by routing to cloud engines as primary).

### Cohere

Used as a secondary embedding engine, especially for multilingual content. Authentication via API key.

## Communication integrations

### Email (transactional)

Transactional emails for signup confirmations, password resets, invoice notifications, billing updates, and webhook notifications are sent through **Postmark** (or **Amazon SES** as the primary, with Postmark as a backup).

Authentication via API token. Outbound emails are signed with DKIM, SPF, and DMARC records configured on the zerokey.symprio.com domain.

Failure modes include delivery failures (logged and retried), bounces (the user's email is marked invalid until updated), and spam complaints (the user is unsubscribed from non-essential notifications and the operations team is notified for investigation).

### Email (inbound forwarding)

The customer's per-Organization forwarding address (`<slug>@in.zerokey.symprio.com`) accepts email and routes it to our ingestion pipeline. The receiving infrastructure is **Cloudflare Email Routing** plus a Lambda-based handler that uploads attachments to S3 and creates IngestionJob records.

Failure modes include delivery delays from sending mail servers (we cannot control), email being routed to junk by intermediate mail servers (handled by SPF/DKIM correctness on our end and by clear customer documentation about whitelisting our domain), and invalid attachments (rejected with a bounce message explaining the issue).

### WhatsApp Business API

For customer notifications and for the WhatsApp ingestion channel. Integration is via **Meta's WhatsApp Business Cloud API**.

Authentication uses an access token from a Meta Business account configured for ZeroKey's verified business profile. Tokens are rotated periodically.

Outbound notifications use approved message templates (Meta requires templates for transactional messages). Inbound messages from customers are received via webhook, attributed to the customer based on registered phone number, and routed to ingestion or status-query handling.

Failure modes include template rejection by Meta (we maintain alternate templates and the operations team handles template approval issues), customer phone number changes (handled by re-verification flow), and rate limiting (Meta enforces limits per business profile; handled by queueing for non-urgent messages).

### SMS (backup notifications)

For critical notifications when email and WhatsApp are unavailable. Integrated via **Twilio** as the primary or **MessageBird** as a backup.

Used sparingly because SMS is expensive and Malaysian customers strongly prefer WhatsApp. Used for security-critical notifications (login from new device, password change confirmation) and for users who explicitly opt into SMS for critical updates.

## SSO integrations

For Pro tier and above, customers configure SSO with their identity provider.

### SAML 2.0

Generic SAML support that works with any SAML 2.0 identity provider including Okta, Microsoft Entra ID (formerly Azure AD), Google Workspace, OneLogin, and others. The customer admin uploads the IdP's metadata XML or configures the issuer URL, certificate, and attribute mapping.

Failure modes include certificate expiration on the IdP side (we surface this in the customer's settings with renewal guidance), attribute mapping issues (debug-level error messages explain what attribute we expected and what we received), and clock skew (we accept a small skew window).

### OpenID Connect

Generic OIDC support. Same providers, slightly different configuration shape.

## Accounting connector integrations

These are the customer-facing connectors to the major Malaysian SME accounting platforms. They are P1 features for Scale tier and above.

### SQL Account

Read-only connector that pulls newly issued sales invoices from a customer's SQL Account database on a configurable schedule. Authentication uses the customer's SQL Account database credentials, encrypted with KMS-backed envelope encryption.

We deliberately do not write to SQL Account in v1; the connector is read-only to minimize blast radius. Write-back of LHDN UUIDs is a P2 feature.

Failure modes include database connectivity issues (the customer is notified), schema variations across SQL Account versions (we maintain compatibility logic for the major versions), and credentials becoming invalid (the connector pauses and the customer is prompted to refresh).

### AutoCount

Same shape as SQL Account. AutoCount and SQL Account are the two dominant Malaysian SME accounting platforms; supporting both well is essential.

### Sage UBS

Slightly more legacy than SQL Account and AutoCount. Schema is more variable across versions. Same read-only approach.

## Observability integrations

### CloudWatch Logs and Metrics

Default observability backend for v1. All structured logs and metrics flow here. Authentication is via IAM roles within our AWS account.

### Sentry (or similar)

Application-level error tracking, used for catching unhandled exceptions and surfacing them with stack traces. Authentication via DSN. We sanitize sensitive fields before sending events.

### PagerDuty (or similar)

On-call paging for critical alerts. Authentication via integration keys.

### Status page (Statuspage.io or self-hosted)

The public status page reflecting real system health. Updated automatically from internal metrics for known incident classes; updated manually by the operations team for narrative context during incidents.

## Security integrations

### Cloudflare

Acts as the edge layer: DNS, TLS, WAF, DDoS protection, bot management, CDN. Configuration is via Terraform-managed Cloudflare resources. Authentication for admin operations is via API token; runtime traffic is unauthenticated public-facing through the WAF.

### AWS KMS

Key Management Service for cryptographic key custody. Holds envelope keys for customer certificates, field-level encryption keys for PII, and various other key materials. Authentication via IAM roles tied to specific services that need each key.

### AWS Secrets Manager

Stores all credentials (API keys, database passwords, third-party tokens). Service code retrieves credentials at startup or on rotation events. Rotation is automated for credentials that support it.

### HashiCorp Vault (potentially, for Custom-tier deployments)

Some BFSI customers require Vault for credential management rather than AWS Secrets Manager. The integration is supported on a per-deployment basis for Custom-tier customers.

## Infrastructure integrations

### AWS (broadly)

The cloud provider hosting all production infrastructure. Specific services include EC2, ECS, Fargate, RDS, ElastiCache, S3, ALB, KMS, Secrets Manager, CloudWatch, Route 53, IAM, VPC. Authentication and authorization are managed through IAM with the principle of least privilege.

### GitHub

Source control, CI, deployment pipeline. Authentication via GitHub App with scoped permissions for the ZeroKey organization repositories.

### Docker Hub or AWS ECR

Container registry. We use ECR for production images for tighter integration with our AWS environment.

## Future integrations on the roadmap

Several integrations are on the roadmap but not active in v1.

**Zapier and Make** for generic automation platform connectivity. P2 timeline.

**Microsoft Teams and Slack notifications** as alternative notification channels for enterprise customers. P2 timeline.

**ERP connectors** beyond SME accounting platforms — Oracle NetSuite, Microsoft Dynamics, SAP Business One — for mid-market and Custom-tier customers. P3 timeline.

**Government APIs beyond LHDN** as Malaysia continues digitizing compliance — SST returns, customs declarations, statutory filings. P3 timeline.

## Credential management discipline

Every credential listed in this catalog has a defined home in our secrets infrastructure. Credentials never appear in source code, configuration files in version control, or environment variables baked into Docker images.

Credentials are retrieved at runtime by services that need them, using IAM-scoped access. A service that does not need a credential cannot retrieve it.

Credential rotation is automated where the underlying service supports it. Where rotation requires coordination (such as updating an external IdP with a new SAML signing certificate), the rotation is a documented procedure in `OPERATIONS.md`.

Credential leakage is a high-severity incident. The procedure for response is documented in `OPERATIONS.md`.

## Failure mode discipline

Every integration has a documented failure mode response. When the integration fails, what happens? Which alternative path is taken? What is communicated to the customer? When is the operations team paged?

These responses are codified in `OPERATIONS.md` runbooks and are tested periodically through chaos exercises (intentionally disabling an integration in a non-production environment to verify the failover and notification logic works).

## How this catalog evolves

When a new integration is added, this catalog is updated in the same pull request. When an integration is deprecated or removed, the catalog reflects the removal with a date.

When a new failure mode is discovered (a vendor outage we had not previously seen, an unexpected error pattern), the catalog entry for that integration is updated with the new failure mode and its response.

When the catalog and reality diverge, the catalog is wrong (update it) or the integration is wrong (fix it). We do not let drift accumulate; uninventoried integrations are a serious operational risk.
