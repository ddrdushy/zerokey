# START HERE — ZeroKey Documentation Index

> **For every Claude Code session: read this file first, then load the docs relevant to your current task.**

---

## What is ZeroKey?

ZeroKey is an enterprise-grade, SME-friendly e-invoicing platform for the Malaysian market. It connects Malaysian businesses to LHDN's MyInvois system through the simplest possible workflow — drop an invoice in any format, and ZeroKey handles extraction, enrichment, validation, signing, submission, and status tracking automatically.

ZeroKey is a product of **Symprio Sdn Bhd**, an established consulting and automation firm with offices in Malaysia, Singapore, India, and the United States. The product is hosted at **zerokey.symprio.com**.

The tagline that defines the product: **Drop the PDF. Drop the Keys.**

The first phrase speaks to users — drop your invoice, we do the work, no keystrokes required. The second phrase speaks to security buyers — drop your signing keys to us, but we never actually hold them; they live in hardware-backed key management infrastructure (KMS/HSM), not in our database.

## Why these documents exist

ZeroKey is being built solo by Dushy with Claude Code as the primary engineering collaborator. In a solo build, documentation is not optional reference material. It is the operating system that keeps every coding session aligned with the same vision, architecture, and standards. Without it, an AI engineer drifts. With it, every session compounds.

This documentation set is therefore the foundation that every Claude Code session loads context from. It is written for two audiences simultaneously: a human founder who needs strategic clarity, and an AI collaborator who needs unambiguous specification.

## How to use this documentation

When you (Claude Code, or any future collaborator) start a session, follow this loading pattern.

For any session, always read this file (`START_HERE.md`) and `PRODUCT_VISION.md` first. These set the unmovable foundation of what we are building and why.

For strategic or product discussions, also read `MARKET_POSITIONING.md`, `BUSINESS_MODEL.md`, `USER_PERSONAS.md`, and `USER_JOURNEYS.md`.

For brand, marketing, or UI work, also read `BRAND_KIT.md`, `VISUAL_IDENTITY.md`, and `UX_PRINCIPLES.md`.

For backend or architecture work, also read `ARCHITECTURE.md`, `DATA_MODEL.md`, and `API_DESIGN.md`.

For LHDN integration work, also read `LHDN_INTEGRATION.md`.

For OCR or LLM engine work, also read `ENGINE_REGISTRY.md`.

For security, compliance, or audit-related work, also read `SECURITY.md`, `COMPLIANCE.md`, and `AUDIT_LOG_SPEC.md`.

For DevOps, deployment, reliability, or incident response work, also read `OPERATIONS.md` and `DISASTER_RECOVERY.md`.

For roadmap or planning discussions, also read `ROADMAP.md`.

For working with Claude Code itself on this codebase, read `CLAUDE_CODE_GUIDE.md`.

## Documentation set

The complete documentation set consists of twenty-three files organized into seven groups.

**Vision and strategy** establishes the why behind ZeroKey. It contains `PRODUCT_VISION.md`, `MARKET_POSITIONING.md`, and `BUSINESS_MODEL.md`.

**Brand and identity** defines how ZeroKey looks, feels, and speaks. It contains `BRAND_KIT.md`, `VISUAL_IDENTITY.md`, and `UX_PRINCIPLES.md`.

**Product and features** specifies what we are building. It contains `PRODUCT_REQUIREMENTS.md`, `USER_PERSONAS.md`, `USER_JOURNEYS.md`, and `LHDN_INTEGRATION.md`.

**Architecture and technical foundation** describes how the system works. It contains `ARCHITECTURE.md`, `DATA_MODEL.md`, `ENGINE_REGISTRY.md`, `API_DESIGN.md`, and `INTEGRATION_CATALOG.md`.

**Security and compliance** establishes the trust foundation that lets us sell into BFSI and enterprise. It contains `SECURITY.md`, `COMPLIANCE.md`, and `AUDIT_LOG_SPEC.md`.

**Operations** covers how we run the system reliably. It contains `OPERATIONS.md` and `DISASTER_RECOVERY.md`.

**Build and roadmap** plans the path from today to a fully launched product. It contains `ROADMAP.md` and `CLAUDE_CODE_GUIDE.md`.

## Core principles that override everything

When in doubt during any decision — code, design, copy, contract terms — return to these.

ZeroKey serves Malaysian SMEs first. Every feature is judged by whether a non-technical SME owner in Kuala Lumpur, Penang, Johor Bahru, or Kuching can use it without help. If they cannot, we redesign until they can.

ZeroKey is enterprise-grade from day one. Even though the user-facing experience targets SMEs, the underlying platform is built to BFSI standards. This is a deliberate dual posture, not a contradiction. The simple front sells; the serious back retains.

ZeroKey holds nothing it does not need to hold. Customer signing keys live in KMS, never in our database. PII is encrypted at the field level. Document retention follows configurable policies. The principle of least data is a product feature, not just a security control.

ZeroKey is pluggable at the AI layer. OCR engines and LLM engines are interchangeable behind a common interface. We are not locked to any vendor. As models improve and prices drop, we route to the best engine for each job. This is a structural advantage, not just a technical preference.

ZeroKey learns from every correction. Every time a user fixes a misread field, the system gets better at that field for that customer next time. The longer a customer uses ZeroKey, the higher the switching cost — not from contracts, but from accumulated intelligence.

ZeroKey is honest about what it does. We never claim to be certified by LHDN unless we are. We never imply legal protection we do not provide. We surface failures, not hide them. Trust, once lost in this category, does not come back.

## How to evolve these documents

These documents are versioned with the codebase. When a decision changes, the relevant document is updated in the same pull request as the code change. Documentation drift is treated as a bug.

When a new doc needs to be created, it is added to this index, and `START_HERE.md` is updated to reference it.

When a contradiction between documents is discovered, it is resolved by escalating to `PRODUCT_VISION.md`. That document is the constitutional layer; everything else is statute.

## Contact and ownership

ZeroKey is owned and operated by Symprio Sdn Bhd. All commercial decisions, contracts, and customer relationships flow through Symprio. The product team is led by Dushy, the founder of the ZeroKey product line within Symprio.