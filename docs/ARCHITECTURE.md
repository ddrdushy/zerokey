# ARCHITECTURE — ZeroKey

> The system design that turns the product vision into a runnable platform. This document is the authoritative reference for what services exist, how they communicate, where data lives, and why each architectural decision was made the way it was. When the codebase and this document diverge, one of them is wrong, and we resolve it deliberately.

## Architectural philosophy

Five principles govern every architectural decision in ZeroKey, listed in precedence order.

The first principle is **boring is beautiful**. We choose mature, well-documented, widely-used technologies over novel ones unless there is a compelling reason. PostgreSQL, Django, Celery, Redis, S3, Stripe — these are tools with two decades of operational experience between them and almost no surprises left. Novelty has a cost; we only spend it where the payoff is clear.

The second principle is **vendor independence at the AI layer**. The OCR engines and language models are the most expensive, fastest-moving, and most strategically important components of our stack. We build pluggable abstractions around them so that switching a model is a configuration change, not a refactor. Lock-in to any single AI vendor is an existential risk we refuse to take.

The third principle is **enterprise-ready from the first commit**. Every architectural choice — multi-tenancy isolation, KMS-backed encryption, immutable audit logging, role-based access control — is made as if a BFSI customer might evaluate us tomorrow. We do not retrofit security; we build it in.

The fourth principle is **the simplest thing that works**. We resist the temptation to introduce sophisticated infrastructure (Kubernetes, service mesh, event sourcing, microservices for their own sake) until we have a problem that genuinely requires it. A solo founder with Claude Code as the engineering team cannot afford operational complexity that does not pay for itself.

The fifth principle is **observability is not optional**. From the first deployment, every service emits structured logs, metrics, and distributed traces. We never deploy a service we cannot debug at 2 AM during an incident.

These principles compose into a recognizable shape: a Django monolith with carefully separated subsystems, async work via Celery and Redis, S3 for object storage, PostgreSQL with Row-Level Security for multi-tenancy, KMS for cryptographic key management, a pluggable engine registry abstracting AI vendors, a Next.js frontend, and Cloudflare at the edge. This is not a unique architecture; it is the right architecture for this problem at this stage.

## The high-level shape

ZeroKey runs as a hosted SaaS platform on AWS in the Asia Pacific (Malaysia) region — `ap-southeast-5` — for data residency and latency. The choice of Malaysian hosting is deliberate: it satisfies PDPA data localization preferences, eliminates cross-border legal complexity for our customers, and reduces round-trip latency to LHDN's MyInvois platform which is also Malaysia-hosted.

The system is composed of five logical tiers. The **edge tier** handles all inbound traffic, terminating TLS, enforcing rate limits, blocking malicious traffic, and routing requests to the application tier. The **application tier** runs the Django backend and the Next.js frontend, serving every customer-facing request. The **work tier** runs Celery workers processing asynchronous jobs — extraction, signing, submission, polling, webhook delivery. The **data tier** holds PostgreSQL, Redis, Qdrant, and S3, the persistent state of the system. The **integration tier** is a thin abstraction layer where every external API call (LHDN, Stripe, Anthropic, OpenAI, Azure, etc.) is mediated through dedicated client modules with consistent retry, observability, and credential handling.

Each tier is independently scalable. The application tier scales horizontally behind a load balancer. The work tier scales horizontally based on queue depth. The data tier scales vertically initially and is partitioned later if and when single-instance limits become a constraint.

## The Django monolith

The backend is a Django 5.x application written in Python 3.12. Django was chosen over alternatives (FastAPI, Node.js, Go) for three reasons. First, Django's ORM, admin interface, migrations, and authentication system give us months of foundation work for free. Second, Django's mature ecosystem (Django REST Framework, Celery integration, django-tenants patterns) covers nearly every component we need. Third, the codebase is being built primarily by Claude Code, which has exceptional fluency in Django patterns; choosing the framework with the cleanest model-view-template-serializer separation maximizes AI engineering velocity.

The monolith is organized into bounded contexts that resemble services without being deployed as such. Each context is a Django app with its own models, views, serializers, services, and tests. The contexts are: **identity** (users, organizations, roles, sessions, SSO), **billing** (plans, subscriptions, payments, usage metering, invoices to customers), **ingestion** (file uploads, email forwarding, WhatsApp, API submissions, batch handling), **extraction** (the routed pipeline, engine registry, confidence scoring, review surfaces), **enrichment** (customer master, item master, MSIC and classification suggestion, currency conversion), **validation** (pre-flight checks, LHDN rule enforcement, error translation), **submission** (signing, MyInvois API calls, status polling, cancellation), **archive** (historical invoices, search, export), **audit** (immutable hash-chained log), **integrations** (webhooks, accounting connectors, notifications), and **administration** (the super-admin console, plan and feature flag configuration, support tools).

Each context exposes a clean service-layer interface to the others. Direct cross-context model imports are forbidden. When the extraction context needs to know about a customer, it calls `identity.services.get_customer(customer_id)`, not `from identity.models import Customer`. This discipline preserves our ability to extract any context into a separate service in the future without a months-long refactor.

The monolith deploys as a single Docker container served by Gunicorn behind Nginx (managed by the load balancer). One container image, one deployment unit. Multiple instances run behind the load balancer for horizontal scaling and rolling deployments.

## The Next.js frontend

The customer-facing web application is a Next.js 14+ application written in TypeScript. The Next.js App Router is used for its server-component model, which gives us excellent initial load performance critical for users on Malaysian mobile connections. The frontend is statically built and served from Cloudflare's CDN edge for marketing pages, and dynamically rendered for authenticated product pages.

The component library is **shadcn/ui** customized with our design tokens, as specified in `VISUAL_IDENTITY.md`. Tailwind CSS handles styling. Radix UI primitives underpin every interactive component for accessibility correctness. State management uses React's built-in primitives (useState, useReducer, Context) for component-local state, and React Query (TanStack Query) for server state. We deliberately avoid Redux and similar global state libraries; their cost exceeds their benefit for this product's complexity level.

The frontend communicates with the Django backend exclusively through a versioned REST API, detailed in `API_DESIGN.md`. There is no direct database access from the frontend, no shared types compiled across the boundary, no code generation that ties the two together. The boundary is contractual, defined by OpenAPI schemas, and treated as the seam where we could replace either side independently.

Multilingual content is handled through Next.js's internationalization routing, with translations stored in JSON files per language and managed through a translation management system as the volume grows. The four launch languages — English, Bahasa Malaysia, Mandarin, Tamil — are each first-class with their own translator review.

## Asynchronous work with Celery and Redis

Most of the interesting work in ZeroKey is asynchronous. Extraction takes seconds; LHDN submission takes seconds to minutes; webhook delivery may take milliseconds or may need retries over hours. The customer should not wait synchronously for any of this.

The async work tier is **Celery** with **Redis** as the broker and result backend. Celery was chosen because it is the de facto standard for Python async work, has mature retry, scheduling, and chaining capabilities, and integrates cleanly with Django. Redis was chosen as the broker because it doubles as our caching layer and our session store, simplifying our infrastructure.

The work tier runs as a separate set of containers from the application tier, scaled independently based on queue depth. Different queues serve different priorities: a high-priority queue for customer-facing operations like extraction and submission, a medium-priority queue for periodic jobs like reference data refresh and scheduled customer reports, and a low-priority queue for batch operations and analytics.

Every task is idempotent by design. Tasks accept a job identifier, check if the job is already complete, perform their work atomically, and record completion. Retries do not duplicate effects. This is enforced through a discipline of designing every task as "compute the next state of this entity given the current state" rather than "perform this side-effect."

The retry strategy uses exponential backoff with jitter for transient failures (network errors, rate limits) and surfaces persistent failures to the operations dashboard for human inspection. Dead-letter queues capture jobs that exhaust their retry budget; these are never silently dropped.

## The data tier

The data tier consists of four distinct stores, each chosen for the type of data it holds.

### PostgreSQL

PostgreSQL 16+ is the primary system of record. Every entity in the application — users, organizations, plans, invoices, line items, customer master records, audit log entries — lives in PostgreSQL. The reasoning is simple: we need ACID guarantees, mature tooling, and rich query capability, and PostgreSQL has been the right answer for these requirements for two decades.

The schema is normalized to third normal form for transactional data, with carefully designed indexes for the access patterns we know about and full-text search indexes on customer-searchable text fields. Detailed schema documentation lives in `DATA_MODEL.md`.

Multi-tenancy is implemented through **PostgreSQL Row-Level Security (RLS)**. Every customer-scoped table has a `tenant_id` column, an RLS policy attached, and a session variable that the Django connection sets at the start of each request to the authenticated user's tenant. Queries that do not match the tenant are silently filtered to zero rows by the database itself. This makes it cryptographically difficult to leak data across customers even in the presence of application-level bugs. The RLS approach is detailed in `DATA_MODEL.md` and `SECURITY.md`.

PostgreSQL is hosted on **Amazon RDS** with a primary in `ap-southeast-5a` and a synchronous read replica in `ap-southeast-5b` for high availability. Backups are automated, encrypted, and retained per the policy in `DISASTER_RECOVERY.md`.

### Redis

Redis serves three purposes: as the Celery broker (already discussed), as the caching layer for hot reference data and computed query results, and as the session store for authenticated user sessions.

The cache layer holds the MSIC catalog, the classification code list, the UOM list, the country code list, recently-verified TINs, recent currency exchange rates from Bank Negara Malaysia, and computed query results that are expensive to recompute (such as a customer's monthly compliance dashboard summary). Cache keys are namespaced by domain, every cached value has a TTL, and cache invalidation is explicit on writes that affect cached data.

Redis is hosted on **Amazon ElastiCache** with a primary and replica configuration for high availability. Persistence is enabled to survive restarts; we treat Redis as durable enough for sessions and Celery state but not as authoritative for any business data — that always lives in PostgreSQL.

### S3

Amazon S3 holds all binary objects: original uploaded invoices (PDFs, images, Excel files), generated signed XML documents, audit log archive bundles, customer-uploaded brand assets, and exports.

S3 is structured into prefix-namespaced buckets with strict access policies. Each customer's objects live under a tenant-prefixed key path; access is gated through pre-signed URLs generated by the Django backend with short expiration windows. Direct customer access to S3 is never permitted.

Object lifecycle policies move older invoice originals to S3 Infrequent Access after 90 days and to S3 Glacier Deep Archive after one year, dramatically reducing storage costs while preserving retrievability for audits. The lifecycle policies respect each customer's plan retention period; objects are not deleted while within the customer's retention window.

S3 is configured with bucket-level encryption using KMS-managed keys, versioning enabled to protect against accidental deletion, and server access logging to a separate audit bucket for forensic capability.

### Qdrant

**Qdrant** is the vector database used for semantic search workloads, primarily the MSIC code suggestion and item master matching. Qdrant was chosen over alternatives (Pinecone, Weaviate, pgvector) for three reasons. First, it is open-source and self-hostable, removing a vendor dependency. Second, it has excellent Python client support and is operationally simple. Third, Dushy has prior production experience with Qdrant from the Tamil music RAG and chat system projects, and that experience compounds.

Qdrant runs on a small EC2 instance in the same VPC as the application tier. Embeddings are generated using a multilingual embedding model accessed through the engine registry (so we can switch embedding providers without disrupting the rest of the system). The MSIC catalog is embedded once and re-embedded on monthly catalog refresh; customer-specific item master embeddings are computed on item creation and updated on item correction.

The Qdrant index is treated as derivative — it can be fully rebuilt from PostgreSQL state at any time. Qdrant is not the system of record for anything; it is the index that makes semantic search fast.

## The engine registry

The engine registry is the architectural component that delivers our pluggable AI vendor strategy. It is documented in detail in `ENGINE_REGISTRY.md`, but its place in the overall architecture is worth describing here.

Every interaction with an OCR engine or a language model goes through the engine registry. The registry exposes a small number of capability interfaces — `text_extract`, `vision_extract`, `field_structure`, `embed`, `classify` — and any number of registered engines that fulfill those capabilities. Each engine is a thin adapter around a specific vendor's API: Azure Document Intelligence, AWS Textract, Google Document AI, Anthropic Claude, OpenAI GPT, Google Gemini, Mistral, local PaddleOCR, local Tesseract, etc.

The routing logic that picks an engine for a particular job is data-driven, not hardcoded. Configuration lives in PostgreSQL and is editable from the super-admin console. Routing rules consider the job type, the file characteristics, the customer's plan tier, the engine's current health and cost, and explicit per-customer overrides for deals where a customer requires a specific engine (such as a BFSI customer who requires AWS-only).

Engines are versioned and observable. Every engine call records latency, cost, success status, and confidence outputs to a metrics store. This produces real per-engine quality and cost data over time, allowing routing rules to be tuned based on evidence rather than vendor claims.

## The signing service

The signing service is architecturally distinct from the rest of the application even though it deploys as part of the same monolith. The reason is custodial: this service handles customer digital certificates, the most sensitive material in our system.

The signing service runs in an isolated process within the work tier, on dedicated worker containers that do not run any other workload. It receives signing requests from the submission context as Celery tasks. Each request includes the invoice payload to sign and the identity of the customer. The signing service retrieves the customer's certificate from S3 (where it is stored as an envelope-encrypted blob), decrypts the envelope key using KMS (which logs the access), uses the certificate to apply the digital signature according to LHDN's specifications, returns the signed payload to the submission context, and immediately discards the decrypted certificate from process memory.

The signing service has read-only S3 access scoped only to the customer-certificates prefix and KMS decrypt access scoped only to the certificate envelope key alias. It has no database access. It has no internet access except to KMS. The blast radius of a compromise of the signing service is bounded by these controls.

Detailed cryptographic and key management architecture is in `SECURITY.md`.

## The integration tier

Every external API call from ZeroKey goes through a dedicated client module in the integrations context. This is not just a coding convention; it is an architectural enforcement. There is no `requests.get()` scattered throughout the codebase. Every external call is made through a typed client module with consistent retry logic, circuit breaking, observability, and credential handling.

The clients we maintain include: an LHDN MyInvois client (the most important), a Stripe client (billing), engine clients (one per AI vendor, exposed through the engine registry), an SMTP client (email), a WhatsApp Business API client (notifications and ingestion), a Slack client (internal alerting), an SSO client per provider (Okta, Microsoft Entra, Google), accounting connector clients (SQL Account, AutoCount, Sage UBS), and a Bank Negara Malaysia exchange rate client.

Each client logs every request and response (with sensitive values redacted) to a centralized audit log. Each client emits metrics for latency, success rate, and error class. Each client respects the external service's rate limits and surfaces rate limiting cleanly back to the calling context. Each client implements a circuit breaker that opens after sustained failures and closes after a verified recovery, preventing cascading failures when an external service is degraded.

## The edge tier

All traffic to ZeroKey enters through **Cloudflare**. Cloudflare provides DNS, TLS termination, DDoS protection, web application firewall (WAF), bot management, and CDN caching for static assets.

The WAF is configured with the OWASP Core Rule Set as a baseline and supplemented with ZeroKey-specific rules that block known attack patterns against Django, common credential-stuffing tools, and aggressive scrapers. Rate limits are applied per-IP and per-customer, with tighter limits on authentication endpoints and payment-related endpoints.

The CDN layer caches the marketing site, static product UI assets, and public help center articles. Authenticated product pages are not cached at the edge.

Behind Cloudflare, traffic enters the AWS region through an Application Load Balancer that terminates internal TLS, performs health checks against application tier instances, and routes requests to healthy targets. The load balancer also performs path-based routing: API requests go to one set of containers, web page requests go to another, allowing them to be scaled and tuned independently.

## Authentication and authorization

Authentication is handled by Django's built-in authentication framework extended for our needs. Customer users authenticate with email and password (with mandatory two-factor authentication option), magic-link login as an alternative, and SAML/OIDC SSO for Pro tier and above. Sessions are stored in Redis with secure httpOnly cookies and CSRF protection.

Authorization is implemented as a role-based access control (RBAC) system. Each user has a role within their organization (Owner, Admin, Approver, Submitter, Viewer); each role has a set of permissions; each protected operation declaratively requires specific permissions. The permission model is enforced at the service layer, not at the view layer, so that any code path reaching a protected operation goes through the same gate.

Multi-tenancy is enforced both at the application layer (the user's tenant context is set on every request from their authenticated session) and at the database layer (PostgreSQL RLS filters every query to the tenant). The two layers are independent; an application bug that fails to filter by tenant would still be caught by the database. This belt-and-suspenders approach is critical for a system handling regulated data.

API keys for the API ingestion channel are first-class authentication credentials with their own scopes and audit trails. API keys can be scoped to specific operations (for example, "submit invoices but not read customer master") and can be rotated and revoked from the customer's settings.

## Observability

The observability stack is built on three pillars: logs, metrics, and traces.

Structured logs are emitted by every service in JSON format and shipped to a centralized log aggregation platform. Initially this is **AWS CloudWatch Logs** for cost simplicity; as scale demands, it can be upgraded to **Datadog**, **Honeycomb**, or a self-hosted **OpenSearch** stack. Logs include the request ID, the user ID, the tenant ID, the operation, and the outcome, allowing any incident to be reconstructed minute-by-minute.

Metrics are emitted using the OpenTelemetry standard and shipped to **AWS CloudWatch Metrics** initially, with the same upgrade path. Critical metrics include request latency by endpoint, queue depth by Celery queue, extraction latency by engine, MyInvois submission success rate, payment success rate, and resource utilization across the application and work tiers. Dashboards are maintained for every service.

Distributed traces are emitted using OpenTelemetry and exported to whatever the tracing backend is at the time. Traces follow a customer request from edge through application, into Celery work, through external API calls, and back. When something is slow, the trace tells us where.

Alerting routes critical conditions to a paging channel (PagerDuty initially, or a comparable service). Alerts are tuned to be high-signal: an alert means a human needs to look. Noisy alerts are systematically retired or downgraded to warnings. The on-call rotation in the founding period is the founder; as the team grows, a proper rotation is established.

Detailed observability requirements and the runbook structure are in `OPERATIONS.md`.

## Configuration management

Application configuration falls into three categories with three different lifecycles.

**Code-level configuration** is in version control. The list of bounded contexts, the wiring of services, the structure of the codebase — these are decisions changed through pull requests.

**Infrastructure configuration** is in version control as Terraform modules. The list of AWS resources, the network topology, the IAM policies, the RDS instance class — these are decisions changed through Terraform plan-and-apply with approval gates.

**Operational configuration** is in PostgreSQL and editable from the super-admin console. Plans, pricing, feature flags, engine routing rules, customer-specific overrides — these are decisions changed through admin actions, with full audit logging. This is the configurability principle from `BUSINESS_MODEL.md` made architecturally concrete.

The boundary between these categories is deliberate. A pricing change must not require a code deploy. A new engine must not require an infrastructure change. A new feature must not require a database migration just to flag it on for one customer.

## Deployment topology

Production deployments use **Docker** containers orchestrated by **AWS ECS on Fargate**. Fargate was chosen over Kubernetes for the same reason boring is beautiful: at our current scale, Fargate's operational simplicity dramatically outweighs Kubernetes's flexibility. The migration path to ECS-on-EC2 or to EKS exists if and when we need it.

The application tier runs as one ECS service with auto-scaling based on CPU utilization and request rate. The work tier runs as separate ECS services per queue priority, scaling on queue depth. The signing service runs as a dedicated ECS service with stricter network isolation. The Qdrant instance runs on a single EC2 host (since vector search is stateful and benefits from local disk).

Deployments are blue-green: a new version is deployed alongside the current version, traffic is shifted gradually from current to new with health checks confirming each step, and rollback is a one-click reversal of the traffic shift. Database migrations are designed to be backwards-compatible across at least one version, allowing rolling deployments without downtime.

The deployment pipeline is automated through GitHub Actions: on merge to the main branch, the application is tested, packaged, and deployed to a staging environment for smoke tests, then promoted to production with manual approval. Hotfix deployments can bypass staging if marked as urgent and approved by the founder.

Detailed environment, deployment, and incident procedures are in `OPERATIONS.md`.

## Backup and disaster recovery

The architecture is designed to satisfy a recovery time objective of four hours and a recovery point objective of one hour. PostgreSQL has automated continuous backups and point-in-time recovery within the past thirty-five days, with daily snapshots retained for one year. S3 is replicated across availability zones with versioning enabled. Redis is replicated with persistence enabled but is treated as recoverable from PostgreSQL state (sessions are reset on a Redis loss; Celery in-flight jobs are re-enqueued).

A second AWS region (`ap-southeast-1`, Singapore) is configured as a warm standby for disaster recovery scenarios where `ap-southeast-5` is unavailable. Failover is documented and tested quarterly. Detail in `DISASTER_RECOVERY.md`.

## What the architecture is not

We deliberately do not have a microservices architecture. The cost of operating multiple services for a solo team exceeds the benefit of independent scaling, which we do not need.

We deliberately do not have a service mesh, an event-sourced data store, or a CQRS read-write split. These add operational complexity that is not justified at our scale. We will adopt them if and when our scale demands it, not as a hedge against scaling problems we do not have.

We deliberately do not run our own Kubernetes cluster. Fargate is enough.

We deliberately do not maintain a polyglot codebase. The backend is Django/Python; the frontend is Next.js/TypeScript; that is enough complexity for one team.

We deliberately do not build our own LLM, OCR engine, or payment processor. We integrate with vendors whose business it is to be excellent at these things, and we use the engine registry to maintain optionality.

## How this document evolves

When an architectural decision is made — a new service is introduced, an existing service is split, a vendor is changed, an infrastructure pattern is adopted — this document is updated as part of the same pull request that implements the decision. An architecture change without a document update is rejected at code review.

When this document and the production system diverge, the divergence is treated as a bug. Either the document is updated to reflect the new reality (if the change was intentional), or the system is changed to match the documented architecture (if the divergence was accidental).

When a future engineer or AI collaborator joins this codebase, this document plus `DATA_MODEL.md`, `ENGINE_REGISTRY.md`, `API_DESIGN.md`, and `SECURITY.md` form the architectural mental model they need to be productive. Together they describe a system that is small enough to understand and serious enough to trust with regulated workloads.