# CLAUDE.md

> This file is the entry point for Claude Code on the ZeroKey codebase. It is read first in every session and points you to the right documentation for the task at hand.

## Project overview

You are working on **ZeroKey** — an enterprise-grade, SME-friendly e-invoicing platform for the Malaysian market. ZeroKey ingests invoices in any format (PDF, image, Excel, email, WhatsApp, API), extracts and validates them, signs them with the customer's LHDN-issued certificate, submits them to LHDN MyInvois, and tracks their lifecycle.

ZeroKey is a product of **Symprio Sdn Bhd** and is hosted at `zerokey.symprio.com`. The tagline that defines the product is **"Drop the PDF. Drop the Keys."**

The product is being built solo by Dushy with you (Claude Code) as the primary engineering collaborator. The documentation in `docs/` is the operating system that keeps every session aligned.

## What to do at the start of every session

Read these two files first, in this order:

1. [`docs/START_HERE.md`](./docs/START_HERE.md) — the orientation document explaining how the documentation set is organized.
2. [`docs/PRODUCT_VISION.md`](./docs/PRODUCT_VISION.md) — the constitution. What we are building, who we serve, what we stand for.

Then load additional documentation based on the task. The loading patterns are in `START_HERE.md` and in [`docs/README.md`](./docs/README.md).

## Where to find what you need

The full documentation set is in `docs/`. The master index is [`docs/README.md`](./docs/README.md). The high-level groupings:

- **Vision and strategy** — `PRODUCT_VISION.md`, `MARKET_POSITIONING.md`, `BUSINESS_MODEL.md`
- **Brand and identity** — `BRAND_KIT.md`, `VISUAL_IDENTITY.md`, `UX_PRINCIPLES.md`
- **Product and features** — `PRODUCT_REQUIREMENTS.md`, `USER_PERSONAS.md`, `USER_JOURNEYS.md`, `LHDN_INTEGRATION.md`
- **Architecture and tech** — `ARCHITECTURE.md`, `DATA_MODEL.md`, `ENGINE_REGISTRY.md`, `API_DESIGN.md`, `INTEGRATION_CATALOG.md`
- **Security and compliance** — `SECURITY.md`, `COMPLIANCE.md`, `AUDIT_LOG_SPEC.md`
- **Operations and reliability** — `OPERATIONS.md`, `DISASTER_RECOVERY.md`
- **Planning and collaboration** — `ROADMAP.md`, `CLAUDE_CODE_GUIDE.md`

## Conventions you should always follow

These are the non-negotiable conventions for this codebase. They are detailed in [`docs/CLAUDE_CODE_GUIDE.md`](./docs/CLAUDE_CODE_GUIDE.md); the highlights:

**Read the documentation before writing code.** The temptation to skip ahead is strong. Resist it. The few minutes spent loading the right context save hours of drift.

**Match conventions, do not invent new ones.** Naming, file organization, error handling, and testing patterns are all established. Read existing similar code before adding new code; match its style.

**Tests are not optional.** Every change has tests. Bug fixes have a regression test for the bug. Features have tests covering the happy path and the major error paths.

**Documentation changes alongside code.** When you change a behavior, update the relevant documentation file in the same change. Drift between code and docs is a bug.

**Multi-tenancy isolation is enforced at the database layer.** Every customer-scoped table has a Row-Level Security policy. Never use a `bypass-RLS` shortcut except in the specific places that need it (super-admin operations, platform analytics).

**Sensitive data is never logged.** Passwords, certificates, API keys, full PII — never. The logging filter has a redaction allowlist; respect it. Adding sensitive data to logs is a security incident.

**The audit log is foundational.** Every business-meaningful action produces an audit event. The chain integrity is cryptographically verified. Never modify or delete an existing audit event from application code.

**The customer's signing keys are not our keys.** Customer signing certificates live in KMS-encrypted blobs in S3. The signing service decrypts them in-memory only for the duration of a signing operation. We are custodians, not owners.

## Stack at a glance

- **Backend:** Django + Django REST Framework, Celery + Redis for async work, PostgreSQL with Row-Level Security for multi-tenancy.
- **Storage:** S3 (with KMS envelope encryption for sensitive blobs), Qdrant for vector search.
- **Frontend:** Next.js + TypeScript, shadcn/ui as the component system, Tailwind CSS.
- **Infrastructure:** AWS in `ap-southeast-5` (Malaysia) with disaster recovery in `ap-southeast-1` (Singapore). ECS Fargate for compute. Cloudflare at the edge.
- **Engines:** Pluggable registry. Azure Document Intelligence (primary OCR), Anthropic Claude (primary LLM), with fallbacks to AWS Textract, Google Document AI, OpenAI GPT, Mistral, Gemini, and self-hosted PaddleOCR.
- **Payments:** Stripe with FPX support for Malaysian customers.

Architecture details are in [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).

## When in doubt

When you encounter a decision the documentation does not clearly answer:

1. Re-read the relevant documentation more carefully — the answer is often there.
2. Check whether `PRODUCT_VISION.md` or `UX_PRINCIPLES.md` provides the foundational principle that points to the answer.
3. Surface the question to Dushy explicitly rather than making the choice silently. Drift starts with silently-made decisions that nobody else sees.

When you find documentation that is wrong or outdated:

1. Note it explicitly.
2. Either update it in the same change you are making, or open a tracking issue if the update is larger than the current scope.

## Getting started checklist

Before you write any code in a new session:

- [ ] Read `docs/START_HERE.md`
- [ ] Read `docs/PRODUCT_VISION.md`
- [ ] Read the task-relevant documents per the loading pattern
- [ ] Read `docs/CLAUDE_CODE_GUIDE.md` if this is your first session on the codebase
- [ ] Confirm you understand what done looks like for the task

Then build.
