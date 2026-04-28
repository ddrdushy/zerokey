# BUILD LOG — ZeroKey

> Chronological record of what has been shipped, what works, what's deferred,
> and the design calls made along the way. ROADMAP.md describes intent;
> this document describes reality.

Current state: **Phase 1 complete, Phase 2 in flight.** Eight commits shipped.
The system boots end-to-end via `make up` and a user can sign up, drop a
PDF, and watch it auto-extract and auto-structure into LHDN-shape fields.

---

## Snapshot — what works today

A user can:

1. **Sign up** at http://localhost:3000/sign-up — atomically creates User +
   Organization + Owner Membership.
2. **Sign in** at http://localhost:3000/sign-in.
3. Land on the **dashboard** with a sidebar shell, hero card, KPI strip with
   sparklines, pipeline-throughput bar chart, compliance-posture donut, and
   a drag-and-drop file upload zone.
4. **Drop a PDF**, watch the state machine flip in real time:
   `received → classifying → extracting → ready_for_review` with one auto-chained
   `invoice.structured` event when Anthropic Claude is wired (graceful degrade
   when no `ANTHROPIC_API_KEY` is set).
5. **Click into a job** and see the structured Invoice (header / supplier /
   buyer / line-item table) plus the raw extracted text and the state-history
   timeline.
6. **Sign out** or **switch organizations**.

Behind that:

- Every business-meaningful action lands in an immutable, hash-chained audit
  log. `verify_chain()` walks the full log and rejects any tampering.
- Multi-tenancy is enforced at the database layer via PostgreSQL Row-Level
  Security on every customer-scoped table. The application connects as a
  non-superuser role so the policies actually apply.
- Extraction calls are observable per-engine — each `EngineCall` row records
  latency, cost, confidence, and outcome.
- Files live in S3-compatible storage (MinIO in dev, AWS S3 in prod via the
  same boto3 client; only the endpoint URL changes).

Operator surfaces in dev:

| URL                                              | What                                  |
| ------------------------------------------------ | ------------------------------------- |
| http://localhost:3000                            | Marketing landing + auth + dashboard  |
| http://localhost:3000/dashboard                  | Authenticated SPA                      |
| http://localhost:8000/api/v1/                    | DRF endpoints                          |
| http://localhost:8000/api/v1/schema/swagger/     | Interactive API docs                   |
| http://localhost:8000/admin/                     | Django admin (superuser required)      |
| http://localhost:9001                            | MinIO console (S3 browser)             |

---

## Slice-by-slice record

Each slice corresponds to one (or two) git commits. Numbers in parentheses are
abbreviated commit hashes.

### Slice 1 — Project skeleton + docker-compose dev stack (`d3920f6`)

What landed:

- Repo layout (`backend/`, `frontend/`, `infra/`, `docs/`).
- Django 5 monolith with eleven bounded-context apps mapped to the contexts
  in [ARCHITECTURE.md](ARCHITECTURE.md): identity, billing, ingestion,
  extraction, enrichment, validation, submission, archive, audit,
  integrations, administration.
- Settings split (base / dev / prod / test) with sqlite-in-memory for tests.
- Celery + Redis wiring; queues by priority (high / default / low / signing).
- Next.js 14 frontend with the design tokens from [VISUAL_IDENTITY.md](VISUAL_IDENTITY.md):
  Inter / Geist / JetBrains Mono, ZeroKey Ink / Paper / Signal palette,
  1.25 modular type scale, 8px spacing grid.
- Landing page assembled from [LANDING_PAGE.md](LANDING_PAGE.md) sections
  1-4, 7-8, 11-13.
- `infra/docker-compose.yml` brings up Postgres 16, Redis 7, Qdrant, the
  Django backend, two Celery workers (general + signing-only on a dedicated
  queue), and the Next.js frontend.
- Postgres init script provisions a non-superuser app role so RLS will work.

Tooling: `uv` for Python, `npm` for Node, `ruff` for backend lint/format,
`eslint`/`prettier` for frontend.

### Slice 2 — Identity domain + audit log hash chain (`3b8a075`)

Identity:

- Custom **User** model — UUID PK, email-based auth (`USERNAME_FIELD=email`).
- **Organization** — the tenant boundary; PK doubles as the RLS tenant id.
- **OrganizationMembership** — user-to-org link with role.
- **Role** + **Permission** — system-defined; the five v1 roles per
  [DATA_MODEL.md](DATA_MODEL.md).
- `TenantScopedModel` base class + `TimestampedModel` mixin.

Tenancy plumbing (`apps.identity.tenancy`):

- `set_tenant`, `clear_tenant`, `tenant_context()` context manager.
- `super_admin_context(reason=...)` — bypass via `app.is_super_admin`. The
  required `reason` argument means callers cannot omit the audit-log
  justification.
- `TenantContextMiddleware` reads `request.session["organization_id"]` and
  sets the variable for the duration of the request.
- Postgres-only; no-ops on SQLite (test backend).

Audit log:

- **`apps.audit.canonical`** — JSON canonicalization per
  [AUDIT_LOG_SPEC.md](AUDIT_LOG_SPEC.md): sorted keys, no whitespace, UTF-8,
  decimal-as-string, UUID coercion. Floats raise `FloatNotAllowedError`.
- **`apps.audit.chain`** — `content_hash = SHA256(canonical(body))`,
  `chain_hash = SHA256(prev_chain_hash || content_hash)`. `GENESIS_PREV_HASH`
  is 32 zero bytes (documented choice; spec was open).
- **`AuditEvent`** model — global gap-free sequence, `BinaryField` hashes,
  empty signature column reserved for KMS-Ed25519. `save()` and `delete()`
  refuse on the model.
- **`record_event()`** — appends one event under transaction. Every other
  context calls this; nothing else writes to `audit_event`.
- `verify_chain()` walks the log and reports tampering with the offending
  sequence number.

RLS migrations:

- `identity/0002_rls_policies.py` enables RLS + creates `tenant_isolation`
  on `identity_membership`.
- `audit/0002_append_only_rls.py` enables RLS on `audit_event` with
  separate read/insert policies; `REVOKE UPDATE, DELETE` from the app role
  so history can't be rewritten without becoming superuser.
- Both migrations Postgres-gated via `RunPython` + `connection.vendor`.

### Slice 3 — Auth flows + signal-driven audit events (`1e39593`)

Closes Phase 1's exit criterion from [ROADMAP.md](ROADMAP.md): "A user can
sign up, create an Organization, log in, and see an empty dashboard. The
audit log shows their actions in chronological order with verifiable hash
chains."

Backend:

- Seed migration — five system roles + 18 v1 permission codes; idempotent.
- `register_owner()` service — atomic User + Organization + Owner
  Membership inside one transaction. Emits three audit events in order:
  `identity.user.registered`, `identity.organization.created`,
  `identity.membership.created`. Sets the tenant variable mid-transaction
  so the membership insert passes the RLS WITH CHECK policy (registration
  is the bootstrap moment for a tenant).
- Signal handlers — `user_logged_in`/`_logged_out`/`_login_failed` →
  `auth.login_success`/`auth.logout`/`auth.login_failed`. Login-failed
  payload contains `email_attempted` but never the password.
- DRF endpoints: `register`, `login`, `logout`, `me`, `switch-organization`,
  `csrf`.

Frontend:

- `/sign-up`, `/sign-in`, `/dashboard` pages.
- `src/lib/api.ts` — typed fetch client; reads `csrftoken` cookie and
  forwards it as `X-CSRFToken` on unsafe methods. `credentials: include`
  for sessions.

### Slice 4 — IngestionJob + S3 upload (`32775aa`)

Backend:

- **IngestionJob** model with the 13-state machine from [DATA_MODEL.md](DATA_MODEL.md).
  `state_transitions` JSON column denormalizes the audit log for the review
  UI; the audit log remains authoritative.
- **`apps.integrations.storage`** — boto3 wrapper. The integration catalog was
  silent on key/bucket structure, so this module *is* the design:
  - Bucket per object class: `zerokey-uploads`, `zerokey-signed`, `zerokey-exports`
  - Key prefix: `tenants/{org_id}/{class}/{entity_id}/{filename}`. IAM
    scoping by prefix is straightforward and a misrouted object is
    structurally impossible to mistake for another tenant's.
  - 5-minute pre-signed URL TTL by default.
  - Two boto3 clients: internal one for backend↔MinIO, public one for
    signing browser-bound URLs (URLs are bound to their signing endpoint,
    so dev needs `http://localhost:9000` not `http://minio:9000`).
- `services.upload_web_file` — atomic upload: validate (25 MB cap, mime
  allowlist per [PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md)),
  `put_object`, create job, emit `ingestion.job.received` audit event.
  File goes to S3 *before* the row is created so a successful return is
  always consistent.
- DRF endpoints: `POST /upload/`, `GET /` (active org only), `GET /<id>/`.

Infra:

- MinIO + a one-shot `bucket_init` container that creates the three buckets.
- Removed `backend_venv` named volume — it was masking the image's
  `/opt/venv` with stale dep state. New deps now require an image rebuild,
  which is the standard Docker dev workflow.

Frontend:

- `DropZone` component — drag-over Signal-accent feedback (the one motion
  exception from [VISUAL_IDENTITY.md](VISUAL_IDENTITY.md)), keyboard
  fallback via the hidden file input, multi-file support.
- Dashboard wires the drop zone, lists recent uploads, KPI cards reflect
  actual job counts.

### Slice 5 — Engine registry + extraction pipeline (`daec096`)

Backend:

- **Capability ABCs** (`apps.extraction.capabilities`) — `TextExtract`,
  `VisionExtract`, `FieldStructure` with confidence + cost in their result
  dataclasses. `EngineUnavailable` raised by adapters whose deps (API key,
  library) are missing.
- **Adapters**:
  - `pdfplumber` — native PDFs, in-process, free.
  - `anthropic-claude vision` — for images / scanned PDFs (raises
    `EngineUnavailable` if `ANTHROPIC_API_KEY` unset).
  - `anthropic-claude structure` — raw text → LHDN fields (same).
- **DB-backed registry** — `Engine`, `EngineCall`, `EngineRoutingRule`.
  Engine names match adapter `name` attrs; the in-process adapter factory
  is the seam where DB rows meet code.
- **Router** — walks active rules ordered by priority, picks the first
  whose mime allowlist matches.
- **`run_extraction`** — idempotent on terminal states, transitions the
  state machine, records `EngineCall` rows, emits `state_changed` +
  `extracted/errored` audit events.
- **Worker tenant context** — extraction is a system service that processes
  every tenant's jobs. Brief-elevates to `super_admin` to look up the job,
  then `set_tenant(job.organization_id)` for the rest of the run so RLS
  filters everything to one customer.
- IngestionJob now carries `extracted_text` / `extraction_engine` /
  `extraction_confidence`; the upload service auto-enqueues extraction via
  `transaction.on_commit` so the worker never races the row insert.

Frontend:

- `/dashboard/jobs/[id]` — guarded detail page with KPI cards, extracted
  text in a monospace pre, state-history timeline, pre-signed download
  link (5-minute TTL).
- Dashboard auto-polls every 2s while any job is in flight.

Infra:

- YAML anchor `&backend-env` shared across backend + worker + signer so
  divergence (the source of "API works, worker doesn't" earlier) becomes
  structurally impossible.

### Slice 5b — Audit sequence race + dev CORS (`361b3a1`)

Two production-shaped bugs found by exercising the live stack:

**Audit sequence race.** Original advisory-lock + `MAX(sequence) + 1`
pattern raced under threaded WSGI: between lock acquisition and the SELECT,
two concurrent `record_event` calls could compute the same value and the
loser failed the unique constraint. Replaced with a single-row
`audit_sequence` counter incremented via `UPDATE … RETURNING`. Postgres
serializes UPDATEs on the same row through MVCC; the increment lives
inside the caller's transaction so a rollback un-increments naturally —
preserving the gap-free guarantee.

**Dev CORS.** `CORS_ALLOW_ALL_ORIGINS=True` forbids credentialed requests
per the fetch spec — browsers refuse `Allow-Origin: *` when the request
carries cookies. Switched to an explicit allowlist with
`CORS_ALLOW_CREDENTIALS=True` so session cookies and CSRF tokens flow
between localhost:3000 and localhost:8000.

### Slice 6 — Invoice + LineItem + auto-structuring (`1712cd7`)

Backend:

- **Invoice** model in `apps.submission` (header / supplier / buyer /
  totals / per-field confidence / submission lifecycle fields).
- **LineItem** model carrying an explicit `organization` FK for defensive
  RLS — a JOIN bug that fails to filter through Invoice can't leak rows.
- `services.create_invoice_from_extraction` (idempotent on
  `ingestion_job_id`).
- `services.structure_invoice` — calls the FieldStructure adapter, parses
  decimals stripped of "RM"/"MYR"/commas, parses dates in five formats,
  writes `EngineCall` + audit event regardless of outcome. Graceful
  degrade when the adapter is `EngineUnavailable` (e.g.
  `ANTHROPIC_API_KEY` missing) — the invoice still reaches
  `ready_for_review` with an `error_message` so the user can hand-edit.
- New Celery task `extraction.structure_invoice` on the `high` queue,
  same super-admin → set_tenant pattern as the extract task.
- Wired into `apps.extraction.services._complete`: after extraction
  succeeds, the Invoice row is created and the structuring task fires on
  commit.

Frontend:

- `/dashboard/jobs/[id]` extended with an `InvoiceCard` rendering the
  structured fields: header field grid, supplier/buyer cards (TIN +
  address), line-items table with quantity/price/tax/total columns. Empty
  state with the structuring error message when auto-structuring degraded.

### Slice 7 — Dashboard layout overhaul (`1503676`)

Replaces the single-page dashboard with a multi-zone layout — Vuexy-style
structure adapted to ZeroKey's calmer brand:

- **Persistent dark Ink sidebar** — grouped navigation (Dashboard /
  Workflow / Compliance / Settings); not-yet-built sections show a `soon`
  badge so the surface area is visibly mapped.
- **Top bar** with search, notifications icon, profile menu showing the
  active org's legal name.
- **Hero card** — first-name welcome with the italics device on the value
  phrase, Signal-accent drop motif replacing the inspiration screenshot's
  mascot illustration.
- **KPI strip** — 4 tiles (Total uploads / In flight / Validated by LHDN /
  Audit events) with per-tile mini sparklines and tone-coded icon chips.
- **2:1 chart row** — Pipeline throughput (Recharts bar chart, Ink vs
  Signal series) and Compliance posture (Recharts donut showing
  validated/needs-review/failed share with the percentage in the centre).
- Drop zone + recent uploads list integrated into the new shell.

`recharts` added (~75 KB gzipped) for the chart widgets.

---

## Architectural decisions worth preserving

These are choices made because the spec docs were silent or vague. They
should be revisited deliberately if conditions change rather than drifted
from silently.

### Audit chain

- **Genesis `previous_chain_hash`** = 32 zero bytes (documented in
  `apps/audit/chain.py`).
- **Sequence counter** lives in a dedicated `audit_sequence` row and is
  incremented via `UPDATE … RETURNING`. Race-free under concurrent writes
  in a way the original advisory-lock pattern was not.
- **No floats in payloads** — `FloatNotAllowedError` raised at canonical
  serialization time. Decimal-as-string only.
- **Signature column is empty** until KMS-Ed25519 signing lands. Schema
  exists so wiring later does not require a migration.

### Multi-tenancy

- **Per-table CREATE POLICY** rather than a parameterised global policy.
  Clearer and allows per-table customisation later (e.g. the audit table's
  read-only-with-explicit-insert pattern).
- **Defensive `organization_id` on every leaf table** including
  `LineItem` — not just at the parent's level. A JOIN bug that fails to
  filter through the parent can't leak.
- **`super_admin_context(reason=...)`** mandates a non-empty reason so the
  caller's audit log entry can never be omitted by oversight.
- **Registration sets the tenant variable mid-transaction** — registration
  is the bootstrap moment for a tenant; the membership insert needs
  `app.current_tenant_id` set to pass WITH CHECK.

### S3 / MinIO

- **One bucket per object class** (`zerokey-uploads`, `zerokey-signed`,
  `zerokey-exports`).
- **Key prefix `tenants/{org_id}/{class}/{entity_id}/{filename}`** — IAM
  scoping by prefix is trivial in production.
- **Two boto3 clients** in dev — internal endpoint for backend↔MinIO,
  public endpoint for browser-bound presigned URLs (the URL is bound to
  the host that signed it).
- **Pre-signed TTL = 5 minutes** by default.

### Engine registry

- **Capability ABCs in code, registry rows in DB.** Adapter `name` attr
  matches the `Engine.name` row so the DB is the source of truth for
  routing while code stays small.
- **`EngineUnavailable` is a first-class graceful degradation path.** When
  an adapter can't run (no API key, library missing), the calling pipeline
  records the reason and surfaces it to the UI rather than crashing.
- **No retries on `extract_invoice` / `structure_invoice` Celery tasks.**
  The pipeline is eagerly stateful; a blanket retry would skip with the
  job stuck mid-state. Real retries land later, gated on a richer
  is-it-safe-to-retry signal.

### Cross-context coupling

- **Soft FK by UUID for `Invoice.ingestion_job_id`** — service layer keeps
  the link consistent without a hard models-level coupling between
  submission and ingestion.
- **Cross-context model imports forbidden.** Other contexts call
  `apps.<context>.services`, never `apps.<context>.models`.

### Frontend

- **Tailwind tokens are semantic-over-literal** (`text-ink`,
  `bg-paper`, `bg-signal`, etc.) — components reference roles not literal
  values.
- **Recharts** (~75 KB gzipped) for charts. Picked over chart.js for
  React-native API.
- **Signal lime appears at most twice on a single screen** per the brand
  spec. On the dashboard it's the primary CTA + the drop motif.
- **No `frontend_node_modules` named volume** — it shadowed the bind mount
  with stale install state when we added recharts. Dev workflow now
  matches host installs immediately.

---

## Test surface

**Backend:** 60 passing, 4 skipped (3 Postgres-only RLS tests + 1 native-PDF
roundtrip needing reportlab). Run with `make test`.

Coverage:

- Canonical JSON serialization — byte-exactness, key sorting, decimal
  rendering, float rejection.
- Hash chain primitives — determinism, tamper detection.
- `record_event` integration — gap-free sequencing, chain linkage,
  immutability, in-DB tampering detected by `verify_chain`.
- Identity — custom user, membership uniqueness, RLS isolation
  (Postgres-only).
- Auth flow — register, login success/failure, logout, /me, switch-org.
  Each hits the audit chain.
- Ingestion upload — service-level mime/size rejection, endpoint upload,
  list isolation per active org.
- Extraction pipeline — state transitions, audit emission, EngineCall
  recording, terminal-state idempotency.
- Invoice structuring — idempotent creation, header + line-item population,
  EngineUnavailable graceful degrade, decimal parsing strips currency
  symbols, garbled JSON tolerated.

**Frontend:** typecheck + lint clean; no unit tests yet.

---

## What's deferred (and where it should plug in)

Ordered roughly by Phase 2/3 priority:

1. **Real audit-event count and throughput data** — the dashboard KPI
   "Audit events" tile and the throughput chart are placeholders. Wire to
   `AuditEvent` + `EngineCall` aggregations.
2. **Validation engine** — pre-flight checks against LHDN's 55-field rules.
   The `Invoice.status = "validating"` state exists; the actual validators
   don't.
3. **Side-by-side invoice review UI** — current detail page is functional
   but the polished review screen with PDF viewer + field-level confidence
   highlighting hasn't landed.
4. **Vision escalation on low pdfplumber confidence** — router primitive
   exists; the escalation logic that re-routes a low-confidence text
   extract through `vision_extract` doesn't.
5. **Customer master / item master** — `apps.enrichment` is empty. Per
   DATA_MODEL.md these accumulate buyer/item patterns and drive auto-fill
   on subsequent invoices.
6. **Signing service** — placeholder Celery task on the dedicated `signing`
   queue exists. KMS-backed envelope encryption + Ed25519 signature over
   `chain_hash` lands when KMS is provisioned.
7. **MyInvois submission** — placeholder Celery task exists. Real LHDN API
   client + UUID/QR retrieval + cancellation within 72-hour window.
8. **Email / WhatsApp / API ingestion channels** — only `web_upload` is
   wired. Web-upload is the most visible path; the others share the
   `IngestionJob` model and just need their adapters.
9. **Billing + Stripe + FPX** — `apps.billing` is empty; the plan/tier
   catalog from BUSINESS_MODEL.md isn't seeded.
10. **PII field-level encryption** — `Organization.contact_email`,
    `contact_phone`, `registered_address` are plain text in dev. The
    encrypted column type swaps in when KMS lands.
11. **Frontend sub-routes that show "soon" in the sidebar** — Inbox,
    Invoices, Customers, Audit log, Engine activity, Settings.
12. **CI workflow** — intentionally postponed. `.github/workflows/ci.yml`
    can wrap the existing `make test` + frontend lint/build.

---

## How to run it

```bash
cp .env.example .env
make up          # postgres, redis, qdrant, minio, backend, worker, signer, frontend
make migrate     # apply Django migrations on first boot
make test        # backend pytest suite
```

Then:

- Sign up at http://localhost:3000/sign-up (use a fresh email + TIN).
- Or sign in as the dev user: `fresh@example.com` / `long-enough-password`.
- For Django admin: `admin@zerokey.local` / `admin-dev-password`.

If extraction is hitting Anthropic and you have an API key, set
`ANTHROPIC_API_KEY` in `.env` before `make up`. Without it, extraction still
works (pdfplumber for native PDFs); only the field-structuring stage degrades
gracefully.

---

## How this document is maintained

Update this document at the end of every slice that ships. Add a new
`### Slice N — title (commit)` section describing what landed and any
durable design decisions made. Don't delete or revise old entries — the
chronological record is the value.
