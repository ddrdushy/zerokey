# GAPS_PLAN.md

> Snapshot taken 2026-05-04, after Slice 103. Compares the documentation
> set against shipped code in `backend/apps/` + `frontend/src/`. Lists
> only the gaps that matter — P3 and Phase-6 ops scaffolding are out of
> scope for this round.
>
> This is a *living* planning doc: as slices ship, strike the line and
> reference the slice number. When the list is empty, delete the file.

---

## How this is organised

1. **Inventory** — every gap, by source document, with a one-line
   description, priority, and effort estimate (S = under 1 day,
   M = 1–3 days, L = 3+ days).
2. **Proposed slice sequence** — 11 slices that close the inventory in
   a sensible order. Each slice bundles gaps that share a layer
   (middleware, auth lifecycle, notifications, etc.) so the work
   compounds rather than scattering.
3. **Recommended next** — the first slice to take.

Anything *already shipped but mis-recorded as deferred* is called out
at the end so the BUILD_LOG can be corrected.

---

## Inventory

### From PRODUCT_REQUIREMENTS.md

| Gap | Priority | Effort |
|-----|----------|--------|
| Magic-link login | P0 | M |
| Active session review + revoke (backend) | P0 | M |
| Active sessions UI in `/dashboard/settings/security` | P0 | S |
| Login history + IP/UA capture | P0 | M |
| New-device email alert | P0 | M |
| Password reset + change flow | P0 | S |
| Help center articles + LHDN error decoder | P0 | L |
| In-product onboarding tooltips beyond the checklist | P0 | M |
| In-app notification feed (model + UI) | P0 | M |
| Outbound WhatsApp notification channel | P0 | M |
| Per-plan rate limiting | P0 | S |
| Customer master merge endpoint | P0 | S |
| Batch submission + batch-level status | P1 | M |
| Multi-entity firm-scoped dashboard | P1 | M |

### From API_DESIGN.md

| Gap | Priority | Effort |
|-----|----------|--------|
| Idempotency-Key enforcement on inbound mutations | P0 | M |
| Standardised error envelope `{error: {code, message, field, request_id, …}}` | P0 | S |
| `request_id` middleware + `X-Request-Id` echo | P0 | S |
| Cursor-based pagination class (replace per-view paging) | P0 | M |
| Rate-limit response headers (`X-RateLimit-*`, `Retry-After`) | P0 | S |
| Resource-prefixed opaque IDs (`inv_…`, `cust_…`) in serialisers | P0 | M |
| Public `AuditEvent` API resource | P1 | S |
| Public `UsageReport` API resource | P1 | S |
| Field selection (`?fields=`) | P1 | M |

### From SECURITY.md

| Gap | Priority | Effort |
|-----|----------|--------|
| Account lockout + progressive failed-login delays | P0 | S |
| File upload virus scanning (ClamAV / managed equivalent) | P0 | M |
| Session rotation on privilege escalation (2FA confirm) | P0 | S |
| Security alert templates (new device, password change, 2FA change, key created/revoked) | P0 | M |
| Account deletion / full data export self-serve | P0 | L |

(Magic-link, session review/revoke, login history overlap PRD; counted once.)

### From OPERATIONS.md

| Gap | Priority | Effort |
|-----|----------|--------|
| Sentry SDK init + DSN | P0 | S |
| Request-ID propagation through Celery + logs | P0 | S |

(Phase-6 work — Terraform, runbooks, observability dashboards, DR drill —
is out of scope for this round.)

### From INTEGRATION_CATALOG.md

| Gap | Priority | Effort |
|-----|----------|--------|
| Outbound WhatsApp Business notifications | P1 | M |
| SMS provider (Twilio) for security-critical notifications | P1 | S |

### From AUDIT_LOG_SPEC.md

| Gap | Priority | Effort |
|-----|----------|--------|
| Ed25519 signature on every event (`AuditEvent.signature` is empty today — `chain.py` says "left empty for now") | P0 | M |
| Tamper-evident export bundle (signed JSON, public keys, verification spec) | P0 | L |
| Cross-tenant intermediate-hash inclusion in customer view + export | P0 | M |
| Public verifier reference implementation | P1 | M |
| Centralised action-type catalog file | P1 | S |
| `payload_version` column on `AuditEvent` | P1 | S |
| Redact-rather-than-delete pipeline (depends on account-deletion flow) | P1 | M |

---

## Proposed slice sequence

Each slice is sized to ship in one session.

### Slice 104 — Platform hardening (S bundle)

Touches the request lifecycle once and ships several P0 items
together — biggest impact for smallest effort.

- Standardised error envelope (DRF `EXCEPTION_HANDLER`).
- `request_id` middleware + `X-Request-Id` response header +
  Celery task header propagation + log line enrichment.
- Sentry SDK init (Django + Celery + frontend).
- DRF scoped throttle (plan-tier-aware) + rate-limit response
  headers + `Retry-After` on 429.
- Account lockout via `django-axes`.
- Session rotation on 2FA confirm (`request.session.cycle_key()`).

Closes 6 P0 gaps. **Effort: M** (one good session). Depends on
nothing.

### Slice 105 — Idempotency-Key enforcement

The biggest API correctness fix. Without it, a network-level retry on
`POST /v1/invoices/{id}/submit/` can result in two LHDN submissions.

- Decorator-based dedup (Redis-backed) for inbound POST/PUT/DELETE.
- Honours request body hash so a re-used key with a different body
  errors instead of silently returning the prior response.

**Effort: M.** Depends on Slice 104 for `request_id` to log retries
coherently.

### Slice 106 — Audit log integrity (the trust story)

The "publicly verifiable" claim in AUDIT_LOG_SPEC is hollow today —
signatures aren't computed. Single biggest brand-trust win.

- Ed25519 signing in `apps/audit/chain.py:record_event` via KMS Sign.
- Centralised action-type catalog (`apps/audit/actions.py`) replacing
  scattered string literals.
- `payload_version SMALLINT DEFAULT 1` on `AuditEvent`.

**Effort: M.** Independent.

### Slice 107 — Identity quality of life

Three small fixes that share the identity surface.

- Password reset + change flow (Django built-ins, hooked into existing
  notifications).
- Active session review + revoke (`/me/sessions` endpoint +
  `/dashboard/settings/security` UI).
- Customer master merge (one service function + endpoint; the
  matching logic already exists in `apps/connectors/`).

**Effort: M.** Depends on Slice 104 (envelope + throttling).

### Slice 108 — Notifications expansion

Foundation for security alerts in Slice 109.

- In-app notification feed (model + UI feed, builds on
  `NotificationBell` shell component).
- Outbound WhatsApp Business send via existing provider adapter
  (inbound is already wired in `apps/ingestion/whatsapp.py`).
- Security alert email templates (new device, password change, 2FA
  change, API key created/revoked).

**Effort: M–L.** Independent of 107.

### Slice 109 — Magic-link + login history + new-device alerts

All three share the authentication lifecycle, so they ship together.

- Magic-link sign-in flow (token → email → consume).
- `LoginHistory` model with IP + UA capture per successful auth.
- New-device detection (UA fingerprint + IP geo) → security alert
  (uses templates from Slice 108).

**Effort: L.** Depends on Slice 108.

### Slice 110 — File upload AV scan

- ClamAV (or managed equivalent) wired into the ingestion path
  before files reach S3.
- Quarantine bucket for failed scans.

**Effort: M.** Independent.

### Slice 111 — Help center + LHDN error decoder

The largest single deliverable in the gap list. Worth the effort —
doc explicitly calls it "high marketing value".

- Help article model + admin authoring surface.
- `/dashboard/help/{slug}` reading surface (existing route is a
  placeholder).
- LHDN error code decoder: hand-curated mapping of MyInvois error
  codes → plain-language explanation + remediation steps.

**Effort: L.**

### Slice 112 — API contract polish

Closes the API_DESIGN gaps that are non-blocking but matter for the
public-API story.

- Cursor-based pagination class as the DRF default.
- Resource-prefixed opaque IDs in serialiser output.
- Public `AuditEvent` and `UsageReport` API resources.

**Effort: M.** Depends on Slice 104.

### Slice 113 — Audit export bundle + public verifier

The customer-facing trust deliverable. Pairs with Slice 106.

- Tamper-evident JSON export bundle (events + cross-tenant
  intermediate hashes + signing public keys).
- Stand-alone Python verifier (open-sourced as a separate repo).

**Effort: L.** Depends on Slice 106.

### Slice 114 — Account deletion + data export self-serve

The PDPA-aligned customer right. Last because it is large and depends
on the audit redaction pipeline being in place.

- Self-serve full-account dump (all tenant data, S3 zip).
- Self-serve deletion trigger with a 30-day cooling-off window.
- Audit redaction job (replaces deleted-customer payloads with hashed
  references; preserves chain integrity).

**Effort: L.** Depends on Slice 106.

---

## Recommended next

**Slice 104 (platform hardening).** It closes six P0 gaps in one
session, every other slice depends on at least one of its outputs
(request_id for log correlation, error envelope for the public API,
Sentry for ops visibility), and it is the smallest commitment with the
biggest immediate payoff.

After that, **Slice 106 (audit signatures)** is the highest *strategic*
priority — without it, the brand-defining trust claim ("publicly
verifiable audit chain") is not actually true. It is independent of
104 and can ship next or in parallel.

Slices 105 and 107 are the natural follow-ons after 104 because they
inherit its middleware. 108 unblocks 109. 110, 111, 112 are
parallelisable.

---

## Stale entries to correct in BUILD_LOG

Field-level PII encryption is **shipped** (Slice 95 — see
`apps/administration/fields.py:EncryptedCharField`/`EncryptedTextField`,
applied across `enrichment.CustomerMaster`, `submission.Invoice`
supplier+buyer PII, `identity.OIDCProvider.client_secret`). The
"deferred / not yet implemented" bullet for it should be removed from
the BUILD_LOG retrospective list.
