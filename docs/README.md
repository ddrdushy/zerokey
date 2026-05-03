# ZeroKey Documentation

> Operating documentation for **ZeroKey** — an enterprise-grade, SME-friendly e-invoicing platform for the Malaysian market. A product of **Symprio Sdn Bhd**, hosted at **zerokey.symprio.com**.
>
> Tagline: **Drop the PDF. Drop the Keys.**

## Read this first

If you are a human collaborator new to the project, or an AI session starting work on this codebase: **read [`START_HERE.md`](./START_HERE.md) first.** It explains how this documentation set is organized, what to load for which kinds of tasks, and the foundational context every session needs.

After `START_HERE.md`, [`PRODUCT_VISION.md`](./PRODUCT_VISION.md) sets the unmovable constitution: what ZeroKey is, who it serves, and what it stands for. No subsequent decision should contradict it.

## The full document set

Twenty-three documents organized into seven groups.

### Vision and strategy — why we are building this

| Document | Purpose |
|---|---|
| [`PRODUCT_VISION.md`](./PRODUCT_VISION.md) | The constitution. What ZeroKey is, who it serves, what it stands for, and what it deliberately does not do. |
| [`MARKET_POSITIONING.md`](./MARKET_POSITIONING.md) | The competitive landscape, the positioning frame, and how we win. |
| [`BUSINESS_MODEL.md`](./BUSINESS_MODEL.md) | Pricing, plans, the configurability principle, billing approach, and unit economics. |

### Brand and identity — how ZeroKey looks, feels, and speaks

| Document | Purpose |
|---|---|
| [`BRAND_KIT.md`](./BRAND_KIT.md) | Naming, tagline, voice, vocabulary, the ZeroKey-by-Symprio relationship. |
| [`VISUAL_IDENTITY.md`](./VISUAL_IDENTITY.md) | Color, typography, logo system, layout grammar, motion, design tokens. |
| [`UX_PRINCIPLES.md`](./UX_PRINCIPLES.md) | Fifteen ranked principles that govern every interface decision. |

### Product and features — what we are building

| Document | Purpose |
|---|---|
| [`PRODUCT_REQUIREMENTS.md`](./PRODUCT_REQUIREMENTS.md) | Capability inventory across fifteen domains. The functional scope of v1 and the staged scope beyond. |
| [`USER_PERSONAS.md`](./USER_PERSONAS.md) | The six personas: Aisyah, Wei Lun, Priya, Hafiz, Ravi, Sarah. |
| [`USER_JOURNEYS.md`](./USER_JOURNEYS.md) | Eight detailed journeys from first signup through audit response. |
| [`LHDN_INTEGRATION.md`](./LHDN_INTEGRATION.md) | The MyInvois integration: protocol, fields, validation, lifecycle. |

### Architecture and technology — how it is built

| Document | Purpose |
|---|---|
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | The system architecture: services, data tiers, deployment topology, signing isolation. |
| [`DATA_MODEL.md`](./DATA_MODEL.md) | All entities, relationships, multi-tenancy, retention. |
| [`ENGINE_REGISTRY.md`](./ENGINE_REGISTRY.md) | Pluggable AI engine architecture: capabilities, routing, fallbacks, cost tracking. |
| [`API_DESIGN.md`](./API_DESIGN.md) | REST conventions, authentication, errors, idempotency, webhooks, versioning. |
| [`INTEGRATION_CATALOG.md`](./INTEGRATION_CATALOG.md) | Every external system we integrate with, what for, and how. |

### Security and compliance — how we are trusted

| Document | Purpose |
|---|---|
| [`SECURITY.md`](./SECURITY.md) | Threat model, controls, key management, certifications, vulnerability management. |
| [`COMPLIANCE.md`](./COMPLIANCE.md) | PDPA, LHDN regulatory framework, data subject rights, retention. |
| [`AUDIT_LOG_SPEC.md`](./AUDIT_LOG_SPEC.md) | Immutable hash-chained audit log structure and verification procedure. |

### Operations and reliability — how it runs

| Document | Purpose |
|---|---|
| [`OPERATIONS.md`](./OPERATIONS.md) | Deployment, environments, observability, SLOs, on-call, runbooks, change management. |
| [`DISASTER_RECOVERY.md`](./DISASTER_RECOVERY.md) | RTO/RPO, backups, failover, testing discipline. |

### Planning and collaboration — how we move forward

| Document | Purpose |
|---|---|
| [`ROADMAP.md`](./ROADMAP.md) | Phased plan from foundation through GA and into year two. |
| [`BUILD_LOG.md`](./BUILD_LOG.md) | What has actually shipped, slice-by-slice, with durable design decisions. |
| [`GAPS_PLAN.md`](./GAPS_PLAN.md) | Living planning doc — open gaps between docs and code, sequenced into proposed slices. Delete when empty. |
| [`CLAUDE_CODE_GUIDE.md`](./CLAUDE_CODE_GUIDE.md) | How to work effectively with Claude Code on this codebase. |
| [`START_HERE.md`](./START_HERE.md) | The orientation document every session reads first. |

## Loading patterns by task type

The following patterns describe which documents to load in addition to `START_HERE.md` and `PRODUCT_VISION.md` for different kinds of work.

| If you are working on... | Also read |
|---|---|
| Strategic or product discussions | `MARKET_POSITIONING.md`, `BUSINESS_MODEL.md`, `USER_PERSONAS.md`, `USER_JOURNEYS.md` |
| Brand, marketing, or UI | `BRAND_KIT.md`, `VISUAL_IDENTITY.md`, `UX_PRINCIPLES.md` |
| Backend or architecture | `ARCHITECTURE.md`, `DATA_MODEL.md`, `API_DESIGN.md` |
| LHDN integration | `LHDN_INTEGRATION.md` |
| OCR or LLM engines | `ENGINE_REGISTRY.md` |
| External integrations | `INTEGRATION_CATALOG.md` |
| Security or compliance | `SECURITY.md`, `COMPLIANCE.md`, `AUDIT_LOG_SPEC.md` |
| DevOps, deployment, reliability, incidents | `OPERATIONS.md`, `DISASTER_RECOVERY.md` |
| Roadmap or planning | `ROADMAP.md` |
| Working with Claude Code itself | `CLAUDE_CODE_GUIDE.md` |

## Documentation discipline

Three rules govern how this set evolves.

The first rule: **documentation changes alongside code**. When a feature, entity, or convention changes, the relevant documentation is updated in the same pull request. Documentation that no longer matches the code is worse than no documentation, because it actively misleads.

The second rule: **documentation drift is a finding, not a normal state**. When a discrepancy between documentation and reality is discovered, it is treated as a bug. Either the documentation is updated (if the code is correct) or the code is brought back into alignment (if the documentation captures the intended state).

The third rule: **documentation is honest**. We do not document what we hope to do; we document what we do. Aspirational claims about controls we do not yet have, certifications we have not yet earned, or features we have not yet shipped do not appear here. The cost of an exposed exaggeration is far higher than the cost of an honest gap.

## How to extend the set

When a new dimension of the product needs durable documentation, a new document is added to this set. The criteria are: the topic is referenced from multiple places, the topic has decisions worth preserving, and the topic is stable enough that documentation will not be obsolete in weeks.

Topics that fail these criteria stay as inline comments, README notes inside specific apps, or runbooks. They do not need to be in this top-level set.

When a document grows beyond a comfortable reading length and starts covering multiple concerns, it is split. Each concern gets its own focused document with a clear purpose statement at the top.

## License and ownership

This documentation is proprietary to Symprio Sdn Bhd. It is shared with team members, AI collaborators, and select prospects under appropriate confidentiality. It is not a public specification.

Components of the documentation that are referenced in customer-facing material — privacy notice content, security page summaries, public API documentation — are derived from these documents but are presented separately at customer-facing surfaces.
