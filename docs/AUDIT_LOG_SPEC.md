# AUDIT LOG SPEC — ZeroKey

> The immutable hash-chained audit log is the single most important compliance and trust artifact in ZeroKey. This document specifies its structure, integrity guarantees, the events it captures, the export format, and the verification procedure that lets customers and auditors prove the log has not been tampered with.

## Why the audit log is foundational

In a regulated category, the audit log is not a feature. It is the substrate on which trust rests. A customer being audited by LHDN, a BFSI procurement officer evaluating us, an enterprise security team reviewing our incident response, a customer trying to investigate an internal mistake — every one of these scenarios returns to the same question: can we prove what happened, when, and by whom.

A weak audit log means weak answers to those questions. A strong audit log means the answers are authoritative and verifiable. This document specifies the strong version.

The disciplines below are operationalized from the first commit of the codebase. The audit log is not retrofitted; it is foundational.

## Design principles

Five principles govern the audit log design, in precedence order.

The first principle is **append-only**. No event in the log can ever be modified or deleted by any authorized actor, including our highest-privileged staff. The database itself enforces this through Row-Level Security policies that deny UPDATE and DELETE on the audit table for every role except a special migration role used only during schema evolution.

The second principle is **chain integrity**. Each event references the cryptographic hash of the previous event. Tampering with any historical event would invalidate the chain from that point forward, and the invalidation is detectable by anyone with the verification key. The chain extends from the first event ever logged through the most recent.

The third principle is **completeness**. Every business-meaningful action produces an event. The criterion for "business-meaningful" is whether a customer might want to know it happened: every invoice action, every authentication event, every settings change, every staff access to customer data, every system action that affects customer state. Trivial events (a heartbeat, an internal cache refresh) do not need entries; significant events do.

The fourth principle is **per-tenant scoping with cryptographic global integrity**. Each customer has their own logical view of the log containing only their events. The chain integrity is global across all tenants — the previous-event hash referenced by any new event may be from a different tenant — so that a tenant cannot construct a valid alternative history without cooperating with every other tenant. Customers see only their own events; the integrity guarantee covers all events.

The fifth principle is **public verifiability**. The verification procedure is fully documented. The cryptographic primitives used are standard. The verification key is published. Anyone with a customer's exported audit log can verify integrity without trusting us. This is the cryptographic foundation of "you do not have to take our word for it."

## Event structure

Each AuditEvent has the following fields.

The **sequence number** is a monotonically increasing integer assigned by the database in commit order. Sequence numbers are global across all tenants. There are no gaps; every committed event has the next sequence number.

The **event timestamp** is the wall-clock time the event was committed, in UTC with millisecond precision. This is the authoritative time for the event.

The **organization reference** is the tenant context. For events specific to a customer, this references the customer's Organization. For system-level events not tied to any tenant, this is null.

The **actor** identifies who or what caused the event. Actors are typed: a `User` actor references a specific user; a `Service` actor references a system service identity (the signing service, the submission service, etc.); a `Staff` actor references an internal team member acting in their staff role; an `External` actor identifies an external system (LHDN MyInvois, Stripe, etc.) when their action triggered our event.

The **action type** is a stable string identifying what happened. Action types are namespaced: `invoice.created`, `invoice.submitted`, `invoice.validated`, `invoice.rejected`, `customer_master.created`, `auth.login_success`, `auth.login_failed`, `settings.updated`, `subscription.upgraded`, `staff.impersonation_started`, `data.exported`, etc. The full action type catalog is documented in the codebase and grows as new event categories are introduced.

The **affected entity reference** identifies the entity the action affected. For an invoice submission event, this references the Invoice. For a settings change, this references the Organization or User whose settings changed.

The **payload** is a structured JSON object describing what happened in detail. The payload schema is action-type-specific. For `invoice.submitted`, the payload includes the LHDN response code, the assigned UUID if any, the submission attempt count, and the engine route used. For `auth.login_success`, the payload includes the IP address, the user agent, and whether 2FA was completed.

The **payload schema version** is the version of the payload schema for this action type. As payloads evolve, the version advances; old events retain their original schema for verification correctness.

The **previous event hash** is the SHA-256 hash of the canonical serialization of the immediately preceding event in the global chain.

The **content hash** is the SHA-256 hash of the canonical serialization of this event's content (everything except the content hash itself). The content hash is computed at insertion time and stored alongside the event.

The **chain hash** is the SHA-256 of the concatenation of the previous event hash and this event's content hash. The chain hash is what the next event will reference. This is the recursive linkage that makes the chain tamper-evident.

The **signature** is a digital signature over the chain hash, produced by ZeroKey's audit-log signing key (a dedicated KMS-backed key separate from any customer signing key). The signature lets external verifiers confirm the chain hash was produced by the authoritative ZeroKey instance, not fabricated.

## Canonical serialization

For the chain to be verifiable, the serialization of each event must be deterministic. We use a canonical JSON serialization with the following rules.

Object keys are sorted lexicographically. Whitespace is omitted between tokens. Strings are encoded in UTF-8 with standard JSON escaping. Numbers are represented in their shortest unambiguous form. Boolean values are `true` or `false` lowercase. Null is `null`.

Floating-point numbers are not used in payloads; monetary values are decimal strings, timestamps are ISO 8601 strings, and any other numeric values are integers. This avoids floating-point representation ambiguity.

The canonical serialization rules are documented as part of the verification specification and are stable across time. A change to the serialization rules would require a new chain version and a defined transition.

## Hash and signature primitives

Hashing uses SHA-256. This is the de facto standard for tamper-evident logs and has the property that the chain remains verifiable even if SHA-256 is later weakened, because SHA-256 collisions have to be deliberately constructed and would be detectable by independent verification using stronger algorithms.

Signing uses Ed25519. Ed25519 was chosen over ECDSA for its deterministic signature property (the same input produces the same signature, simplifying verification) and its resistance to common implementation pitfalls. The signing key is held in AWS KMS as a customer-managed key; we never see the private key material.

The signing key is rotated on a defined schedule. Old signatures remain verifiable using the historical public keys, which are themselves part of the published verification material. Key rotation is itself an audit event.

## What gets logged

The complete catalog of audit events is maintained in the codebase. The high-level groupings are below.

**Identity and authentication events** include user registration, password changes, magic-link issuance and use, 2FA enrollment and changes, login successes and failures, session creations and revocations, API key creations, modifications, and revocations, SSO configuration changes, and role and membership changes.

**Customer data events** include Organization profile changes, customer master record creation, modification, and deletion, item master record creation and modification, certificate uploads and rotations, and any change to settings that affects customer-data handling.

**Invoice lifecycle events** include ingestion job creation, classification, extraction completion (including the engine used and the confidence outputs), enrichment completion, validation pass and fail, signing completion, submission to LHDN, validation response from LHDN, cancellation requests, credit and debit note issuance, and exception inbox state changes.

**Billing events** include subscription creation, modification, cancellation, plan changes, payment attempts (success and failure), refund issuance, overage charge application, and customer-facing invoice generation.

**Staff and system events** include any staff access to customer data, customer impersonation events, super-admin configuration changes (plan modifications, feature flag changes, engine routing rule changes), and any system action that affects customer state without a triggering customer action.

**Integration events** include webhook delivery attempts and outcomes, accounting connector sync runs, third-party API call failures that were customer-impacting, and similar inter-system events.

**Compliance and security events** include data exports, account deletion requests and progressions, security alerts (login from new device, suspicious activity detection), and breach-relevant events.

**Audit and infrastructure events** include audit log exports, audit log key rotations, schema migrations affecting the audit infrastructure, and chain integrity verifications run as part of routine operations.

## What does not get logged

We deliberately do not log certain things to keep the audit log focused and manageable.

We do not log read-only access by customers to their own data. The audit log captures changes and significant events; routine browsing of one's own dashboard does not need entries. The exception is data exports, which are logged because they are bulk transfers of data outside the system.

We do not log every internal cache refresh, every health check, every routine operational tick. These have their own observability surfaces.

We do not log the content of personal communications (such as full email body content of customer support exchanges); we log that the communication occurred. Content is held separately under the support ticket system with appropriate retention.

We do not log raw passwords or secret values, ever, in any form. We log that a password was changed, not what it was changed to.

## Per-tenant scoping

Each AuditEvent has an `organization` reference (or null for system events). The customer's view of the audit log is filtered to their Organization through the same Row-Level Security mechanism that scopes all customer data.

A customer can see all events that affected their Organization, including events triggered by staff acting on their data. They cannot see events for other tenants.

The chain integrity is global. Event sequence number 1,234,567 might be a different customer's invoice submission, and event 1,234,568 might be one of our customer's events; the previous-event hash on 1,234,568 references 1,234,567's chain hash. This means a customer's local view shows non-contiguous sequence numbers, and the verification procedure handles this by also serving the necessary intermediate hashes.

## Customer access to the audit log

The customer's audit log is accessible through three surfaces.

The **dashboard inspection UI** shows a chronological listing of events for the customer's Organization, with filters by date, by user, by action type, and by affected entity. Each event is presented in a human-readable form: "Wei Lun submitted invoice INV-2026-001 to LHDN at 10:23:45 on October 12, 2026."

Clicking into an event shows the full structured payload and the hash-chain metadata. Customers who care about cryptographic verification can see the previous-event hash, the content hash, the chain hash, and the signature.

The **API access** exposes the audit log through the API for programmatic consumption. Customers building their own audit dashboards or integrating with their internal compliance systems use this path.

The **export feature** generates a tamper-evident bundle for a specified date range. The bundle includes the full event sequence with all hashes and signatures, the relevant intermediate hashes from other tenants needed to verify the chain, the public keys for signature verification, and the verification specification document. The export is signed by ZeroKey's audit-log signing key as a single artifact, providing a sealed package the customer can hand to an auditor.

## Verification procedure

The verification procedure is fully documented and runnable by any third party.

A verifier receives the export bundle. The bundle's outer signature is checked against the published audit-log public key for the relevant time period.

For each event in the customer's range, the verifier reconstructs the canonical serialization, computes the SHA-256 content hash, compares it to the stored content hash, retrieves the previous event's chain hash from the bundle, computes the expected chain hash by hashing the concatenation, and compares it to the stored chain hash. Each event's signature is verified against the historical public key for the time period the event was created in.

For chain integrity across tenant boundaries, the bundle includes the necessary cross-tenant intermediate hashes (the chain hash of any event that another tenant's event references). These intermediate hashes do not reveal the content of other tenants' events; only their hashes are exposed, which by cryptographic property reveal nothing about the underlying content.

If every event verifies correctly, the customer's audit log has not been tampered with. If any event fails verification, the position and nature of the failure is reported, and the customer can escalate.

The verification specification document is published and stable. Open-source implementations of the verifier are provided so that auditors do not need to trust ZeroKey's verification tooling.

## Operational discipline around the log

Several disciplines keep the audit log honest in practice.

**Real-time chain construction** happens at event commit time. Events are inserted in commit-time order with chain hashes computed immediately. Concurrent inserts are serialized through a mutex-style mechanism so that sequence numbers are strictly ordered.

**Chain integrity verification** runs as a background job nightly across the full chain. Any verification failure is treated as a critical incident: it would mean the chain has been tampered with, which would be either an internal bug, an internal compromise, or an external attack. The response procedure is in `OPERATIONS.md`.

**Backup integrity** is maintained: the audit log is backed up with the same rigor as other production data, and backups are themselves integrity-checked. A restored audit log must verify cleanly against its known-good chain hashes.

**Storage-layer protections** include the RLS policies preventing UPDATE and DELETE, write-only IAM roles for the application, and read-only access for verification jobs. Privileged operations on the audit log infrastructure require multi-party approval and themselves produce audit events in a separate meta-log.

**Hardware-level protections** include the use of AWS KMS for the signing key (which means even ZeroKey staff cannot extract the private key) and the use of S3 with versioning and bucket lock for archived exports.

## Retention and deletion of audit events

The audit log has a longer retention than most other data. Tax-relevant events (invoice lifecycle events) are retained for the legally required seven years. Other events are retained for at least three years to support security investigations and compliance reviews.

When a customer's data is deleted (after their cancellation and the read-only retention period), their audit events face a tension: the chain integrity requires their events remain in place, but their personal data should not be retained beyond its purpose.

Our resolution is to **redact rather than delete**. After the deletion deadline, audit events for a deleted customer have their personal data fields replaced with hashed equivalents. The hash preserves the ability to verify the chain (the content hash of the original event is preserved separately) without preserving the personal data in retrievable form. The chain remains verifiable; the personal data is gone.

The redaction procedure is itself audited and is run as a deliberate background job, not on-the-fly during reads.

After the maximum retention period (seven years for tax-relevant events, three years for others), even the redacted entries are removed and the chain is rebased to maintain integrity from a new genesis point. Rebases are rare events documented and announced.

## Crypto-agility

The audit log is designed to evolve as cryptographic best practice evolves. A future version of the chain might use SHA-3 instead of SHA-256, or a post-quantum signature algorithm instead of Ed25519.

The version field in each event identifies the cryptographic suite in use. New events use the current suite; old events retain their original suite. The verification specification documents how to verify across versions. Transitions between versions are accompanied by a cutover event in the chain that establishes the new version's parameters.

This crypto-agility is not exercised lightly. The current suite (SHA-256 + Ed25519) is expected to remain valid for many years. But the architectural flexibility is in place.

## How this document evolves

When a new action type is introduced, the codebase's action type catalog is updated and this document's high-level grouping is updated if needed. When the payload schema for an action type changes, the schema version advances and the change is documented.

When the cryptographic primitives change (a future event), this document is significantly updated to reflect the new specification.

When customers ask detailed questions about audit log behavior, the answers come from this document. Our public compliance and security documentation references this document and provides a high-level summary; the full specification is here.

When the live behavior and this document diverge, one is wrong. Diverges are treated as serious findings because the audit log is the foundation of trust; documentation drift undermines verifiability claims.
