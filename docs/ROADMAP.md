# ROADMAP — ZeroKey

> The plan from foundation to general availability and the year that follows. This roadmap captures the sequencing logic — what depends on what, what unlocks what, and where the deliberate choke points are. It is a working document; the dates shift as evidence comes in, but the sequence is durable.

## How to read this roadmap

The roadmap is organized into phases rather than fixed dates because solo build velocity is variable and customer-discovery insights reshape priorities. Each phase has an entrance criterion (what must be true to start it), a definition of done (what must be true to exit it), and the work it contains.

Phases overlap where the dependencies allow. The architectural foundation is sequential because nothing builds without it; subsequent phases run in parallel where they can.

The current state at the time of writing is **late April 2026**. The mandatory enforcement window for LHDN Phase 4 SMEs (who became mandatory on 1 January 2026) begins on 1 January 2027 with penalty assessments retroactive to non-compliance. This puts a hard market clock on launch: ZeroKey needs to be in production-ready state by the end of Q3 2026 to capture the pre-enforcement panic buying window in Q4 2026.

This is aggressive but achievable. The roadmap below describes how.

## Phase 0: Documentation and architectural foundation

**Entrance criterion:** Strategic clarity on product, market, and brand. (This is now achieved; the documentation set is the artifact of this phase.)

**Definition of done:** Complete documentation set committed to the repository. Claude Code can pick up any task and make sound architectural decisions from the documentation alone.

**Duration:** Late April 2026, completing within days.

**Work:** The 23-document set this roadmap is part of. The documentation establishes the unmovable foundation: vision, brand, architecture, security, compliance, integration, and operations. Without this foundation, every coding session would re-make the same decisions inconsistently.

This phase is unique in that it is mostly documentation work. The temptation to skip it and start coding is strong; the cost of skipping it is that every subsequent week of coding produces less coherent output. Time invested in documentation is recovered ten-fold in coding velocity.

**Exit:** The complete document set is committed. Claude Code is configured with the right `CLAUDE.md` pointer and `START_HERE.md` orientation.

## Phase 1: Skeleton and identity

**Entrance criterion:** Documentation foundation complete.

**Definition of done:** A running Django application with multi-tenant identity, basic UI shell, working authentication, and the foundational data model (Organizations, Users, Memberships, Roles, Sessions). The audit log is operational and recording authentication events.

**Duration:** Roughly two weeks. Early to mid May 2026.

**Work:** Initial repository setup with the agreed structure (described in `ARCHITECTURE.md`). Django project skeleton with the apps that map to the entity domains. PostgreSQL setup with multi-tenant Row-Level Security policies in place from the first migration. Redis setup. Celery setup. The signing service skeleton (no signing logic yet, just the deployment shape and the IAM separation).

The Next.js frontend skeleton with the design tokens from `BRAND_KIT.md` and `VISUAL_IDENTITY.md` configured. Shadcn/ui installed and themed. The basic layout shell with header, sidebar, and content area. The login flow, registration flow, and password reset flow.

The audit log infrastructure including the AuditEvent table, the canonical serialization library, the chain construction logic, and the verification utility. Every authentication event in this phase produces an audit entry, exercising the chain from the start.

The first set of tests covering identity, authentication, and audit log behavior. The CI pipeline running these tests on every commit.

The first deployment to the development environment. The first end-to-end test of the full pipeline from commit to running service.

**Risks during this phase:** Over-engineering early infrastructure that does not serve any customer. The discipline is to build what the documentation specifies, no more. Anything that does not appear in the documentation can be deferred.

**Exit:** A user can sign up, create an Organization, log in, and see an empty dashboard. The audit log shows their actions in chronological order with verifiable hash chains.

## Phase 2: Ingestion and extraction core

**Entrance criterion:** Phase 1 complete; identity and audit infrastructure operational.

**Definition of done:** A user can upload an invoice PDF or image and see a fully-extracted, structured invoice on screen. The extraction works for the majority of invoice formats common to Malaysian SMEs. The engine registry is operational with at least two engines per capability.

**Duration:** Roughly four weeks. Mid May to mid June 2026.

**Work:** The IngestionJob entity and the upload pipeline including the web upload interface, the S3 storage integration, the file validation (size, type, basic safety scanning), and the IngestionJob lifecycle state machine.

The engine registry implementation per `ENGINE_REGISTRY.md` including the capability interfaces, the Azure Document Intelligence adapter for OCR, the Anthropic Claude adapter for FieldStructure and VisionExtract, the routing logic with the launch rules, the engine call logging, and the basic health monitoring.

The pdfplumber-based native PDF extraction path. The OCR-based scanned PDF path with confidence escalation to vision. The FieldStructure path that produces the structured Invoice from extracted text.

The Invoice and LineItem entities. The basic invoice review screen showing the extracted fields, the source document side-by-side, and the ability to correct fields before submission.

The customer master and item master entities with the matching logic that recognizes recurring buyers and items across invoices.

The first attempt at the extraction confidence display, drawing from `UX_PRINCIPLES.md` principle 7 (uncertainty is signaled clearly).

Tests covering the ingestion and extraction paths with a substantial test corpus of varied invoice formats. The corpus is built from publicly available sample invoices, anonymized real invoices from friendly contacts, and synthetic test cases.

**Risks during this phase:** The engine quality might not match expectations on the diversity of Malaysian invoice formats. The mitigation is to start customer discovery interviews now, gather sample invoices from prospects, and use that corpus to tune routing rules and prompts before launch.

**Exit:** A user can upload three different invoice formats (a clean native PDF, a scanned PDF, an image of a receipt) and get reasonable extraction quality on each.

## Phase 3: Validation and submission

**Entrance criterion:** Phase 2 complete; extraction is producing structured invoices reliably.

**Definition of done:** A user can submit a validated invoice to LHDN MyInvois and receive back a UUID, QR code, and validated status. The full happy path works end-to-end against the LHDN sandbox.

**Duration:** Roughly four weeks. Mid June to mid July 2026.

**Work:** The validation engine implementing the LHDN field validation rules (the 55 mandatory fields, the cross-field consistency rules, the calculation reconciliation, the buyer TIN verification through LHDN's API).

The validation result UI showing pass/fail status with field-level issues, plain-language explanations in the user's language, and suggested fixes. This is one of the most product-meaningful interfaces; it is where the value of "we caught the issue before LHDN did" becomes visible.

The signing service implementation including the certificate upload flow, the KMS-backed envelope encryption, the in-process certificate decryption with explicit memory-lifetime control, the XML construction following LHDN's specification, and the digital signature application.

The submission service including the LHDN MyInvois API integration, the request signing with our software intermediary credentials, the response parsing, the UUID and QR code retrieval, and the lifecycle state updates.

The submission queue with priority handling, retry logic with backoff, dead-letter handling, and operational visibility.

The cancellation flow within the LHDN seventy-two-hour window.

Audit log integration so that every validation, signing, and submission event is recorded.

Tests covering the full submission path including LHDN sandbox integration tests that exercise the wire protocol against LHDN's actual sandbox.

**Risks during this phase:** LHDN's specification is detailed and edge cases abound. The mitigation is to start with the most common invoice scenarios and progressively cover edge cases. Customer interviews during this phase identify which edge cases matter most for our target market.

**Exit:** A user can complete the full happy path: upload a PDF, see it extracted, review and confirm fields, validate it, sign and submit it, and see the LHDN UUID and QR code returned. The audit log captures every step.

## Phase 4: Multi-channel ingestion

**Entrance criterion:** Phase 3 complete; the web upload submission path is solid.

**Definition of done:** Email forwarding ingestion, WhatsApp ingestion, and API ingestion work end-to-end. A user can drop an invoice in any of these channels and see it processed identically to the web upload path.

**Duration:** Roughly three weeks. Mid July to early August 2026.

**Work:** The email forwarding infrastructure with the per-Organization unique addresses, the receiving Lambda or equivalent, the attachment extraction, and the IngestionJob creation. The setup involves Cloudflare Email Routing or equivalent and SPF/DKIM correctness on the in.zerokey.symprio.com subdomain.

The WhatsApp Business API integration for inbound media messages. The phone-number-to-Organization mapping. The verification flow when a user first registers their phone number with their Organization.

The API ingestion endpoints per `API_DESIGN.md`. The API documentation site covering ingestion endpoints. The sandbox environment for developers to test against.

The notification system that tells the user when their forwarded or messaged invoice has been processed and is ready for review.

**Risks during this phase:** WhatsApp Business API can be finicky around message templates and media handling. The mitigation is to keep the WhatsApp use cases narrow at launch (just receiving documents and basic status notifications) and expand based on customer feedback.

**Exit:** A user can email an invoice to their unique address and see it appear in their dashboard. They can WhatsApp an invoice to a registered number and see the same. They can POST an invoice through the API and get a job ID back.

## Phase 5: Billing, plans, and self-serve onboarding

**Entrance criterion:** Phase 4 complete; the product can be used end-to-end across all ingestion channels.

**Definition of done:** A new user can sign up, choose a plan, complete payment, and start using the product entirely self-serve. The Plan and FeatureFlag entities are operational. The super-admin console can edit plans, feature flags, and engine routing rules from the admin UI without code changes.

**Duration:** Roughly four weeks. Early August to early September 2026.

**Work:** The Plan entity and the configurability work per `BUSINESS_MODEL.md`. The super-admin console implementing the plan editor, feature flag editor, and engine routing rule editor. The seeding of the initial plan catalog (Free Trial, Starter, Growth, Scale, Pro, Custom) with the values from `BUSINESS_MODEL.md`.

The Stripe integration for subscription creation, payment method management, payment processing, webhook handling, and customer-invoice generation. FPX support through Stripe's local payment methods.

The signup and onboarding flow per Journey 1 in `USER_JOURNEYS.md`. The trial state, the plan upgrade flow, the payment failure recovery flow.

The customer-facing billing dashboard showing current usage, current plan, billing history, payment methods, and the customer-facing invoices ZeroKey has issued (which are themselves submitted to LHDN, closing the meta-loop).

The notification system for billing events: trial ending, payment failed, plan limit approaching, invoice ready.

The certificate upload flow for new customers, including the validation that they have a valid LHDN-issued certificate.

**Risks during this phase:** Stripe integration is well-trodden but FPX has Malaysia-specific quirks. The mitigation is to test FPX flow thoroughly with a Malaysian bank account before launch.

**Exit:** A new prospect can land on the marketing site, sign up, complete payment, upload their certificate, and start submitting invoices within the same session.

## Phase 6: Production readiness and beta launch

**Entrance criterion:** Phase 5 complete; the product is feature-complete for the SME-MVP scope.

**Definition of done:** The product is running in production with monitoring, alerting, runbooks, backup verification, security review, and a small set of beta customers actively using it. SLOs are defined and being measured.

**Duration:** Roughly three weeks. Early September to late September 2026.

**Work:** Production environment provisioning per `OPERATIONS.md`. Cloudflare configuration including WAF rules, rate limits, and bot management. The disaster recovery region configured per `DISASTER_RECOVERY.md`.

The observability stack with dashboards, alerts, and runbook links. The on-call rotation (the founder in this period) with paging configured.

A formal security review against `SECURITY.md`. Any findings are remediated before beta. Penetration testing by an external firm is scheduled.

A formal compliance review against `COMPLIANCE.md`. The privacy notice, terms of service, and other legal documents are finalized. The PDPA contact is appointed.

The first backup restore drill is conducted successfully. The first failover drill is conducted in a non-production environment.

Beta customers (10-15 friendly contacts from the founder's network, ideally from the target market) are onboarded. Their feedback shapes the final pre-GA polish.

The documentation site (`docs.zerokey.symprio.com`) is published with API reference, integration guides, and concept guides.

The marketing site at `zerokey.symprio.com` is launched with the brand identity from `BRAND_KIT.md`. The site supports English and Bahasa Malaysia at minimum; Mandarin and Tamil follow.

**Risks during this phase:** Beta feedback identifies issues that require larger work than the schedule permits. The mitigation is to triage feedback ruthlessly: must-fix-before-GA, fix-shortly-after-GA, and add-to-roadmap. The first list must remain small.

**Exit:** Beta customers are submitting invoices weekly. SLOs are being measured. No critical issues are open.

## Phase 7: General availability launch

**Entrance criterion:** Phase 6 complete; beta has produced positive feedback and no critical issues.

**Definition of done:** ZeroKey is publicly available. New customers can sign up without a beta invitation. The product is in market-ready state for the Q4 2026 pre-enforcement panic buying window.

**Duration:** Roughly two weeks of launch activities. Late September to early October 2026.

**Work:** Public announcement through the founder's channels (LinkedIn, Tamil community, BFSI network from the consulting practice, partner channels). The announcement positions ZeroKey clearly: who it is for, what it does, why it is different.

Onboarding of the first wave of paid customers from the announcement. Support for these early customers is high-touch (the founder personally onboards each one) to learn what works and what does not.

A first round of public content: blog posts about LHDN compliance, case studies (anonymized) from beta customers, comparison material against competitors. The content positions ZeroKey not as a feature list but as a stance — small, fast, calm, Malaysia-built.

Partnership conversations begin with accounting firms (Priya the bookkeeper persona's natural network), with consultancies, and with relevant ecosystem players.

A formal review of the launch metrics: signups, conversion to paid, first-week retention, support ticket volume, SLO compliance. The review identifies what to invest in next.

**Risks during this phase:** Customer acquisition might be slower than hoped. The mitigation is to have multiple acquisition channels in motion simultaneously rather than depending on any single one. Even modest customer counts in this phase teach us a lot.

**Exit:** ZeroKey has paying customers. Revenue is starting. The product is operational. The founder has a clear sense of what is working in the market.

## Phase 8: Q4 2026 capture window

**Duration:** October to December 2026.

**Work:** This is the panic-buying window for the LHDN Phase 4 enforcement deadline of 1 January 2027. The market is actively shopping for solutions. The work is to capture as much of it as possible.

Customer acquisition is the dominant theme. Marketing content scales up. Partnership channels mature. Sales conversations with mid-market prospects (Hafiz the BFSI persona's territory) intensify; the BFSI segment may not buy in this window but starts evaluating now.

Product work focuses on customer-facing pain points discovered through onboarding the first cohort. Common requests include accounting-system connectors (SQL Account, AutoCount), additional language polish (especially Mandarin and Tamil), bulk operations for customers with large historical migration backlogs, and additional API endpoints for integrators.

Operational scaling follows customer growth. Infrastructure is sized up as load grows. Support volume is monitored and any patterns are addressed through documentation, product improvements, or hiring (a part-time support contractor enters the picture if volume warrants).

A formal mid-quarter review evaluates whether the trajectory is on track for the year-end revenue and customer-count goals. Adjustments are made as needed.

**Risks during this phase:** The capture window is short. Anything that slows customer onboarding is highly damaging. The mitigation is to obsess over the onboarding flow's friction and remove every step that does not need to be there.

**Exit (end of Q4 2026):** A material number of paying customers (target depends on funnel performance and is not stated here as a fixed number). The product has demonstrated it can support real Malaysian SMEs handling LHDN compliance. The founder has data to inform 2027 planning.

## Phase 9: Q1 2027 — Post-enforcement reality

**Duration:** January to March 2027.

**Work:** With enforcement now active, customer behavior changes. The panic-buying window closes; customers who bought hastily in Q4 may discover gaps. The work is to retain them by demonstrating reliable operational quality and by addressing the gaps quickly.

Existing customers are interviewed to identify what they wish ZeroKey did. The most common requests become roadmap items.

Accounting system connectors mature into reliability. The SQL Account and AutoCount connectors graduate from beta to GA. Sage UBS follows. Each connector has its own customer base who will use it heavily.

The mid-market sales motion (Hafiz the BFSI persona, larger SMEs with formal procurement) matures. The Pro and Custom tiers see their first deals. These deals carry longer sales cycles but materially higher contract values.

A formal review of the year-one results informs year-two planning. The review covers revenue, customer count, retention, support quality, technical debt, team needs, and strategic position.

## Phase 10: Year two themes

**Duration:** April 2027 onward.

**Themes:**

**Multi-entity support** for accounting firms and customers with multiple legal entities is a P2 feature that is now P1 because customer demand has accumulated.

**Approval workflows** for finance teams that need multi-step approval chains. The data model supports this from the start; the user-facing implementation is now built.

**Custom validation rules** for customers with internal compliance requirements beyond LHDN's rules. Scale tier and above.

**Inbound invoice processing** for accounts payable teams. The MVP scope was outbound (issuer perspective); inbound processing serves a different audience and unlocks larger deals.

**Region expansion** evaluation. Singapore and Indonesia are the natural next markets. Each has its own regulatory framework (IMDA in Singapore, the new e-invoicing regulation in Indonesia). The architecture supports multi-jurisdiction; the question is whether the customer demand and operational capacity justify the expansion.

**ISO 27001 certification** is completed. The track record from year one supports the formal audit. Customer demand for the certification is by now significant.

**SOC 2 Type II** is initiated, especially if US customers are emerging.

**Team expansion** from solo to small team. The first hires are likely to be a customer success person (to handle the volume the founder cannot personally), an additional engineer (to expand product velocity), and a sales person if the mid-market motion is producing leads faster than the founder can handle.

## What is explicitly not on the roadmap

Several common SaaS features are deliberately not on the roadmap for the foreseeable future. Their absence is the result of strategic discipline.

**A mobile app** is not on the roadmap because the responsive web is sufficient for our target users and a native app is a substantial separate engineering investment. We do not yet have evidence that mobile-app users would be different enough from mobile-web users to justify the build.

**An offline mode** is not on the roadmap because Malaysian SME internet connectivity is sufficient that offline operation would primarily serve edge cases. The complexity cost is high.

**A marketplace of templates and integrations built by third parties** is not on the roadmap. Marketplace dynamics require a much larger user base to be valuable; we will not have that scale for years.

**General-purpose document automation beyond invoices** is not on the roadmap. Mission focus is a feature. We are an e-invoicing platform; we are not a document-automation platform.

**Embedded / white-label deployments** are negotiated case-by-case under Custom tier; they are not a self-serve productized offering.

These exclusions are not permanent prohibitions. They are deferments based on the current state of market evidence. As evidence changes, the exclusions are reconsidered.

## How the roadmap evolves

This document is a living plan. After every phase, it is reviewed against actual progress and updated to reflect what was learned. The next phase's plan is sharpened based on the experience of the just-completed phase.

When a customer interview reveals a need we had not anticipated, the roadmap is adjusted. When a competitive move requires acceleration of a feature, the roadmap is adjusted. When a technical discovery makes a planned approach untenable, the roadmap is adjusted.

What does not change easily is the sequence logic and the strategic direction. We do not pivot on lukewarm signals. We do change tactics constantly while protecting strategy.

When the roadmap is significantly revised, the revision date and the rationale are noted. Roadmap drift without explanation is a sign of strategic confusion; explained drift is a sign of strategic learning.
