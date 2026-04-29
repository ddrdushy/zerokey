# BUILD LOG — ZeroKey

> Chronological record of what has been shipped, what works, what's deferred,
> and the design calls made along the way. ROADMAP.md describes intent;
> this document describes reality.

Current state: **Phases 1–4 complete, Phase 5 in flight.** Customer can sign
up, drop a PDF (or forward an email), watch it extract, review the
extracted fields, submit it to LHDN MyInvois (sandbox or production), get
back a QR-verifiable Valid status, and issue Credit / Debit / Refund
notes against it. Stripe self-serve checkout is wired. The system boots
end-to-end via `make up`.

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

### Slice 8 — Real dashboard data (audit stats + throughput)

Replaces the two remaining placeholders on the post-Slice-7 dashboard with
real aggregations sourced from the authoritative tables:

- **`GET /api/v1/audit/stats/`** — `apps.audit.services.stats_for_organization`
  rolls up the active org's `AuditEvent` rows into `total`, `last_24h`,
  `last_7d`, and a 7-day gap-filled `sparkline`. System events
  (`organization_id IS NULL`) are excluded so the customer's tile shows
  their own activity, not platform housekeeping. RLS already filters
  `audit_event` by tenant; the explicit `organization_id` filter is
  belt-and-suspenders per convention.
- **`GET /api/v1/ingestion/throughput/?days=7`** —
  `apps.ingestion.services.throughput_for_organization` buckets
  `IngestionJob` rows by `upload_timestamp` date over a configurable
  window (clamped 1–90, default 7), splitting each bucket into
  `validated` and `review` (`ready_for_review` + `awaiting_approval`)
  for the chart's two series. The window also produces totals for
  `validated`, `review`, `in_flight`, `failed`, and `uploads` so the
  chart and any future summary line reconcile.
- **Frontend** — `api.auditStats()` and `api.throughput()` clients added.
  Dashboard now fetches both alongside `listJobs` on mount and on each
  poll tick, replaces the `jobs.length * 4 + 5` proxy on the Audit
  events tile with the real total + a sparkline driven by the API
  series, replaces the `PLACEHOLDER` data on `ThroughputChart` with
  the real 7-day series, and pipes a per-day uploads sparkline into
  the Total uploads tile as a side benefit.
- The post-upload `onUploaded` callback now triggers a full
  `refreshDashboardData` so a fresh upload visibly bumps both the KPI
  tile and the chart on the next paint, not just the recent-uploads
  list.

The day-bucketing uses `TruncDate("upload_timestamp")` /
`TruncDate("timestamp")` and gap-fills server-side. Cross-DB compatible
(SQLite for tests, Postgres for dev/prod) — no `date_trunc` raw SQL
needed.

Tests: 14 new (5 service + 4 endpoint per side) covering happy-path
counts, cross-tenant isolation, window filtering, gap-fill behavior,
the `days` query-param clamp, and that totals reconcile with the
per-day series. Suite is now 74 passing / 4 skipped.

Verified live against the running stack: registered a fresh org and
confirmed both endpoints return the expected shape; the audit stats
report 4 events for the registration flow on today's bucket and the
throughput series renders an empty 7-day window correctly.

### Slice 9 — Vision escalation on low pdfplumber confidence

Closes the Phase 2 exit criterion gap from
[ROADMAP.md](ROADMAP.md): "reasonable extraction quality on a scanned
PDF". Per [ENGINE_REGISTRY.md](ENGINE_REGISTRY.md) line 91 — "scanned
PDFs and images go to … a confidence threshold below which the result
is escalated to vision" — the router now enacts that contract.

Backend:

- **Vision adapter handles PDFs natively.** `ClaudeVisionAdapter` now
  dispatches its content block by mime: `application/pdf` becomes a
  Claude `document` block, `image/*` keeps the existing `image` block,
  anything else raises `EngineUnavailable`. The adapter still satisfies
  exactly one capability (`VisionExtract`); the change is just "what
  shape of input do we accept". Logic isolated in
  `_document_block(body, mime_type)` so the dispatch is unit-testable
  without standing up the full Anthropic client.
- **`run_extraction` adds a post-extract escalation step.** After the
  primary text engine succeeds, if its confidence is below
  `EXTRACTION_VISION_THRESHOLD` (default 0.5, configurable via
  settings), the pipeline picks a `VISION_EXTRACT` engine for the same
  mime type and re-sends the original bytes. On vision success, the
  `StructuredExtractResult` is written straight to the Invoice via
  the newly-public `apps.submission.services.apply_structured_fields`
  — the FieldStructure step is short-circuited because vision already
  returned the same shape of fields.
- **Three audit events frame the escalation.**
  `ingestion.job.vision_escalation_started` records the trigger
  (primary engine, primary confidence, threshold);
  `ingestion.job.vision_escalation_skipped` records every non-fatal
  miss (no route, adapter missing, EngineUnavailable, vendor failure);
  the existing `ingestion.job.extracted` event is enriched with
  `primary_text_engine` / `primary_text_confidence` / `vision_engine`
  when vision applied, so the audit trail makes the escalation
  honest rather than hiding it behind the combined engine name.
- **Job's `extraction_engine` becomes `pdfplumber+anthropic-claude-sonnet-vision`**
  when escalation applies, and `extraction_confidence` carries the
  vision overall confidence (which is the more meaningful signal once
  vision has applied). When escalation is skipped, the row looks
  identical to the pre-slice path.
- **`_apply_structured_fields` was renamed to `apply_structured_fields`**
  and given a docstring. It's the convergence point that both the
  FieldStructure path and the vision path now flow through, so the
  Invoice + LineItem rows look identical regardless of which engine
  produced them.

Tests: 7 new (4 escalation behaviors + 3 mime-dispatch cases). The
graceful-degrade contract is exercised explicitly: low confidence →
no vision route → audit-logged skip; low confidence → vision raises
`EngineUnavailable` → audit-logged skip + `EngineCall` row with
`unavailable` outcome + Invoice left in `EXTRACTING` for the regular
FieldStructure task to finish. Suite is now 81 passing / 4 skipped.

Verified live: uploaded a text-layer-free PDF (the scanned-PDF
trigger). pdfplumber returned 0.1 confidence; the escalation fired
and the vision adapter raised `EngineUnavailable` (no
`ANTHROPIC_API_KEY` in dev). Audit chain shows the
`vision_escalation_started` and `vision_escalation_skipped` events
linked into the chain; `EngineCall` row recorded with `unavailable`
outcome and the right diagnostic; the job still reached
`ready_for_review` cleanly. Setting the API key is the only remaining
step to see the full vision-applied path.

Deferred (worth flagging):

- **Threshold is global.** ENGINE_REGISTRY.md anticipates per-tenant
  and per-document-class thresholds; this slice ships one number.
  When per-customer routing rules land, the threshold migrates onto
  the rule alongside the engine choice.
- **No PDF page rendering.** We pass the original PDF bytes straight
  to Claude (which handles them natively). For very-large or
  multi-page invoices we may want to render selected pages to images
  instead — measurable once we have real cost data.
- **No vision retries.** `EngineCall` outcomes record the fail mode;
  a retry budget alongside the existing fallback chain is the next
  improvement, paired with the cost-aware routing flagged in
  ENGINE_REGISTRY.md.
- **Calibration.** ENGINE_REGISTRY.md spec calls for per-engine
  confidence calibration; we still trust raw vendor confidences.
  Calibration tables are a Phase 3 follow-up.

### Slice 10 — DB-backed runtime config (Engine credentials + SystemSetting)

Moves rotatable secrets out of `.env` and into a DB-backed store the
super-admin can edit at runtime (per ROADMAP.md Phase 5: "the
super-admin console implements the plan editor, feature flag editor,
and engine routing rule editor"). The data model lands now; the
dedicated UI is still a Phase 5 surface, but the Django admin already
exposes both new tables so a fresh deployment can rotate keys today
without touching `.env`.

The line drawn:

- **Stays in `.env`** — anything needed at process boot (settings
  module, `DJANGO_*`, Postgres / Redis / Qdrant connection strings,
  `POSTGRES_APP_*`, `NEXT_PUBLIC_API_BASE_URL`, AWS/KMS root creds,
  `KMS_KEY_ALIAS`). Self-evident — you can't read settings out of a
  DB you haven't connected to yet.
- **Moved to DB** — per-engine vendor credentials (Anthropic, Azure,
  OpenAI) and platform-wide integration credentials (LHDN, Stripe).
  These are exactly the values ENGINE_REGISTRY.md and BUSINESS_MODEL.md
  spec as super-admin-rotatable.

Backend:

- **`Engine.credentials` JSONField** — per-engine vendor credentials
  live on the existing `extraction.Engine` row. Migration
  `extraction/0003_engine_credentials.py`. The Django admin Engine
  editor exposes the field in a "Credentials" fieldset with a notice
  about KMS-encryption status (plaintext today; envelope-encrypted
  when the signing service brings KMS online).
- **`apps.administration.SystemSetting`** — single-row-per-namespace
  table for platform-wide integrations. The `values` JSON dict
  carries the namespace's keys; the namespace itself is the unit of
  edit (super-admin updates "LHDN credentials" as a set, not one key
  at a time). Migration `administration/0001_initial.py`. Registered
  in Django admin.
- **`apps.extraction.credentials.engine_credential` /
  `require_engine_credential`** — the resolver every adapter calls
  instead of `os.environ.get`. Lookup order: `Engine.credentials[key]`
  → `os.environ[env_fallback]` → `None` (or `EngineUnavailable` for
  the `require_*` variant). Empty strings fall through to env so a
  cleared field in the UI doesn't silently leave the system
  unconfigured.
- **`apps.administration.services.system_setting` /
  `require_system_setting` / `upsert_system_setting`** — same
  resolver shape for platform-wide values, plus an atomic upsert
  that emits an `administration.system_setting.updated` audit event
  whose payload lists affected key names but **never the values**
  themselves.
- **Claude adapter wired through the resolver.** `_client()` now
  takes the calling engine's name and calls `require_engine_credential(
  engine_name=..., key="api_key", env_fallback="ANTHROPIC_API_KEY")`.
  Both the vision and structure adapter rows can carry independent
  keys (per ENGINE_REGISTRY.md's "customers maintain separate vendor
  accounts per use case" note) but typically share one. No other
  adapters use external credentials yet, so this is the only call site.

`.env.example` and `.env` reorganised into two sections — required
boot values vs. optional bootstrap fallbacks for DB-managed secrets.
Each fallback variable is documented with the DB row it falls back
from. `.env` had no values filled in locally, so the rewrite is safe.

Tests: 17 new (8 SystemSetting, 9 engine credentials including a
direct adapter-reads-resolver regression test). Suite is now 98
passing / 4 skipped.

Verified live: applied both new migrations on the running stack;
wrote a `lhdn` SystemSetting row and an `Engine.credentials.api_key`
row via super-admin context; confirmed the resolver returns the DB
value over the env value, and falls back to env when the DB row is
cleared.

Durable design decisions:

- **Resolver lives at each context's seam, not in a single shared
  module.** `extraction.credentials` for per-engine,
  `administration.services` for platform-wide. The two have the
  same shape but they answer different questions, and merging them
  would couple the contexts.
- **Empty string is "not set"**, not "explicitly cleared". The
  super-admin clearing a field in the UI is the same operation as
  not having configured it yet — both fall through to env. No
  three-way "unset/empty/cleared" tri-state.
- **Audit payload lists affected keys, never values.** The audit log
  is the LAST place credentials should leak. The upsert service
  enforces this structurally.
- **Plaintext today, KMS-encrypted later.** The encryption swap is
  a single migration when KMS provisions; the resolver call sites
  don't change. Documented in the migration and on each model.
- **Two anthropic engine rows can carry different keys.** The
  resolver looks up by `Engine.name`, not vendor. ENGINE_REGISTRY.md
  anticipates BFSI customers wanting separate accounts per use case;
  this preserves that future without forcing it today.

### Slice 11 — Validation engine (Phase 3 entry)

Closes the Phase 3 entrance criterion's first half — pre-flight LHDN
rules running on every structured Invoice before signing/submission.
This is the "we caught it before LHDN did" UX promise from
`PRODUCT_VISION.md` finally on the chain. Per
`LHDN_INTEGRATION.md` the validation engine is the gate between
extraction/structuring and signing; this slice puts that gate in
place, with 15 rules covering the categories that don't need
external API calls.

What landed:

- **`apps.validation.ValidationIssue`** — one row per finding.
  Severity (`error` / `warning` / `info`), stable `code`, `field_path`
  (e.g. `supplier_tin`, `totals.grand_total`, `line_items[2].quantity`),
  plain-language `message`, and a `detail` JSONField for the
  expandable "technical details" the UI shows on demand. Tenant-scoped
  with the standard per-table CREATE POLICY pattern; defensive
  `organization` FK so a JOIN-bug can't leak issue text across
  tenants.
- **`apps.validation.rules`** — pure-function rule registry. Each
  rule takes a hydrated Invoice (line items prefetched) and returns
  zero or more `Issue` records. 15 rules in this slice:

  Required-fields rules — `required.invoice_number`, `required.issue_date`,
  `required.currency_code`, `required.supplier_legal_name`,
  `required.supplier_tin`, `required.buyer_legal_name`,
  `required.line_items`, `buyer.tin.missing` (warning, not error —
  B2C uses an LHDN placeholder).

  Format rules — `supplier.tin.format`, `buyer.tin.format` (loose
  pattern match for individual / corporate TIN; live LHDN
  verification is a follow-up that needs the LHDN client),
  `currency.format` / `currency.unsupported` (ISO 4217),
  `currency.precision` (JPY/KRW/VND/IDR are zero-decimal; others
  two-decimal), `supplier_msic_code.format` /
  `buyer_msic_code.format` (5-digit; catalog match is a follow-up),
  `buyer.country.format` (ISO 3166-1 alpha-2).

  Date rules — `dates.issue_in_future`, `dates.due_before_issue`
  (errors); `dates.due_in_past` (warning).

  Arithmetic rules — `line.subtotal.mismatch`, `line.total.mismatch`
  (1-cent tolerance per LHDN spec); `totals.subtotal.mismatch`,
  `totals.tax.mismatch`, `totals.grand_total.mismatch` (1-ringgit
  tolerance per invoice).

  Threshold rule — `rm10k.invoice_threshold`, `rm10k.line_threshold`
  (info, not error — the rule changes consolidation eligibility,
  doesn't block submission). MYR-only for now; foreign-currency
  thresholds wait for BNM exchange-rate wiring.

  Consistency rules — `sst.no_tax_on_registered_supplier`
  (warning), `invoice_number.duplicate` (error, scoped within the
  supplier's namespace per LHDN's "unique within supplier sequence"
  spec).

- **`apps.validation.services.validate_invoice(invoice_id)`** — the
  one entry point. Replaces the prior issue set atomically (re-runs
  don't accumulate duplicates), emits exactly one
  `invoice.validated` audit event whose payload reports counts and
  fired-rule codes but **never message text** (messages can carry
  user-visible field values; codes are safe). Returns a
  `ValidationResult` summary with per-severity counts so callers can
  decide whether to proceed.

- **Pipeline hook**: `apps.submission.services.apply_structured_fields`
  now runs `validate_invoice` inline after writing the Invoice +
  LineItems. Inline rather than queued because the rule set is
  pure regex/arithmetic running in milliseconds, and the review UI
  needs the issue list on the same response that shows the
  structured fields. The graceful-degrade path
  (`_finalize_without_structuring`) also runs validation so a
  fresh empty invoice still surfaces the required-field errors
  honestly.

- **API surface**: the Invoice serializer gained `validation_issues`
  (full list) and `validation_summary` (`{errors, warnings, infos,
  has_blocking_errors}`) method fields. One round-trip serves the
  review UI; no separate "fetch issues" call needed. Cross-context
  service-only import (`apps.validation.services` from
  `apps.submission.serializers`) per ARCHITECTURE.md.

- **Frontend**: `ValidationIssue` and `ValidationSummary` types
  added to `frontend/src/lib/api.ts` so the future review UI
  (Slice D) can render them without further wiring. The detail
  page already fetches the Invoice; issues now arrive on the same
  payload.

Tests: 50 new (45 per-rule unit tests + 5 dispatcher integration
tests). The per-rule tests assemble a fully-clean baseline invoice,
mutate one field per test, and assert that the right code fires (and
the noise stays quiet). Tolerance edges are tested explicitly —
1-cent line wobble doesn't trip; 1-ringgit invoice wobble doesn't
trip; anything outside does. Service tests cover atomic replacement
on re-run, audit payload contents (codes yes, messages no), and
cross-tenant isolation. Suite is now 143 passing / 4 skipped.

Verified live: applied both validation migrations; created a
deliberately-broken invoice (bad TIN + arithmetic mismatch);
`validate_invoice` returned 2 errors, 0 warnings, 0 infos with the
expected codes (`supplier.tin.format`, `totals.grand_total.mismatch`)
and the audit chain picked up the `invoice.validated` event.

Durable design decisions:

- **One-rule-one-function with a flat list registry.** Rules are
  pure, side-effect-free, easy to test in isolation. Adding a rule
  is "write a function, append to RULES, write tests" — the
  contract is mechanically obvious.
- **Severity levels match LHDN's posture, not ours.** ERROR =
  blocks submission; WARNING = advisory; INFO = awareness only.
  A rule's severity reflects what LHDN does with the violation,
  not how we feel about it.
- **Codes are stable; messages are not.** The audit log keeps
  codes (and counts), the front-end translation layer keys off
  codes. Rule messages are English copy that gets edited freely
  without breaking anything.
- **Re-run idempotency via delete-then-bulk-create.** Simpler than
  a diff/upsert, and validation is fast enough that the wasted I/O
  doesn't matter. If the invoice list grows, we revisit.
- **Inline validation in the structuring path, not a separate
  task.** Fast rules + UI needs the data on the next paint. We'll
  promote to a queued task only when external-API rules
  (live LHDN TIN verify, BNM exchange rates) make the call slow.
- **Audit log carries codes, never message text.** Messages can
  carry user-visible PII (TIN values, addresses). Codes never can.
  This is the "don't put credentials in audit logs" principle
  applied to validation findings.

What's deferred (and should be obvious next moves):

- **Live LHDN TIN verification** — the format rule passes "looks
  like a TIN"; the API confirms the TIN actually exists. Same
  shape, just routed through `apps.administration` for the LHDN
  credentials.
- **MSIC / classification / UOM catalog matching** — needs the
  cached LHDN catalogs landed (a separate slice that fetches and
  refreshes them monthly).
- **Foreign-supplier / self-billed / consolidated B2C** — the
  rule plumbing here will host the special-case rules when the
  scenarios get explicit pipeline support.
- **MYR-equivalent threshold** for foreign-currency invoices —
  needs BNM exchange-rate wiring.

### Slice 12 — Side-by-side review UI + extraction-finalize fix

Closes the Phase 2 polish gap. The detail page is now a proper
review surface: source PDF on the left, structured fields on the
right with per-field confidence dots and per-field validation issue
pills, all anchored by a top-of-pane validation banner. Layout
stacks on mobile (< lg) and is sticky-side-by-side on desktop so
the document stays visible while the reviewer scrolls fields.

Frontend (new components, all in `frontend/src/components/review/`):

- **`DocumentPreview`** — native rendering only. PDFs get an
  `<iframe>` with `#toolbar=0&navpanes=0` and a no-scripts sandbox;
  images get an `<img>` with `object-contain`; everything else
  falls back to a "use Open" placeholder. Zero dependencies — we
  don't pay the ~500 KB pdfjs cost until we actually need page-
  level controls (zoom, page nav, annotations).
- **`ValidationBanner`** — top-of-pane summary that explains
  posture rather than just declaring numbers (UX_PRINCIPLES
  principle 4: "errors are explained, not announced"). Three tones
  driven by `validation_summary`: red ("This invoice is not ready
  to submit"), warning ("Ready to submit — with notes to review"),
  success ("Looks good to submit").
- **`FieldRow`** — label + value + confidence dot + inline
  IssuePills. The confidence dot is always visible when
  `per_field_confidence[field]` exists (UX_PRINCIPLES principle 7:
  uncertainty signaled clearly); thresholds match the vision-
  escalation cutoff (>= 0.8 success, >= 0.5 warning, < 0.5 error)
  so the reviewer's mental model lines up with the engine's.
- **`IssuePill`** — small badge keyed by severity. Compact mode for
  in-table pills; full mode for inline-with-field pills. Tone
  derives from semantic tokens so a future theme change updates
  everything.
- **`LineItemsTable`** — rebuilds the existing table with per-line
  issue matching (`field_path` of the form `line_items[N].<field>`)
  + a tinted issue row underneath any line that has findings.

Page refactor (`frontend/src/app/dashboard/jobs/[id]/page.tsx`):

- Two-column layout (`grid lg:grid-cols-[1fr_1fr]`). Document pane
  is `lg:sticky lg:top-6` so it stays in view while the right pane
  scrolls.
- Right pane: `ValidationBanner` → Header → Parties → Totals →
  Line items → orphan issues (any `field_path` we don't render
  explicitly), with the existing State history and Raw extracted
  text relegated to collapsible `<details>` at the bottom. Polling
  cadence preserved (2s while non-terminal).

Backend (one fix exposed by live verification):

- **`finalize_invoice_without_structuring` is now a public service.**
  Renamed from the leading-underscore private form and given a
  docstring. The extraction context calls it directly when text is
  empty AND vision didn't apply — previously the pipeline only
  queued FieldStructure when `text.strip()` was truthy, so empty-
  text + vision-unavailable left the Invoice stuck in `EXTRACTING`
  forever with no validation issues. The review banner then
  falsely reported "looks good to submit" on a totally empty
  invoice. Fix routes the empty case to the public finalize
  function which runs validation, surfacing the required-field
  errors honestly. New regression test pins the behaviour.

Tests: 1 new backend regression test + 1 existing test rewritten
to assert the corrected post-finalize state. Suite is now
144 passing / 4 skipped. Frontend bundle for the detail route
went 6.66 KB → 9.24 KB (no new dependencies — just the new
components).

Verified live with Playwright: registered a fresh user via the
sign-up form, dropped the synthetic empty-PDF fixture into the
upload zone, the job reached `ready_for_review` in 2 seconds,
the review screen rendered with a red banner reporting "6 errors
must be fixed before LHDN will accept this invoice", 6 issue pills
inline next to the empty required-field rows, 1 warning pill on
buyer TIN, and the document preview pane on the left. Screenshot
confirms the visual hierarchy (`/tmp/sliceD-review.png` during
local development).

Durable design decisions:

- **Native PDF rendering via `<iframe>`, not pdfjs.** The bundle
  cost of pdfjs (~500 KB) is the kind of dependency that doesn't
  pay off until we need annotation overlays or page-level scroll
  sync between document and fields. We don't, yet. When we do, we
  swap the implementation behind the same `DocumentPreview`
  component contract.
- **Confidence thresholds match the vision-escalation cutoff.**
  >= 0.8 / >= 0.5 / < 0.5 → success / warning / error. Reviewers
  see the same boundary the engine sees, so a "warning yellow"
  field is one that *would* have triggered escalation if it
  hadn't already been escalated.
- **`field_path` is the join key between rules and UI.** The
  rules module emits paths like `supplier_tin`, `totals.grand_total`,
  `line_items[2].quantity`. The page maintains a `FIELD_PATHS` set
  of paths it explicitly renders; anything outside that set lands
  in the "Other issues" stack so nothing gets lost. New rules can
  ship without touching the UI.
- **Public `finalize_invoice_without_structuring`.** Pipelines
  that produce structured invoices come from multiple paths
  (vision short-circuit, FieldStructure adapter, no-structuring
  fallback). Each path has to terminate in the same finalized
  state with validation having run. The convergence point is now
  a public service rather than a private detail of one path.

What's deferred (UI-only, the data is there):

- **Per-field confidence color tints** (the dot is there; tinting
  the field background by confidence band is a polish pass).
- **Sticky validation summary** as the reviewer scrolls past it
  on a long invoice.
- **Edit-in-place** for fields, with re-validation on save —
  needs a `PATCH /invoices/<id>/` endpoint (Phase 3 follow-up).
- **Approve & submit** primary action — gated on the signing
  service landing.

### Slice 13 — Login-after-register RLS fix

A real bug surfaced by the side-by-side review work: existing dev
credentials (`fresh@example.com`, `slice8@example.com`,
`sliceA@example.com`) couldn't log in and view their own data.
`/me` returned `memberships: []` and `active_organization_id: null`,
leaving the dashboard stuck on "No active organization".

**Root cause** — `apps.identity.services.memberships_for(user)` is a
fundamentally cross-tenant query: its job is to answer "which
tenants can this user act for?", which is exactly the question we
ask *before* a tenant context is set (during login, during /me when
the session has no active org yet, during organization-switch). The
RLS policy on `identity_membership` filters every row out when
`app.current_tenant_id` is empty, so the lookup returned zero rows.
Registration worked because `register_owner` runs in
`super_admin_context`; login didn't, because the helper ran with
no tenant on the connection.

The unit tests passed because the test backend is SQLite
(no RLS); only Postgres-backed dev / prod manifested the bug.

Fix: both `memberships_for` and `can_user_act_for_organization`
(the access check used by `switch_organization`) now wrap their
queries in `super_admin_context`. The elevation is narrowly scoped
to the read query and never leaks to the caller; the docstrings
explain *why* this is the right level of authority for those
specific lookups (cross-tenant by design, not by accident).

Tests: 1 new Postgres-only regression test in
`apps/identity/tests/test_tenancy.py` that simulates the login
moment — clears the tenant variable, calls `memberships_for`, and
asserts it returns the user's memberships. Also covers
`can_user_act_for_organization` (positive + negative cases).
Suite still 144 passing on SQLite; the 5 Postgres-only tests
require `DJANGO_SETTINGS_MODULE=zerokey.settings.dev`.

Verified live against the running stack: logged in as
`sliceA@example.com`, `/me` returned the membership and
`active_organization_id`, `/api/v1/ingestion/jobs/` returned the
existing jobs. Previously these all returned empty.

Durable design decisions:

- **Cross-tenant lookups belong in `super_admin_context`.** The
  rule of thumb: if the question is "which tenant should I be
  scoped to?", the lookup that answers it cannot itself be tenant-
  scoped. Same principle that registration relied on; just hadn't
  been applied to the login path.
- **Postgres-only tests run under `settings.dev`, not the default
  test settings.** Adding a Postgres-fixture to the default test
  config would slow the suite for no benefit on the SQLite path.
  The tradeoff: bugs that only manifest on Postgres need
  conscious effort to catch. The fix here is to write a
  Postgres-gated test — they accumulate, and CI eventually runs
  them as a separate matrix entry.

### Slice 14 — Customer + item master (enrichment)

`apps.enrichment` finally does work — the empty bounded context that's
been sitting next to `extraction` and `validation` since Phase 1.
Closes the foundational gap behind the "every correction makes the
system smarter" promise from PRODUCT_VISION.md and the switching-cost
strategy in BUSINESS_MODEL.md.

What landed:

- **`CustomerMaster`** model — one row per known buyer per Organization.
  Carries the canonical legal name + a JSON list of learned aliases,
  the buyer's TIN with verification state (LHDN-API integration is
  the next slice), and the full identifier set
  (registration_number / msic_code / address / phone / sst_number /
  country_code) plus `usage_count` + `last_used_at`. Unique
  `(organization, tin)` constraint with a partial index on non-empty
  TINs (B2C / pre-LHDN buyers without TINs aren't deduped at the DB
  layer; the alias-name match handles them).
- **`ItemMaster`** model — one row per known item description.
  `canonical_name` + aliases list, default codes
  (`default_msic_code` / `default_classification_code` /
  `default_tax_type_code` / `default_unit_of_measurement`), advisory
  `default_unit_price_excl_tax` (Decimal), and `usage_count`.
- **RLS migrations** for both tables, per-table CREATE POLICY pattern
  matching the rest of the codebase.
- **`enrich_invoice(invoice_id)`** service — the convergence point.
  Customer match strategy: by TIN (exact) first, then by legal name
  (case-insensitive) against canonical or any learned alias, then
  create. Same shape for ItemMaster keyed off the line description.
  Auto-fill is **strictly additive** — never overwrites a non-empty
  value the LLM produced — because the LLM saw the actual document
  and the master is weaker per-invoice evidence. When a field is
  auto-filled, its `per_field_confidence` is set to `1.0`, so the
  review UI's three-band scheme renders it as the highest-confidence
  green dot ("from your verified master, not a fresh extraction").
- **Pipeline hook**: `apps.submission.services.apply_structured_fields`
  now calls `enrich_invoice` *before* `validate_invoice`. Order
  matters: validation sees the post-enrichment field set, so a
  master-filled `buyer_address` doesn't trip the
  "buyer_address is missing" warning. The graceful-degrade path
  (`finalize_invoice_without_structuring`) also runs enrichment so
  even an empty extraction gets one shot at master auto-fill.
- **Audit**: `invoice.enriched` event with counts (customer_matched
  / customer_created / items_matched / items_created /
  fields_autofilled list) and the customer master row id. **No buyer
  name in the payload** — buyer names are PII; an audit reader
  reconstructs what changed by following the master id, not by
  reading the name.

Tests: 14 new (5 customer-master, 3 auto-fill semantics, 4 item-master,
2 audit + cross-tenant isolation). Coverage of the contract every
other context relies on: first-time create, repeat-buyer increment,
case-insensitive name match including alias learning, no-overwrite
of populated values, blank-description skip, no buyer-name in audit
payload, cross-tenant isolation. Suite is now 158 passing /
5 skipped.

Verified live against the running stack: first invoice for a new
buyer created a master with `usage_count=1`; second invoice (same
TIN, blank address) matched the existing master, auto-filled
`buyer_address` from the master to "42 Jalan Sample" with
`per_field_confidence['buyer_address']=1.0`, and bumped
`usage_count` to 2. ItemMaster matched one line on repeat. The
master count stayed at 1 — no duplication.

Durable design decisions:

- **Auto-fill is strictly additive — LLM evidence wins.** The LLM
  read the source document; the master is a pattern from prior
  invoices. On a per-invoice basis, the LLM's evidence is stronger
  unless the user explicitly corrects it. Master only fills blanks.
- **Legal name is never auto-filled.** The LLM read SOME name from
  the document; silently swapping it for the master's canonical
  would change what the user sees vs. the source. Address, TIN,
  MSIC, etc. are auto-filled because those are pattern-stable;
  the visible name is not.
- **Confidence 1.0 on master-filled fields** signals to the review
  UI that the value didn't come from a fresh extraction. The user
  reading the green dot understands "this is from your verified
  master" without us having to add a separate visual treatment.
- **TIN match wins over name match.** TIN is the LHDN-issued
  identifier; names drift (LLM emits variants, customers
  rebrand). The alias list is a catch-all for when TIN is absent
  (B2C, pre-LHDN buyers).
- **Master backfill is bidirectional.** When a new invoice matches
  an existing master, the master also learns blank fields from the
  invoice — not just the invoice from the master. Three invoices
  in, the master has the union of every field the LLM has ever
  extracted for that buyer.
- **No buyer-name in the audit payload.** Audit events list what
  changed by master id; PII never enters the chain. Same principle
  as Slice 11 (codes-not-messages).
- **Idempotent re-runs**: the validate-then-edit flow can re-trigger
  enrichment safely. Auto-fill is no-op when fields are filled;
  alias learning de-dupes on insert.

What's deferred (and where it should plug in):

- **Manual correction → master update**. The "user fixed the master's
  default code" feedback loop needs an `ExtractionCorrection`
  emitter on Invoice edits + a master-update consumer.
  `PATCH /invoices/<id>/` endpoint is the prerequisite (Phase 3
  follow-up).
- **Frontend customer / item master pages.** The data is rich
  enough now to power a "frequent customers" view + per-customer
  editing. Sidebar already shows the "Customers" route as `soon`.
- **Live LHDN TIN verification** populates
  `tin_verification_state` / `tin_last_verified_at` on master
  rows. Credentials are already in the `lhdn` SystemSetting from
  Slice 10.
- **Smarter buyer matching** (fuzzy/Levenshtein, embeddings) when
  exact + alias matches start missing recurring buyers. Premature
  today; revisit when we see the miss patterns in production.

### Slice 15 — Edit + save: closing the correction feedback loop

The review screen (Slice 12) was read-only; every field shown was
extraction output and the user had no way to fix it. The masters
(Slice 14) couldn't learn from corrections because there were no
corrections to learn from. This slice puts both halves on the chain:
fields are editable in place, Save runs the full re-pipeline, and
buyer corrections propagate to the matched CustomerMaster.

Backend:

- **`PATCH /api/v1/invoices/<id>/`** accepts a partial update payload
  shaped against a strict allowlist (``EDITABLE_HEADER_FIELDS``).
  Anything outside that set raises a 400 — an attacker (or a bug)
  can't flip ``lhdn_uuid`` / ``status`` / ``signed_xml_s3_key`` /
  ``raw_extracted_text`` via this endpoint. A dedicated test pins
  the allowlist's omissions.
- **`update_invoice` service** does five things in one transaction:
  applies edits with type coercion (decimals tolerate "RM 1,234.56",
  dates accept ISO 8601 or DD/MM/YYYY), bumps ``per_field_confidence``
  to 1.0 for each changed field (matches the master-autofill
  convention so the review UI's confidence dot is consistent across
  both signals), emits a single ``invoice.updated`` audit event whose
  payload lists field NAMES but never values (PII), pushes buyer
  corrections to the matched CustomerMaster, and re-runs
  ``enrich_invoice`` + ``validate_invoice`` so the response carries
  fresh issues against the new field set.
- **Master propagation**: a corrected ``buyer_msic_code`` /
  ``buyer_address`` / etc. **overwrites** the matched master's
  corresponding column. This is the deliberate inversion of the
  enrichment rule (which never overwrites) — user corrections are
  the strongest evidence we have, stronger than any LLM output the
  master previously absorbed. If the user renames the buyer, the
  previous canonical name is filed as an alias before being
  overwritten so the match history is preserved.

Frontend:

- **`FieldRow` is dual-mode.** Read mode (no `onChange` prop) renders
  static text; edit mode (`onChange` provided) renders an inline
  `<input>` with the same visual frame. The dirty marker (a
  Signal-tinted dot labelled "Edited") replaces the confidence dot
  when a field has unsaved edits, so the reviewer's attention shifts
  from "how sure are we" to "you've changed this, save". `kind="date"`
  switches to the native date picker; `kind="decimal"` stays on text
  so the user can paste currency strings.
- **Page draft state** carries pending edits as a `Partial<Record<EditableField, string>>`.
  Each FieldRow's value is `draft[name] ?? invoice[name]`; the
  comparison drives both the value displayed and the dirty marker.
- **`SaveBar`** sticks to the bottom of the right pane only when
  `dirtyCount > 0` (UX_PRINCIPLES principle 2: one primary action
  per screen). Shows count + helper copy ("Save to re-validate
  against LHDN rules. Your masters learn from this."), Discard +
  Save buttons. On save, the response replaces the invoice state
  and clears the draft.
- **Type narrowing**: `EditableField` is a string-literal union that
  must match the backend's `EDITABLE_HEADER_FIELDS`. A typo in the
  page's `onChange` flow becomes a TypeScript error rather than a
  silent runtime 400.

A small visibility bug also fixed: the `required.line_items` rule's
`field_path = "line_items"` (no `[N]`) was being filtered out of the
orphan-issues stack because the predicate used `startsWith("line_items")`
which also matched the indexed paths the table renders. Tightened to
`startsWith("line_items[")` so collection-level findings render in
the orphan stack alongside other field-less issues.

Tests: 16 new (174 passing total). Service-level coverage of single-
field updates, multi-field batching into one audit event, no-op when
nothing changed, decimal coercion, unknown-field rejection, invalid-
decimal rejection, master propagation (corrects blank, overwrites
wrong value, files old name as alias), revalidation clearing
resolved issues, revalidation surfacing newly-broken invariants.
Endpoint-level: PATCH happy path, PATCH unknown-field 400, PATCH
unauth 403, PATCH cross-tenant 404. Allowlist invariant test pins
the submission-lifecycle field omissions.

Verified live with Playwright: signed up fresh, dropped the
synthetic empty-PDF, the review screen rendered with 6 error pills
(missing required fields). Filled invoice number, issue date,
supplier name, supplier TIN, buyer name, buyer TIN — all six fields
showed the "Edited" dirty marker, SaveBar appeared with "6 unsaved
corrections". Clicked Save, the response cleared the draft, errors
dropped to 0 inline pills, banner softened to "1 ERROR" (the
line-items rule, now correctly orphan-rendered), every edited field
showed a 100% green confidence dot. Reloaded the page —
`invoice_number = "EDIT-INV-001"` persisted.

Durable design decisions:

- **Allowlist over denylist for editable fields.** The set is small,
  explicit, and tested; new fields opt in deliberately. The
  alternative (deny submission-lifecycle fields) would have to be
  kept in sync forever and would silently grow holes.
- **User corrections OVERWRITE master values; the master values
  never overwrite invoice values.** Two opposite rules at the same
  master/invoice boundary, both intentional. The review UI is the
  only place a human commits a value; everything else is
  machine-generated. The master learns from humans.
- **Confidence 1.0 on user-edited fields** matches the
  master-autofill convention. The review UI doesn't need to
  distinguish "from your correction" from "from your master" —
  both are user-confirmed signals. If we later need the
  distinction, a separate flag carries it without changing the
  visual treatment.
- **Single audit event per save**, not one per field. The user's
  mental model is "I saved a batch of corrections", not "I
  changed seven fields in atomic order"; the audit log matches.
- **Re-enrich AFTER user edits**, then re-validate. Order
  matters: the enrichment pass picks the right master if the
  user just corrected the TIN, and validation sees the
  post-enrichment field set so master-filled fields don't
  trip "missing" warnings.

What's deferred:

- **Adding / removing line items** through the UI. Editing existing
  lines shipped in Slice 17; add/delete is the next slice on this
  surface.
- **Save-on-blur**, optimistic updates, undo within a session.
  Polish that becomes worth the complexity once the slice is in
  production use and we see the actual editing patterns.
- **Bulk corrections across invoices** ("update all invoices that
  reference this buyer's TIN"). Useful operator surface, but
  premature without volume.

### Slice 16 — Customers route (frequent buyers + master editor)

The sidebar's "Customers · soon" item finally has a screen behind it.
Puts the master data accumulated by Slices 14 + 15 to actual use:
the user can see every buyer ZeroKey has learned, sorted by usage,
and edit any master directly to fix wrong defaults that would
otherwise pollute auto-fill on every future invoice for that buyer.

Backend:

- **`GET /api/v1/customers/`** — list, scoped to active org, sorted
  ``-usage_count, legal_name`` (most-used first matches the
  dashboard's "frequent customers" framing). Default limit 200 keeps
  the page snappy; ``limit=None`` available for export use cases.
- **`GET /api/v1/customers/<id>/`** — detail. Cross-tenant access
  returns 404 (RLS belt-and-suspenders).
- **`PATCH /api/v1/customers/<id>/`** — direct edits to a
  CustomerMaster. Strict allowlist (``EDITABLE_CUSTOMER_FIELDS``):
  legal_name / tin / registration_number / msic_code / address /
  phone / sst_number / country_code. **Excludes** auto-managed
  fields (``aliases``, ``usage_count``, ``last_used_at``,
  ``tin_verification_state``) — direct edits would corrupt the
  accumulation logic. Same shape as ``update_invoice`` from Slice 15:
  rename files the previous canonical name as an alias, single
  ``customer_master.updated`` audit event with field NAMES (no
  values, PII).
- **`apps.enrichment.services`** gained
  ``list_customer_masters`` / ``get_customer_master`` /
  ``update_customer_master`` plus a ``CustomerUpdateError``
  exception. Cross-context callers go through these, not the
  models.

Frontend:

- **`/dashboard/customers`** — table view sorted by usage. Each row
  shows legal name (with "also known as" alias hint when present),
  TIN, MSIC code, invoice count, last-seen date, and a
  verification badge (success / error / muted "Unverified" — the
  third state stays default until live LHDN TIN verify lands).
  Empty state per UX_PRINCIPLES principle 7: speaks in opportunity
  ("Customers appear here automatically as you submit invoices...")
  and links back to the dashboard upload zone.
- **`/dashboard/customers/[id]`** — detail with the same edit-
  draft + SaveBar pattern as the invoice review screen (Slice 15).
  Two-column layout: identity + contact field rows on the left;
  usage stats / alias history / verification card on the right.
  All eight allowlisted fields are editable in place; the
  ``FieldRow`` component is reused unchanged. Save runs the PATCH
  and replaces the local state with the response.
- **Sidebar**: ``Customers`` item drops the ``soon`` badge and
  becomes a real link.
- **Frontend types**: ``Customer`` shape mirrors the serializer.
  ``api.listCustomers()`` / ``getCustomer(id)`` /
  ``updateCustomer(id, updates)`` wrap the new endpoints.

Tests: 11 new (185 passing total). List sorts by usage_count desc
+ name asc; list filters by active org (cross-tenant rows excluded);
unauth rejected. Detail returns the expected fields; cross-tenant
detail 404. PATCH corrects MSIC + audits with field-names-not-values
payload; rename files old name as alias; allowlist rejects
``aliases`` / ``usage_count`` / ``tin_verification_state`` /
random unknown keys; blank legal_name rejected; no-op when nothing
changed (no audit event); cross-tenant PATCH 404.

Verified live with Playwright: signed up fresh, /dashboard/customers
showed the empty-state copy. Uploaded a PDF, edited the buyer
identity on the review screen and saved — the new master appeared
in the customers list ("Important Buyer Sdn Bhd / C30000000099").
Clicked into detail, edited the MSIC code to "62010", saved,
reloaded the page — the value persisted.

Durable design decisions:

- **Allowlist over denylist for editable customer fields.** Same
  rationale as the invoice update path (Slice 15): set is small,
  explicit, tested; new editable fields opt in deliberately.
  ``aliases`` / ``usage_count`` etc. are out because they're
  auto-managed; surfacing them as edits would corrupt the
  accumulation logic.
- **Reuse the FieldRow + SaveBar pattern**, don't invent a new
  editor. The visual language ("Edited" dirty marker, sticky save
  bar, helper copy under the count) is the same in
  ``/dashboard/jobs/[id]`` and ``/dashboard/customers/[id]``;
  reviewers move between the two without re-learning anything.
- **Verification badge stays "Unverified" until live LHDN check.**
  We have a verified state in the model schema but no integration
  to populate it; the badge says so honestly rather than showing
  an empty placeholder.
- **Sidebar "soon" badges are temporary.** Each route ships
  removes its badge; the visible inventory of "what's coming"
  shrinks as the build progresses, which is the framing
  UX_PRINCIPLES principle 6 ("the first ten minutes determine
  retention") wants.

What's deferred:

- ~~Per-customer invoice list~~ — shipped in Slice 19.
- **Search + filter** on the list. List is ordered by usage so the
  top-of-list is what the user usually wants; search waits until
  list size makes it worthwhile.
- **Item master surface.** Same shape, different table. Lower
  immediate value than customers; ships when the line-item
  editing slice lands and surfaces the masters as a side effect.
- **Bulk re-enrich** (apply current master to historical invoices
  whose fields don't match). Useful operator surface, premature.

### Slice 17 — Editable line items + ItemMaster propagation

Slice 15 made the invoice header editable; this slice closes the
remaining half by extending the same edit-save-revalidate-propagate
pattern to line items. Now every cell on the review screen — header
fields, party blocks, totals, AND every line-item cell — supports
inline correction with the same visual language and the same
post-save side effects.

Backend:

- **`update_invoice` accepts a ``line_items`` array** alongside the
  existing header fields. Each entry addresses a specific line by
  ``line_number`` (the stable identifier within an invoice; the DB
  id stays internal). Allowlist of editable per-line fields:
  description, unit_of_measurement, quantity, unit_price_excl_tax,
  line_subtotal_excl_tax, tax_type_code, tax_rate, tax_amount,
  line_total_incl_tax, classification_code, discount_amount,
  discount_reason_code. Unknown line numbers, unknown fields, and
  malformed payloads all raise ``InvoiceUpdateError`` rather than
  silently being ignored.
- **One audit event per save**, summarising both header changes and
  per-line changes — payload includes ``changed_line_items: [
  {line_number, changed_fields[]} ]``. Field NAMES only, no values
  (PII redaction matches the header path).
- **ItemMaster propagation**: a corrected ``classification_code`` /
  ``tax_type_code`` / ``unit_of_measurement`` /
  ``unit_price_excl_tax`` on a line item updates the matched
  ItemMaster's defaults. Same rule as the buyer-master path: user
  corrections OVERWRITE master values. Quantity / per-line tax
  amounts / etc. don't propagate — those are per-invoice values,
  not per-item patterns.
- The ``description`` field can be edited but the master is keyed
  off the new description; if the edit effectively renames the
  item, the next ``enrich_invoice`` pass picks the right master and
  records the alias. We don't attempt master re-keying inside the
  update service — the enrich path is the single owner of master
  matching.
- Per-line ``per_field_confidence`` flips to 1.0 for changed cells,
  matching the header-cell convention. The frontend's three-band
  scheme renders edited cells as the highest-confidence green dot,
  so "this came from your correction" is visually identical to
  "this came from your master".

Frontend:

- **`LineItemsTable` is dual-mode** like `FieldRow`. Read mode
  (no `onChangeCell` prop) keeps the existing static cells with
  per-line issue rows; edit mode renders every cell as a
  chrome-less input that looks like text until clicked. Each cell's
  dirty state is keyed by `(line_number, field)`. Dirty cells get
  a Signal-tinted ring and faint Signal/5 background — same
  vocabulary as the header `FieldRow`'s "Edited" marker.
- **Page state** tracks per-line drafts as
  `Record<number, LineDraft>` alongside the existing header `Draft`.
  The `dirtyCount` displayed in the SaveBar sums header drafts +
  every per-line cell. Save submits both halves in one PATCH
  payload; Discard clears both. The user's mental model
  ("I'm correcting this invoice") collapses both edits into one
  "save corrections" action — UX_PRINCIPLES principle 2 unchanged.

Tests: 9 new (194 passing total). Description edit persists with
confidence=1.0; decimal cell coerces "RM 250.50" → Decimal; one
audit event covers header + line edits combined; unknown
line_number rejected (`line_items[99]`); non-editable line field
rejected (`id`, etc.); malformed payload rejected (non-array
shape, missing line_number); ItemMaster propagation overwrites a
prior wrong code; combined header + line update emits exactly one
audit event; submitting current values is a true no-op (no event
written).

Verified live against the running stack: created an invoice with
one line item ("Premium Widget"), let `enrich_invoice` create the
matched ItemMaster, deliberately seeded the master with a wrong
default classification (`999`). Called `update_invoice` with a
line-items payload setting `classification_code="011"` +
`unit_of_measurement="EA"`. Result: line item picked up the new
codes, ItemMaster `default_classification_code` flipped from `999`
to `011`, master `default_unit_of_measurement` learned `EA`. The
correction overwrote the wrong master value, exactly as designed.

Durable design decisions:

- **`line_number` is the addressing key, not the database id.**
  Stable within the invoice, unique by constraint, and matches how
  the user thinks about line items. Exposing the DB id would
  encourage downstream code to bypass the invoice-scoped query.
- **One PATCH endpoint, header + lines together.** Two endpoints
  would force the front-end to coordinate save order and the audit
  log to interleave events. The user's mental model is "save my
  corrections", singular.
- **One audit event per save** mirrors the user's mental model.
  The payload's `changed_line_items` summary is enough for an
  audit reader to reconstruct what changed without leaking values.
- **ItemMaster propagation skips quantity / amounts / per-line
  tax.** Those are per-invoice values; making them master defaults
  would cause auto-fill to overwrite different-but-correct values
  on the next invoice. Pattern-stable fields only.
- **Same FieldRow + cell visual language** across the whole
  review surface. Header field → row card with "Edited" marker;
  line cell → table cell with Signal-tinted ring. Reviewers see
  the same mark for the same meaning anywhere on the screen.

What's deferred:

- **Adding / removing line items** through the UI. The "edit"
  contract assumes the line set is fixed by extraction; if the
  user needs to add a missing line they currently have to upload
  a corrected document or use the API. The next slice on this
  surface adds + delete.
- **Cell-level validation feedback**. Today errors are line-level
  (the issue row underneath); per-cell error decoration (red
  border on the offending cell only) waits for the editable
  experience to settle in production use.
- **Keyboard navigation between cells** (tab / arrows like a
  spreadsheet). Click-to-edit is enough for v1; refine when we
  see actual usage.

### Slice 18 — Cached LHDN reference catalogs

Closes the largest validation-quality gap available without KMS or
LHDN sandbox creds. The format-only catalog rules from Slice 11
(MSIC, classification code, tax type, UOM, country) now consult cached
LHDN reference data rather than just regex-matching the format. Per
LHDN_INTEGRATION.md "reference data caching", the catalogs live
locally and refresh monthly from the LHDN published source.

What landed:

- **5 reference-catalog models** in `apps.administration`:
  `MsicCode`, `ClassificationCode`, `UnitOfMeasureCode`,
  `TaxTypeCode`, `CountryCode`. All platform-wide (NOT tenant-scoped)
  — every customer's validation rules read from the same tables.
  Each row carries `is_active` (deprecated codes stay around so
  historical invoices stay verifiable) and `last_refreshed_at` (the
  audit reader can see which version of the LHDN published catalog
  the row was reconciled against).
- **Seed migration** ships a representative subset:
  - **32 MSIC codes** — common SME categories (retail, software,
    services, hospitality, F&B, professional, finance, real estate,
    education, health). Full ~700-row catalog lands when the LHDN
    refresh integration wires in.
  - **45 classification codes** — the LHDN-published e-invoice
    Category list (1–45) in full, including the catch-all "022 Others".
  - **20 UOM codes** — the UN/CEFACT subset LHDN accepts in practice
    (C62 / KGM / LTR / MTR / EA / PCE / HUR / DAY / etc.).
  - **7 tax type codes** — the COMPLETE LHDN published list
    (01/02/03/04/05/06/E), with `applies_to_sst_registered` for the
    SST consistency rule.
  - **56 country codes** — Malaysia + ASEAN + East/South Asia +
    GCC + Americas + EU + Oceania + key African + Russia /
    Ukraine. Full ISO 3166-1 alpha-2 (250 codes) lands with the
    refresh integration.
- **Service helpers** in `apps.administration.services`:
  `is_valid_msic` / `is_valid_classification` / `is_valid_uom` /
  `is_valid_tax_type` / `is_valid_country`. Each returns `False` for
  blank input, unknown codes, and inactive rows — the caller doesn't
  need to special-case any of those.
- **Validation rules upgraded to two-tier**:
  - `_check_msic` and `rule_buyer_country_code`: format failure stays
    `ERROR`, catalog miss is `WARNING`. The two-tier severity is
    deliberate — promoting catalog misses to `ERROR` while the seed
    catalog is incomplete would create false rejections during the
    pre-LHDN-refresh window. Once the refresh wires in and the
    catalogs are authoritative, the misses promote to `ERROR`.
  - **New `rule_line_item_catalogs`** validates per-line
    `classification_code` / `tax_type_code` / `unit_of_measurement`
    against their respective catalogs, all `WARNING` for now. New
    issue codes: `line.classification.unknown`, `line.tax_type.unknown`,
    `line.uom.unknown`.
- **Refresh stub** at `apps.administration.tasks.refresh_reference_catalogs`
  + service-level `refresh_reference_catalogs()`. Today it just
  stamps `last_refreshed_at` on every active row; the production
  implementation will hit LHDN's published catalog endpoints, diff
  against local rows, and upsert. The shape and Celery wiring are
  here so the LHDN client lands in one place.
- **Django admin** registers all five catalog models (read-mostly:
  search, filter on `is_active`). Inline editing is emergency-only
  (toggle a code's `is_active` if it needs to be deprecated before
  the next monthly refresh).

Tests: 20 new (214 passing total).
- 5 seed-presence tests pin the migration's expected codes (so a
  future seed change doesn't silently break validation).
- 5 lookup-helper tests cover known/unknown/blank/inactive
  per catalog.
- 2 refresh-stub tests confirm `last_refreshed_at` stamps the
  active set and skips inactive rows.
- 8 new validation-rule tests cover the two-tier severity (known
  codes pass, unknown formats fail with `ERROR`, unknown codes that
  match format fail with `WARNING`) for MSIC, country, and the
  three line-item catalogs.

Verified live: applied both new migrations on the running stack;
catalog counts confirmed (32 / 45 / 20 / 7 / 56); positive +
negative lookups returned the expected booleans; the refresh stub
stamped every active row with the current timestamp.

Durable design decisions:

- **Two-tier severity (format ERROR + catalog WARNING)** during
  the seed-only window. Promoting catalog misses to ERROR before
  the LHDN refresh is wired would block submission on codes LHDN
  itself accepts but our seed doesn't have. The promotion path is
  documented inline so the change is one rule severity flip when
  the refresh ships.
- **`is_active` not delete** for deprecated codes. Historical
  invoices that reference a now-deprecated code remain auditable
  against the version of the catalog active at their issue date.
  LHDN explicitly publishes deprecation rather than removal; we
  match.
- **Reference catalogs are platform-wide, not tenant-scoped.**
  Every customer reads the same rows. Tenant-specific overrides
  (Custom-tier customers with non-standard tax treatments) belong
  in a separate "tenant override" table that points at base
  catalog rows; not needed in any current scope.
- **Lookup helpers are the cross-context boundary**, not the
  models. Validation rules call `is_valid_msic` etc.; the
  validation context never imports `apps.administration.models`
  directly. Same pattern as every other service-only crossing.
- **Seed ships a representative subset, not the whole catalog.**
  The migration is small, fast, easy to audit; the real LHDN
  catalogs land via the (eventually wired) refresh task. The
  alternative (shipping ~700 MSIC rows in a migration) makes the
  migration painful and the file noisy without making the
  validation more correct in the seed-only window.

What's deferred:

- **Real LHDN catalog refresh** — the task fetches from LHDN's
  published endpoints, diffs, upserts. Credentials are already in
  the `lhdn` SystemSetting (Slice 10); the implementation is a
  hundred lines of HTTP client + JSON parsing.
- **Celery beat schedule** for the refresh — `zerokey.celery`
  needs a beat schedule entry pointing at
  `administration.refresh_reference_catalogs` on a monthly cron.
  Add when the real refresh implementation lands.
- **MSIC parent_code population** — the catalog is hierarchical
  (5-digit codes roll up to 4-digit categories). Seed leaves
  `parent_code` blank; the refresh task populates it from the
  LHDN-published hierarchy.
- **Severity promotion** of catalog misses from WARNING to ERROR
  once the refresh integration ships. One-line change in
  `_check_msic` / `rule_buyer_country_code` /
  `rule_line_item_catalogs`.

### Slice 19 — Per-customer invoice list

Closes the obvious "show me every invoice from this buyer" drill-down on
the Customers detail surface (Slice 16). The Customers route now answers
the operator's first follow-up question after looking at a master:
"how often do we deal with this buyer, and what does the invoice
history look like?".

Backend:

- **`GET /api/v1/customers/<id>/invoices/`** — compact list of every
  Invoice on the active org whose buyer matches the master. Match
  policy mirrors the enrichment-time matcher (`_find_customer_master`)
  inverted: TIN equality wins when the master has a TIN; otherwise the
  master's canonical name OR any learned alias matches case-
  insensitively. Returns most-recent-first, prefetched with line
  items.
- **404 (not 200 with empty list) when the customer doesn't belong
  to the active org** — preserves cross-tenant opacity (otherwise an
  attacker probing IDs could distinguish "exists but not yours" from
  "doesn't exist").
- **`CustomerInvoiceSummarySerializer`** ships a compact shape
  (id, ingestion_job_id, invoice_number, issue_date, currency_code,
  grand_total, status, created_at). Full invoice payload is one
  click away via the ingestion job link in the UI; we don't pay the
  serialization cost on a list endpoint.
- **`list_invoices_for_customer_master`** in
  `apps.enrichment.services`. Cross-context import of
  `apps.submission.models.Invoice` is OK because enrichment owns the
  master matching logic and the inverted query is the natural
  complement.

Frontend:

- **`/dashboard/customers/[id]`** gains an "Invoices from this buyer"
  section beneath the existing identity / contact / aside layout.
  Renders as a compact table with invoice number, issue date, grand
  total (with currency), and a status pill. Each row links to
  `/dashboard/jobs/<ingestion_job_id>` — the existing review screen.
- **Empty state** speaks in opportunity ("No invoices have referenced
  this buyer yet. New invoices that match this master appear here
  automatically.") per UX_PRINCIPLES principle 7.
- **Loading state** is a small "Loading…" placeholder while the
  list fetch is in flight; the master-detail render is independent
  so the page is usable even if the invoice list is slow.
- New types `CustomerInvoiceSummary` + `api.listCustomerInvoices(id)`
  in api.ts. Independent fetch from the master detail — both kick off
  in the same `useEffect` so the round-trips overlap.

Tests: 6 new (220 passing total). TIN-equality match returns matching
invoices and excludes non-matching; alias-fallback match (case-
insensitive against canonical + every alias) when the master has no
TIN; 404 for cross-tenant customer; empty list for a master with no
matching invoices; unauth rejected; serializer returns the compact
field set (only the keys the table needs).

Verified live: created a master + two matching invoices on the same
TIN, called the service: returned both invoices in created_at desc
order, with the right grand totals. Cleanup confirmed.

Durable design decisions:

- **Match policy mirrors the enrichment matcher, inverted.** TIN
  is the canonical key; alias-or-canonical-name is the fallback for
  no-TIN buyers. The two functions read as natural complements;
  any future change to enrichment matching (fuzzy, embeddings, etc.)
  applies symmetrically here.
- **Compact serializer for list, full for detail.** The list fetches
  enough to render the table + the click-through link; the detail
  invoice fetch carries the full payload. Same pattern as the
  customers list / detail split.
- **404 over empty 200** for cross-tenant access. Cross-tenant
  opacity beats the cleaner "always returns a list" API ergonomics
  here — the one-bit information leak (does this id exist on
  another tenant) is worth preventing.

What's deferred:

- **Date / status filters** on the list. The list is most-recent-
  first; filters wait until volume makes them worthwhile.
- **Per-customer aggregate stats** (total invoiced, average,
  outstanding). The data is in the line items; renders on the
  detail aside when we have enough invoices to make the numbers
  interesting.
- **Cross-master de-duplication** (one buyer, two masters from a
  TIN edit). A Settings → "Merge customers" operator action; the
  rename-via-TIN-edit case in Slice 14 doesn't currently produce
  these in practice but a deliberate merge surface is worth having.

### Slice 20 — Audit log page

Surfaces ZeroKey's most distinctive technical claim — the immutable,
hash-chained audit log — to the user. Every business-meaningful action
has been producing events since Slice 2; this slice is the operator +
compliance-officer surface for browsing them. The chain itself was
already trustworthy; what changed is that customers can now SEE it.

Backend:

- **`GET /api/v1/audit/events/`** — paginated list, scoped to active
  org, newest-first. Filters: `?action_type=<exact match>` + cursor-
  based pagination via `?before_sequence=<n>` (each page returns
  events strictly older than the cursor). The cursor approach keeps
  queries to point lookups on the `(organization, sequence)` index
  as the log grows. `limit` clamped to 1–200.
- **`GET /api/v1/audit/action-types/`** — distinct action types
  present on the org's log, sorted alphabetically. Powers the
  filter dropdown so users only see codes that actually appear in
  their data.
- **`AuditEventSerializer`** exposes the full row including
  `content_hash` and `chain_hash` as hex strings (the model stores
  them as raw bytes; hex is the presentation form for the
  "technical details" expandable). Read-only by design — the audit
  table is append-only at the application layer (model.save / .delete
  refuse) and at the database layer (RLS revokes UPDATE/DELETE from
  the app role).
- **Service helper distinct() ordering bug fix**: AuditEvent's
  default `Meta.ordering = ["sequence"]` would otherwise add
  sequence to the SELECT column list and defeat `DISTINCT` (every
  row's sequence is unique → every action_type returns once per
  emission). The fix is `.order_by()` to clear the default before
  `.values_list().distinct()`. Documented inline so the next
  reader doesn't reintroduce the bug.

Frontend:

- **`/dashboard/audit`** — table view with sequence, timestamp,
  action (rendered as inline code), actor (type:id), affected
  entity (type:id). Each row expands inline to reveal the JSON
  payload + a "Technical details · hash chain" disclosure
  containing schema version, sequence, content_hash, chain_hash.
  Pagination via "Load more" using the sequence cursor.
- **Chain badge** at the top right: a Signal-success-tinted pill
  with a shield icon and the live event count
  ("14 events on the chain"). Lightweight, calm, but visually
  signals "this is on the immutable chain" without making a
  marketing claim.
- **Filter dropdown** is populated from
  `listAuditActionTypes()` so only present codes appear; "All
  actions" is the default option, "Clear filter" link reset.
- **Empty state** speaks in opportunity ("Audit events appear here
  as soon as anything happens — sign-ins, uploads, validation,
  edits. Every event is hash-chained and immutable.") per
  UX_PRINCIPLES principle 7.
- **Sidebar**: `Audit log` drops the `soon` badge, becomes a real
  link.

Tests: 11 new (231 passing total). Service-level: list returns
org events newest-first, action_type filter is exact match,
before_sequence cursor paginates correctly, cross-tenant rows
(including system events with `organization_id IS NULL`) are NOT
returned, action-types service returns sorted distinct codes.
Endpoint-level: GET returns results + total + hex-encoded hashes,
action_type filter via query param, limit clamping, invalid limit
400, unauth rejected, action-types endpoint returns the list.

Verified live with Playwright: signed up fresh, dropped the
synthetic PDF, navigated to /dashboard/audit. The page rendered
14 events from the full upload pipeline:
`identity.user.registered` →
`identity.organization.created` →
`identity.membership.created` →
`auth.login_success` →
`ingestion.job.received` →
`ingestion.job.state_changed` →
`ingestion.job.vision_escalation_started` →
`ingestion.job.vision_escalation_skipped` →
`ingestion.job.extracted` →
`invoice.created` →
`invoice.structuring_skipped` →
`invoice.enriched` →
`invoice.validated`. Chain badge showed "14 events on the chain".
Action-type filter narrowed to 1 row when set to
`ingestion.job.received`. Row expansion revealed the JSON payload
and the hex content/chain hashes.

Durable design decisions:

- **Cursor pagination over offset.** As the audit log grows, an
  offset query gets progressively more expensive. The
  `(organization, sequence)` index makes cursor-based lookups
  point queries forever. The frontend's "Load more" pattern uses
  the last-seen sequence as the cursor.
- **Hex hashes in the API.** The model stores raw bytes for byte-
  exact hashing math; the API exposes hex because that's what
  reads correctly in a "technical details" disclosure. The
  conversion is unidirectional — the API never accepts a hash
  from the client (it can't, the audit log is read-only).
- **Filter dropdown reads from the data, not a static list.**
  Keeps the dropdown honest: only codes the user has actually
  produced are selectable. New codes ship live without needing a
  frontend update.
- **System events (`organization_id IS NULL`) excluded** from the
  customer-facing list. Platform housekeeping (nightly
  verifications, etc.) belongs in an internal ops surface, not
  in the customer's tenant view.
- **Append-only is enforced at every layer.** Model rejects save
  on existing rows + rejects delete; RLS revokes UPDATE/DELETE
  from the app role; serializer is read-only fields. The
  customer surface inherits all three by default — the page has
  no edit affordance because there was never a write path.

What's deferred:

- **Date-range filter.** action_type is the most commonly used
  filter; date range (e.g. "events in the last 24h") waits until
  the log is large enough for time-bucketing to matter.
- **Search across payload contents.** Implementable with a GIN
  index on the JSON column; valuable for support investigations
  ("show me events that mention this UUID"). Phase 5 territory.
- **CSV / JSONL export** of the chain. The
  `AuditExport` model in DATA_MODEL.md anticipates this — itself
  audit-logged. Phase 6 compliance work.

### Slice 21 — Customer-triggered chain verification

Closes the audit-surface trust loop. Slice 20 made the chain visible;
this slice makes it verifiable. The customer clicks "Verify chain
integrity" on the audit page, the platform re-walks the chain on their
behalf, and returns a tamper-detected boolean + count. The
verification call itself produces an audit event so the verify
request appears in the chain it just verified.

Backend:

- **`apps.audit.services.verify_chain_for_visibility`** — wraps
  the existing global `verify_chain()` in a brief `super_admin_context`
  (so the walker can read events across tenants — the chain is
  globally sequenced) and returns a customer-tailored summary:
  `{ok, events_verified, tampering_detected, support_message}`.
  Cross-tenant info control: the offending sequence number is
  logged to ops but **never returned** to the customer (it could
  belong to another tenant's event). The customer-facing message
  is generic on failure ("Chain integrity check failed. Operations
  has been alerted.") so the same response shape applies whether
  their own events tampered or someone else's broke the chain
  upstream.
- **`POST /api/v1/audit/verify/`** — POST not GET because the
  call writes one audit event. Returns the service summary verbatim.
  Cheap to call relative to the chain length, but not idempotent
  (each call adds an entry to the chain).
- **`audit.chain_verified` event** records the request itself with
  `{ok, events_verified}` payload — never the offending sequence,
  same redaction rule as the response. The verification is part of
  the chain it verifies; a self-referential property that's the
  whole point of an immutable log.

Frontend:

- **Verify button on `/dashboard/audit`** replaces the static
  ChainBadge from Slice 20 with an interactive `ChainStatus`
  component. Default state (no verify yet) is muted slate; after
  a clean verify it flips to success green with "All audit events
  verified — your chain is intact."; after a tamper detection it
  flips to error red with "Chain integrity check failed. Operations
  has been alerted." The button text reads "Verify chain integrity"
  → "Verifying chain integrity…" (disabled) → "Re-verify".
- **List refresh on success**: the verify call wrote a
  `audit.chain_verified` event, so the page re-fetches the events
  list to show the new entry. The chain-of-the-verification-of-the-
  chain rendering is informative — the user sees their own action
  in the chain as confirmation.

Tests: 7 new (238 passing total).
- Clean chain returns `ok=True` with `events_verified ≥ 3`.
- Tampered chain returns `ok=False` with `tampering_detected=True`,
  `support_message` mentions support/alerts, and the result dict
  carries no key or value that exposes a sequence number.
- Verify call is audited: each invocation writes one
  `audit.chain_verified` event scoped to the requester's org with
  the right actor + payload (no sequence numbers in payload).
- Endpoint returns clean chain on POST; GET returns 405
  (idempotency lie would be misleading); unauth rejected;
  no-active-org returns 400.

Verified live with Playwright: signed up fresh, dropped the
synthetic PDF (seeded the chain with 14 events from sign-up +
upload + extraction + enrichment + validation), navigated to
/dashboard/audit. Initial badge: muted slate, "Verify chain
integrity" prompt. Clicked the button. Response (after resetting
the dev DB's accumulated drift from prior slice smoke tests):
green badge "All audit events verified — your chain is intact.",
event count bumped to 15 (the new `audit.chain_verified` event
appeared at sequence 15 at the top of the table).

The dev-DB drift discovery is itself a useful artifact: ad-hoc
work across many slice sessions had broken the chain. The new
verify endpoint correctly detected the corruption (sequence 10
mismatched), and we reset the dev audit table to demonstrate the
clean case. In production this kind of corruption would be a
critical alert; in dev it's a teachable moment about why we
needed the verify surface in the first place.

Durable design decisions:

- **Verify is POST, not GET.** The call writes an audit event;
  marking it idempotent in HTTP semantics would be a small lie
  with real downstream consequences (caching layers, retry
  semantics).
- **Cross-tenant opacity in the failure path.** A customer's
  verify call walks the global chain, but a failure at another
  tenant's event must NOT leak that event's sequence number.
  Generic "contact support" message; offending sequence stays in
  ops logs only.
- **The verify event is part of the chain it verified.** The
  immutable log includes its own verifications, so an attacker
  who tampered with old events can't quietly re-verify and
  rewrite the verification record — both the original tamper AND
  any subsequent rewrite would show up.
- **Super-admin elevation, not per-tenant.** The chain is
  globally sequenced; verifying any one event requires walking
  every prior event's chain hash. A per-tenant verify would have
  to elevate anyway; better to be honest about the elevation and
  audit it ("audit.verify_chain:customer_request").
- **Dev-DB drift is real.** The verify endpoint surfacing
  accumulated chain corruption from solo-developer ad-hoc work
  is exactly its job. In production this would be a critical
  alert; recording it here as a discipline note: dev DB resets
  are sometimes the right move, but the drift came from real
  state changes worth understanding.

What's deferred:

- **Operator-facing chain repair surface.** Today, drift requires
  a `TRUNCATE audit_event RESTART IDENTITY CASCADE` (dev only)
  or a careful forensic reconstruction (prod). A super-admin
  console with "show me the chain integrity status across all
  tenants" + a guided incident-response playbook is the
  Phase 6 ops work.
- **Background re-verify**, e.g. a nightly Celery task that
  walks the chain and pages on-call if integrity fails.
  `verify_chain_for_visibility` is already callable in this
  shape; just needs scheduling.
- **Per-tenant verify with chain forking.** Truly tenant-scoped
  verification would require parallel per-tenant sub-chains
  alongside the global one, doubling write cost. Not worth it
  for SME workloads; revisit only if a Custom-tier customer
  contractually requires it.

### Slice 22 — Engine activity page

Surfaces the per-engine telemetry the platform has been recording
since Slice 5 — every OCR / LLM call writes an `EngineCall` row with
latency, cost, outcome, confidence, vendor diagnostics. Until this
slice none of that was visible. ENGINE_REGISTRY.md "observability and
auditability" requires the surface; customers paying per call have a
legitimate need to see which engines processed their invoices and how
reliably.

Backend:

- **`engine_summary_for_organization`** in
  `apps.extraction.services` — per-engine roll-up scoped to the
  active org's calls. Annotations via `Count` + `Avg` + `Sum` on the
  outcome field do the work in one query; the per-row dict carries
  `total_calls`, success/failure/timeout/unavailable counts,
  computed-on-read `success_rate`, `avg_duration_ms`,
  `total_cost_micros`. Sorted by `total_calls` desc — the engines
  doing the most work for the customer come first.
- **`list_engine_calls_for_organization`** — recent EngineCall rows,
  newest-first, cursor-paginated on `started_at`. `select_related`
  on the engine FK keeps the row payload one query.
- **`GET /api/v1/engines/`** + **`GET /api/v1/engines/calls/`**.
  Limit clamping, ISO-8601 cursor parsing for `before_started_at`,
  invalid input → 400.
- **EngineCallSerializer** is compact (id, engine_name, vendor,
  request_id, started_at, duration_ms, outcome, error_class,
  cost_micros, confidence, diagnostics). Diagnostics ride along as
  the JSON the adapter wrote — no PII per the model docstring's
  redaction contract.

Frontend:

- **`/dashboard/engines`** — two stacks. Top: per-engine summary
  table (engine + vendor / capability badge / call count / success
  rate with success/warning/error tone bands / avg latency / total
  cost). Bottom: recent calls table with click-to-expand details
  (request_id, cost in micros USD, full vendor diagnostics dump as
  pretty-printed JSON). Cursor-paginated "Load more" same as the
  audit log surface (Slice 20).
- **Cost formatting** rounds to two cents above $0.01, four decimals
  below — keeps small per-call costs readable without scientific
  notation. **Latency formatting** auto-switches ms ↔ seconds.
- **Outcome badges** color-code success / unavailable / failure /
  timeout consistent with the rest of the brand palette.
- **Sidebar**: "Engine activity" drops the `soon` badge.
- New types `EngineSummary` + `EngineCallRecord` + the matching
  `api.engineSummary()` / `api.listEngineCalls()` clients.

Tests: 11 new (249 passing total). Service: per-engine roll-up
counts (success / failure / unavailable broken out, success_rate
ratio, avg_duration_ms int rounding); cross-tenant rows excluded;
empty case returns `[]`; calls list newest-first;
`before_started_at` cursor pagination produces strictly older
pages; cross-tenant call list excludes other org's rows.
Endpoint: summary returns rolled-up rows, calls returns compact
shape with engine + vendor surfaced via SerializerMethodField,
limit / cursor invalid-input 400, unauth rejected.

Verified live with Playwright: signed up fresh,
`/dashboard/engines` showed the empty state ("No engine calls
yet."). Dropped a PDF, returned to engines: summary table showed
**pdfplumber 1 call, 100% success, 2 ms avg, $0** and
**anthropic-claude-sonnet-vision 1 call, 0% success, 2 ms avg,
$0** (vision unavailable as expected — no API key in dev).
Recent calls expanded to reveal the actual vendor diagnostics
JSON: `"detail": "Credential
anthropic-claude-sonnet-vision.api_key not configured (looked in
Engine(...).credentials[api_key], env ANTHROPIC_API_KEY)"`. Real
observability surfacing real engine state.

Durable design decisions:

- **Compute success rate on read, don't store it.** Storing a ratio
  goes stale on every new call; a single SQL aggregation is
  fast enough at any scale we'll see for a year.
- **Cursor on `started_at`, not on `id` or `sequence`.** Engine
  calls don't get a sequence; the natural ordering for the user
  is when-it-happened. The index on `(organization_id,
  -started_at)` (already on the model) makes it a point lookup.
- **Diagnostics surfaced verbatim.** The adapter's JSON dump is
  the right level of detail for ops investigations; pretty-
  printing it in the UI rather than parsing/normalizing keeps
  the shape forward-compatible with new adapter shapes.
- **Tenant-scoped from the service, not RLS.** EngineCall rows
  carry `organization_id` but the table isn't in the per-tenant
  RLS list (Slice 5 noted "system-scoped so cross-tenant
  analytics are straightforward"). Service-level filter is the
  one belt-and-suspenders here; the customer surface never
  crosses tenants.

What's deferred:

- **Filter dropdown** on the calls list (by engine, by outcome).
  Full table is what you want by default; filters wait until
  log size warrants.
- **Engine health surface** — current `Engine.status` (active /
  degraded / archived) doesn't render anywhere. Worth a
  per-engine card or badge once we wire engine health monitoring
  per ENGINE_REGISTRY.md "engine health monitoring".
- **Cost-by-customer rollups** — the data is there to render
  "you spent $X this month on AI calls", which is a billing
  surface. Defer to the billing slice.

### Slice 23 — Settings → Organization

Closes the last `Settings` group sidebar item. Lets the user maintain
their own org's contact + identity details — the kind of edit a
new customer needs to do once shortly after signup, then occasionally
as their business changes.

Backend:

- **`apps.identity.services.update_organization`** — strict
  allowlist (`EDITABLE_ORGANIZATION_FIELDS`): legal_name /
  sst_number / registered_address / contact_email / contact_phone
  / language_preference / timezone / logo_url. Same single-audit-
  event-with-field-names-not-values pattern as the invoice and
  customer master updaters. Empty `legal_name` rejected; no-op
  when the submitted values match current.
- **TIN is excluded by design.** Changing it would invalidate every
  signed invoice that referenced the prior value (LHDN considers
  the TIN the canonical supplier identifier on every signed
  document). If a customer's LHDN-issued TIN actually changes,
  that's a fresh-tenant operation handled by support, not a
  self-serve edit. Same logic applies to `billing_currency`
  (per-Plan), `trial_state` / `subscription_state` (Stripe-managed
  in a future slice), and `certificate_*` (signing service owns
  these).
- **`GET / PATCH /api/v1/identity/organization/`** — single
  endpoint, two methods. The user-must-be-a-member-of-the-active-
  org check returns 403 separately from the no-active-org-set 400.
  Cross-tenant write attempts surface as 403 because the membership
  check fires before the lookup.
- **`OrganizationDetailSerializer`** — full read-side shape
  (including read-only fields like trial_state / certificate_*) so
  the UI renders the entire org on one page.

Frontend:

- **`/dashboard/settings`** — four sections matching the model's
  conceptual groups: Identity, Contact, Preferences, Subscription +
  certificate. Editable sections use the same `FieldRow` + dirty-
  marker pattern as the invoice review and customer master pages
  (Slices 15, 16) — reviewers move between editing surfaces without
  re-learning the gesture vocabulary.
- **Read-only fields render in `ReadOnlyRow`** with a slate-50 tint
  + a hint explaining why ("LHDN-issued. Contact support to change.",
  "Set per Plan; contact support to change."). The visual contrast
  makes the editable-vs-not distinction immediate.
- **SaveBar** sticks to the bottom only when dirty count > 0
  (UX_PRINCIPLES principle 2: one primary action per screen). Helper
  copy is "Saved values are recorded in your audit log." — turns the
  audit chain into a reassurance.
- **Sidebar**: "Organization" drops the `soon` badge.
- New types `OrganizationDetail` + `api.getOrganization()` /
  `updateOrganization()` clients.

Tests: 12 new (261 passing total). Service: allowlisted edits land,
no-op when nothing changes (no audit event), audit payload lists
field names not values, unknown fields rejected (TIN explicitly
tested), blank legal_name rejected. Allowlist invariant test pins
the structural exclusions (TIN / billing_currency / lifecycle /
certificate_*). Endpoint: GET returns active org + all fields,
PATCH applies via endpoint, PATCH unknown field 400, unauth
rejected, no-active-org 400, member-of-different-org 403.

Verified live with Playwright: signed up fresh, navigated to
/dashboard/settings (sidebar's "Organization" with no soon
badge). Page rendered with the registered legal_name +
contact_email + everything. Edited legal_name and contact_phone,
saved, reloaded → both values persisted. Top-bar's active-org
label auto-updated to the new legal_name. Audit log showed one
new `identity.organization.updated` event.

Durable design decisions:

- **Allowlist over denylist** — same rationale as every other
  edit surface this session. Set is small, explicit, tested. New
  editable fields opt in deliberately.
- **TIN is not editable.** Structural choice tied to LHDN's
  signing semantics, not a UI choice. Documented in the model +
  in the allowlist's exclusion comment.
- **Read-only fields stay visible.** The user benefits from
  seeing the whole org shape in one place; the visual treatment
  (slate-50 tint, hint text) makes it clear which rows are
  edit-surfaces and which are reference. Hiding the read-only
  rows would force the user to remember where to look elsewhere
  for billing / certificate state.
- **Single audit event per save**, same as every other multi-
  field updater. The user's mental model is "I saved my Settings
  changes", singular.

What's deferred:

- **Role-based permissions on edit.** Right now any active
  member can edit. Phase 5 ships the
  per-permission gate (e.g. only owner / admin can change the
  legal_name). The check goes in the view's
  `can_user_act_for_organization` block alongside the
  membership check.
- **TIN-change support flow.** Changing a customer's TIN is a
  rare but real event (LHDN reissues for restructuring). Today
  it's a fresh-tenant operation; a guided "transfer to new TIN"
  flow that re-signs the certificate and re-keys masters /
  invoices would belong on a Phase 6 ops surface.
- **Logo upload, not URL.** UI accepts a URL; the production
  flow uploads to S3 and stores the resulting URL. Trivial swap
  when the upload widget lands.

### Slice 24 — Invoices route

Closes the second-to-last sidebar `soon` item. Distinct from the
dashboard's "recent uploads" excerpt: the all-invoices route is a
filterable, paginated list across the customer's entire history.

Backend:

- **`list_invoices_for_organization`** in
  `apps.submission.services` — three filters that match the user's
  mental model of "find an invoice":
  - `status`: exact match against `Invoice.Status`.
  - `search`: case-insensitive substring against `invoice_number`
    OR `buyer_legal_name` OR `buyer_tin`. The user doesn't always
    remember which field the value lives in; one box covers all
    three.
  - `before_created_at`: cursor pagination — same idiom as the
    audit log + engine activity surfaces.
- **`count_invoices_for_organization`** — list-page header context.
  Renders as "N total" alongside the filter bar so the user sees
  the unfiltered total even when looking at a filtered slice.
- **`InvoiceListSummarySerializer`** — wider than the per-customer
  summary (Slice 19) because the list view needs `buyer_legal_name`
  + `buyer_tin` per row (no per-row buyer header). Compact enough
  to keep the response cheap; the full Invoice payload is one click
  away via the ingestion job link.
- **`GET /api/v1/invoices/`** with `?status=` / `?search=` /
  `?limit=` / `?before_created_at=` query params. Limit clamping
  (1–200), ISO-8601 cursor parsing, invalid input → 400. Mounted
  on the existing `/api/v1/invoices/` URL prefix; the empty-path
  pattern (`""`) is the list endpoint.

Frontend:

- **`/dashboard/invoices`** — table with invoice number / buyer
  (name + TIN stacked) / issue date / grand total / status pill.
  Each row links to the existing review screen via the ingestion
  job id.
- **Filter bar** — status dropdown (hard-coded to match the
  backend's `Invoice.Status` set; UI list changes when the state
  machine evolves, which is rare and code-reviewed) + free-text
  search input. Search applies on Enter or click, not on every
  keystroke — avoids hammering the API as the user types.
- **"N total" header context** stays unfiltered so the user can
  see the full inventory size at a glance even while looking at a
  narrow filtered slice.
- **Empty states** are filter-aware: the unfiltered empty state
  speaks in opportunity ("Drop your first invoice →" link to the
  dashboard); the filtered empty state nudges toward "Clear
  filters" instead.
- **"Load more" pagination** with the standard
  `created_at` cursor.
- New types `InvoiceListSummary` + `InvoiceListResponse`, and an
  `api.listInvoices()` client.
- **Sidebar**: "Invoices" drops the `soon` badge.

Tests: 12 new (273 passing total). Service: returns org invoices
newest-first; status exact match; search OR-matches on three
fields case-insensitive; cursor produces strictly older pages;
cross-tenant rows excluded; count is per-org. Endpoint: GET
returns results + total + compact field set; status / search
filters via query param; invalid limit / cursor → 400; unauth
rejected.

Verified live with Playwright: signed up fresh, /dashboard/invoices
showed "No invoices yet" with the upload-prompt link. Dropped two
PDFs, returned to the page: "2 total" header, two table rows.
Status filter narrowed to 2 rows for `ready_for_review`. Free-text
search "C" returned 0 rows (correct — synthetic empty PDFs
produce empty buyer fields, so no value contained "C"); the
filtered empty state and "Clear filters" link rendered as
designed.

Durable design decisions:

- **Search is OR across three fields, not a separate search-by
  selector.** UX-driven: users find an invoice by whatever they
  remember about it. The backend takes a single substring and the
  Django ORM does the OR; tests pin the three-field behaviour.
- **Status options hard-coded on the frontend.** Pulling from a
  dynamic API would let the dropdown drift if the backend
  silently added states. The state machine is small and rarely
  changes; keeping the list of statuses next to the rendering
  code makes new states a deliberate, code-reviewed UI change.
- **Search applies on Enter, not on input.** Type-ahead search
  feels modern but means hitting the API on every keystroke;
  for a list of invoices that's all backend roundtrips with no
  visible benefit. Explicit Enter / click matches the deliberate
  feel of the rest of the surface.
- **Header "N total" stays unfiltered.** Filtered total would
  require a separate query and add visual noise. The unfiltered
  total is the answer to "how big is my invoice corpus?"; the
  filtered list answer to "what am I looking at right now?".

What's deferred:

- **Date range filter.** Search + status cover the common cases;
  date range waits until volume makes time-bucketing useful.
- **Saved filter presets** ("show me invoices that need
  attention" — issues > 0, not validated). The data is there;
  the UI hook is small. Phase 5 polish.
- **Bulk actions** (export, archive, retry submission). Operator
  surface; low immediate value while submission isn't wired.
- **Per-row inline actions** (view audit log entries, view
  validation issues without clicking through). Clean detail flow
  is enough for v1.

### Slice 25 — Exception Inbox

Closes the **last** sidebar `soon` item and finally turns the dashboard
into a navigable, complete product. The Inbox is the triage queue per
DATA_MODEL.md "exception inbox entities" — invoices the pipeline has
flagged for human attention. Unlike the other surfaces (which are
read-or-edit views over existing data), the Inbox is a real **workflow
abstraction**: items appear automatically when conditions trigger,
disappear automatically when conditions clear, and can be manually
resolved when the operator decides nothing more needs doing.

Backend:

- **`apps.submission.ExceptionInboxItem`** model with RLS migration
  (per-table CREATE POLICY pattern matching every other tenant-scoped
  table). Five reasons enumerated:
  - `validation_failure` — the post-validation hook opens this when
    the invoice has blocking errors.
  - `structuring_skipped` — the no-text + no-vision pipeline branch
    opens this when an invoice can't be auto-structured.
  - `low_confidence_extraction`, `lhdn_rejection`,
    `manual_review_requested` — defined in the schema; the trigger
    points wire in as those pipelines mature.
  - Status: `open` / `resolved`. `unique_together (invoice, reason)`
    prevents flapping conditions from creating duplicate rows.
- **`apps.submission.inbox`** module — the single entry point for the
  inbox lifecycle:
  - `ensure_open(invoice, reason, priority, detail)` — idempotent
    upsert. New row → audit `inbox.item_opened`. Already-open row +
    state changed (priority / detail) → save + audit
    `inbox.item_reopened`. Resolved row → reopens (status = open,
    resolved_* cleared), audit `inbox.item_reopened`. Already-open
    row + no changes → no-op (no audit noise).
  - `resolve_for_reason(invoice, reason, ...)` — closes every open
    row matching, used by the auto-resolve path. No-op when no open
    rows exist.
  - `resolve_by_user(organization_id, item_id, actor_user_id, note)`
    — manual close from the UI. Idempotent on already-resolved.
  - `list_open_for_organization` / `count_open_for_organization` —
    the read surface.
- **Pipeline wiring** (`_sync_validation_inbox` in
  `apps.submission.services`):
  - Called from `apply_structured_fields` (post-structuring),
    `finalize_invoice_without_structuring` (no-text path), and
    `update_invoice` (post-edit re-validation).
  - When `validation_result.has_blocking_errors` → ensure_open with
    `reason=validation_failure` + detail `{errors, warnings}`. When
    clean → resolve_for_reason. The auto-resolve actor is
    `None` for pipeline runs and the editing user's id for
    user-triggered re-validates (the audit log distinguishes
    automatic from user-triggered in the resolution_note).
  - The no-structuring path also opens a `structuring_skipped` item
    with the underlying reason in detail.
- **API endpoints** (`/api/v1/inbox/`):
  - `GET /` — list open items with embedded invoice context (number,
    status, buyer, ingestion job id for click-through), optional
    `?reason=` filter, `?limit=` clamped 1–500.
  - `POST /<id>/resolve/` — manual close. Optional `note` in body.
    Cross-tenant id returns 404 (membership-of-active-org check is
    implicit via the service's `organization_id=` filter).
- **Audit events**: `inbox.item_opened` / `inbox.item_reopened` /
  `inbox.item_resolved`. Payloads carry the invoice id, reason, and
  whether the resolution was automatic — never message text or PII.

Frontend:

- **`/dashboard/inbox`** — table with reason badge / invoice link /
  buyer / detail summary / created timestamp / "Mark resolved"
  action. Filter dropdown driven by the reason set; empty state
  speaks "Inbox zero" (with a calm green count badge) when there
  are no open items.
- **Detail summary** is reason-aware: a `validation_failure` row
  renders "N errors · M warnings" with the error count in red; a
  `structuring_skipped` row renders the underlying reason text;
  unknown reasons fall back to a JSON snapshot (so new reasons
  surface visibly even before the UI is taught about them).
- **Optimistic-ish resolve**: clicking "Mark resolved" calls the
  API, then refetches the list so the resolved item drops out
  cleanly and the count updates.
- **Sidebar**: "Inbox" drops the `soon` badge — the last one in
  the navigation. Every group is now fully implemented.
- New types `InboxItem` + `InboxListResponse` + `api.listInbox()` /
  `resolveInboxItem()` clients.

Tests: 17 new (290 passing total). Service: ensure_open creates +
audits; second call is idempotent (no extra row, no extra audit on
no-op); reopen resets resolved_* + audits; priority change writes
audit. resolve_for_reason closes open rows + records "automatic"
in payload; no-op when nothing open. resolve_by_user records the
actor + idempotent on already-resolved. List + count scoped to
active org, exclude resolved + cross-tenant. Pipeline wiring:
deliberate validation failure → inbox row appears via the
`update_invoice` path; fixing the failure on a subsequent edit
auto-resolves it. Endpoint: GET returns embedded invoice context;
POST resolve marks done with the actor; cross-tenant resolve →
404; unauth rejected; invalid limit → 400.

Verified live with Playwright: signed up fresh, /dashboard/inbox
showed "Inbox zero" with the calm success badge. Dropped a PDF
(synthetic empty, no API key for vision). Returned to inbox: 2
open items appeared automatically — `Structuring skipped` ("No
extracted text and no vision adapter available.") and
`Validation failure` ("6 errors · 1 warning"). Clicked "Mark
resolved" on the first row; count dropped from 2 to 1, list
refreshed, the item disappeared.

Durable design decisions:

- **One inbox row per (invoice, reason).** A flapping condition
  (validate → fix → re-break → fix) reopens and re-resolves the
  same row; we never accumulate a graveyard of identical rows.
  The `unique_together` constraint enforces this at the DB layer
  alongside the `ensure_open` semantics in code.
- **Status NOT a separate "needs attention" flag on the
  Invoice.** The Inbox is its own table because reasons can
  coexist (an invoice can have BOTH validation_failure AND
  structuring_skipped at the same time, which a single boolean
  can't represent). The audit-log story also wants per-reason
  events, not per-invoice toggles.
- **Auto-resolution distinguishes itself from manual** in the
  audit log. Automatic resolution leaves `resolved_by_user_id`
  null; manual resolution stamps the actor. Same pattern as
  every other system-vs-user audit distinction.
- **"Show resolved" is deferred.** Triage is forward-looking; the
  open-only default keeps the page honest about "what needs your
  attention right now". The audit log preserves the full lifecycle
  for anyone who needs the recovery view.
- **Reason-specific detail rendering.** Unknown reasons fall back
  to JSON, so adding a new reason on the backend doesn't require
  a coordinated frontend change to be visibly useful (it'll
  render with the JSON detail until the UI is taught its
  shape).

What's deferred:

- **Show resolved toggle.** Forward-looking is the right default;
  add the toggle when an actual customer asks for it.
- **Bulk resolve** (select multiple rows, mark resolved). Phase 5
  operator polish.
- **Notifications** when items appear. The existing audit chain
  already records the events; the user-facing notification (email /
  in-app push) wires through the `Notification` model in
  DATA_MODEL.md when the channel infrastructure lands.
- **Low-confidence-extraction trigger.** The reason exists in the
  enum; the actual hook fires once we have a calibrated confidence
  threshold per engine (depends on the offline calibration tables
  in ENGINE_REGISTRY.md).
- **LHDN-rejection trigger.** Wires in when the MyInvois
  submission service ships (KMS-gated).

---

### Slice 26 — Add / remove line items in review

Closes the editable-invoice surface. Slice 17 made existing line
cells editable; this slice lets the operator **add** entirely new
lines and **delete** wrong ones. Together with Slices 14, 15, 17
the correction loop is now complete: anything the extractor got
wrong — header fields, party master fields, line-item cells, line
membership itself — can be fixed in the review screen.

Backend:

- **`update_invoice` accepts two new arrays** alongside the
  existing `line_items` patch list:
  - `add_line_items: [{description, quantity, unit_price_excl_tax,
    tax_rate, ...}]` — each entry must include a non-empty
    description; other fields are optional and default to zero /
    null. Allowed fields gated by the existing
    `EDITABLE_LINE_FIELDS` allowlist (no smuggling
    `organization_id` / `id` / per-field-confidence in via the
    add path).
  - `remove_line_items: [<line_number>, ...]` — integer line
    numbers. Unknown numbers reject the whole update with a
    400 (no partial application).
  - `_apply_line_item_removes` runs **before** the adds so a
    payload can simultaneously remove L2 and add a new line — the
    new line still gets `max(remaining_numbers) + 1`, which is
    the durable rule.
- **Line numbers never recompact.** Removing line 1 of a 3-line
  invoice leaves lines 2 + 3 with their numbers intact; the next
  add becomes line 4. This matches the invariant that
  `(invoice, line_number)` is a stable external reference — audit
  events, exception-inbox detail payloads, and any future
  rejection-retry comparison can quote line numbers without
  worrying that they shift under their feet.
- **New lines store `per_field_confidence=1.0`** for every
  populated field, same as the user-correction path on existing
  lines — the structured data carries forward the fact that a
  human asserted these values.
- **`InvoiceUpdateResult`** carries new `added_line_numbers` +
  `removed_line_numbers` lists. The `invoice.updated` audit event
  records both as field names (numbers, not values), keeping the
  audit log PII-clean.
- **Validation re-runs after every structural change.** Adding a
  line that fixes an "invoice needs at least one line" violation
  resolves the inbox row automatically (via the
  `_sync_validation_inbox` hook from Slice 25) — no separate
  user gesture needed.

Frontend:

- **`LineItemsTable`** in edit mode grew:
  - Per-row trash button (with `aria-label` "Remove line N"). A
    marked-for-removal row becomes line-through + dimmed, and
    the trash flips to an Undo (RotateCcw) button so the user
    can reverse before saving.
  - "+ Add line" button below the table opens a fresh editable
    row tagged "+ new" with a signal-tinted background. Pending
    rows use negative `pendingNumber` keys (-1, -2, …) to keep
    React keys stable until the server assigns real numbers on
    save.
  - Each pending row has its own discard (×) button so the user
    can back out of an add that's no longer wanted.
- **Page state** (`/dashboard/jobs/[id]`) added `pendingAdds` +
  `removedNumbers` alongside the existing `lineDrafts`. The
  SaveBar count rolls all four sources together. On save, the
  PATCH body builds `add_line_items` (filtered to entries with
  a non-empty description — empty drafts are silently dropped)
  and `remove_line_items` (just the array of line numbers).
- **Error handling**: if the backend rejects (e.g. unknown line
  number on remove), the SaveBar surfaces the message and the
  drafts stay in place so the user can correct without losing
  their work.

Tests: 9 new (299 passing total). Service: add assigns next
sequential number; multiple adds increment monotonically; add
requires non-empty description (400); add rejects unknown
fields; remove deletes by number; remove rejects unknown line
number; remove rejects non-array payload; combined
add+remove+edit in one call (removes preserve gaps, edits hit
remaining rows); audit payload lists added + removed numbers.

Verified live with Playwright: signed up fresh, dropped a PDF,
opened the job. Clicked "Add line" twice → two pending rows
appeared with the signal tint and "+ new" labels; SaveBar read
"2 unsaved corrections". Filled both descriptions, clicked
"Save corrections" — both rows persisted. Clicked the trash on
the first remaining row, saved again — only the second row
remained, **numbered #2** (the first row's number stayed gone,
no recompacting). The validation banner went from 6 errors → 5
errors as soon as the first save landed (the empty-lines
violation cleared once any line existed) — the inbox auto-resolution
loop closed itself end-to-end.

Durable design decisions:

- **No recompaction of line numbers.** Once line 1 is removed,
  it stays removed. Line 4 stays line 4 even after lines 1-3
  vanish. This keeps any external reference (audit event, inbox
  payload, future LHDN rejection citing a line number) stable
  forever. The cost is one extra invariant for the UI to know
  about; the benefit is no spooky reference rot.
- **Removes processed before adds in a single call.** Counter-
  intuitive at first — but ensures that a payload that says
  "remove L2, add a new line" computes the new line's number
  from the post-remove state. Without this, a remove-then-add
  pair could collide on the same number.
- **Pending rows don't enter the table data structure** until
  saved. They live in a parallel `pendingAdds` array on the
  client. This keeps the read-only "current truth" view of the
  table (the persisted lines) cleanly separable from the
  unsaved-edit overlay, mirroring how `lineDrafts` works for
  cell-level edits.
- **Empty-description pending rows are silently dropped on
  save.** A user who clicks "Add line" then changes their mind
  doesn't need to also remember to discard the row — saving
  with empty draft = same as not adding. Explicit rejection
  fired on the backend only kicks in if the client somehow
  tries to send an explicitly empty description.
- **No bulk-add / paste-CSV.** Out of scope for the manual-
  correction loop. Bulk-onboard belongs in a future "import
  invoices" surface, not the per-job review screen.

What's deferred:

- **Reorder lines.** No customer has asked; LHDN doesn't care
  about row order; deferred until someone needs it.
- **Restore-deleted toggle.** Once saved, removed lines are
  truly gone (the DB row is deleted). The audit event records
  the line number; full restoration would need a soft-delete
  pattern, which we'll add only if the use case appears.
- **Per-line `is_user_added` flag.** We could mark which lines
  came from extraction vs human-added in the UI; not done
  because the per-field confidence column already carries that
  signal (1.0 = user-asserted) and visually nothing about a
  user-added line should differ from a corrected-extracted line.

---

### Slice 27 — Background chain verification

The audit chain has been verifiable on demand since Slice 21
(`POST /api/v1/audit/verify/`). This slice adds the second half:
a Celery beat task that verifies the chain on a schedule
regardless of customer activity, and a "last verified" trust
footer on the audit log page that surfaces the result. Together
they let the customer see "we last verified the chain X minutes
ago" without ever clicking anything — the trust signal is
ambient instead of on-demand.

Backend:

- **`ChainVerificationRun`** model (system-level, no
  ``organization`` column — the chain is global). Records every
  run, manual or scheduled, in a single table. Fields: status
  (`ok` / `tampered` / `error`), source (`scheduled` / `manual`),
  events_verified, started_at, completed_at, error_detail.
  Migration `audit/0004_chainverificationrun`. No RLS — read by
  any authenticated session via the service, which strips
  operational fields (``error_detail``) before returning.
- **`apps.audit.tasks.verify_audit_chain`** — `@shared_task` on
  the `low` queue. Calls `run_scheduled_chain_verification`,
  which is a thin wrapper around the shared
  `_run_chain_verification` core. The core runs the chain
  walker under super-admin elevation, catches
  `ChainIntegrityError` (→ status=tampered with the offending
  sequence in `error_detail`) and any other exception (→
  status=error with the exception type+message). The run is
  recorded for *every* outcome — silent failure on a trust
  surface is worse than an explicit "we tried at T, here's what
  happened".
- **Manual verify path now writes a run row too.**
  `verify_chain_for_visibility` (the customer-triggered call
  from Slice 21) was refactored to use the same
  `_run_chain_verification` core with `source=manual`. The
  audit page's "last verified" surface unifies both kinds of
  trigger — whichever ran most recently, that's what shows.
- **System-level audit event** `audit.chain_verified` is
  emitted with `organization_id=NULL`, `actor_type=service`,
  `actor_id=audit.verify_audit_chain`, `payload.source=scheduled`.
  Manual runs continue to emit user-scoped events for the
  customer's own log. The two coexist on the chain without
  duplicating; tenants don't see system events under RLS.
- **`latest_chain_verification`** service returns the most
  recent run in a customer-safe shape: status, ok, source,
  events_verified, timestamps, support_message. Never
  `error_detail`; never the offending sequence number.
  `GET /api/v1/audit/verify/last/` exposes it.
- **Celery Beat schedule** in `settings.base`:
  `AUDIT_CHAIN_VERIFY_SECONDS` (default 6h, env-overridable for
  dev) drives the cadence. The beat container is a new service
  in `infra/docker-compose.yml` — single instance, since
  multiple beats would dispatch each tick more than once. Beat
  itself does no work; the task runs on the general worker via
  the `low` queue.

Frontend:

- **Audit page footer** (`/dashboard/audit`) now surfaces the
  latest verification under the chain-status badge: "Last
  verified 12 minutes ago · scheduled run" when the background
  task has run, "All audit events verified — your chain is
  intact." (or the tamper message) immediately after the user
  clicks Re-verify, and "Background verification runs every six
  hours." when no run has happened yet.
- **`api.latestAuditVerification()`** + `LatestVerification`
  type. The page fetches once on mount, and after a manual
  verify completes, refetches so the footer reflects the just-
  completed run.
- **CTA wording adapts**: "Verify chain integrity" before any
  run is observed, "Re-verify now" after — same button, same
  endpoint, just the right framing for the state.

Tests: 12 new (311 passing total). Service: clean chain →
status=ok with the verified count + system audit event with
`actor_type=service` + `organization_id=NULL` + payload
records `source=scheduled`. Tampered chain → status=tampered
with the sequence in `error_detail` (operational only). Celery
task path under `CELERY_TASK_ALWAYS_EAGER` → invokes the
service end-to-end, run row exists. Manual run via
`verify_chain_for_visibility` → writes a run row with
`source=manual`. `latest_chain_verification` → returns None
before any run, returns sanitised shape after (no
`error_detail`). Tampered run → customer-facing surface omits
the sequence entirely. Endpoint: `GET /verify/last/` → 200
with `{"latest": null}` before any run, returns latest with
sanitised shape after; unauthenticated → 401/403; no active
org → 400.

Verified live with Playwright: signed up fresh on a reset audit
table. Triggered the scheduled task once via shell so the dev
DB has a run on it. Visited /dashboard/audit — the chain badge
showed "4 events on the chain" with "Last verified just now ·
scheduled run" beneath it (success-tinted). Clicked "Re-verify
now"; badge updated to "5 events on the chain" with "All audit
events verified — your chain is intact." A new
`audit.chain_verified` event appeared in the table at the
top, scoped to the user (manual run). Beat container also
verified to be running and dispatching at the configured
cadence.

Durable design decisions:

- **One run table for both manual and scheduled.** A separate
  `ManualVerificationRun` + `ScheduledVerificationRun` would
  give a clean type distinction at the cost of forcing every
  surface ("show me the latest", "list runs") to UNION two
  tables. Since the surfaces only ever care about which one
  ran most recently regardless of source, the unified table
  with a `source` column is the right shape. The constraint
  this puts on the future: if scheduled and manual diverge in
  what they store, we'll have to split — but they share the
  same chain-walker, the same outcomes, and the same UI
  representation, so divergence is unlikely.
- **No retries on the task.** Same reasoning as
  `extraction.extract_invoice`: a transient DB failure is
  recorded as `status=error` and visible on the next page
  load; the next beat tick re-attempts naturally. A retry
  storm on a cryptographic check buys nothing.
- **`error_detail` never reaches customers.** It carries the
  offending sequence number (which under our global chain
  could belong to another tenant) and exception messages
  (which may carry environmental detail). The customer
  surface gets the same generic "tampering detected; contact
  support" message Slice 21 established. Operations sees
  `error_detail` via the audit table directly.
- **Recording `error` runs (not just ok/tampered).** Silent
  failure on a trust surface is worse than visible failure.
  If the database hiccupped during the verify, the page should
  show "Last verification errored at T — operations notified"
  rather than "Last verified at T-6h" (because the older run
  was the previous *successful* one). Today the latest-run
  query is unconditional `ORDER BY started_at DESC LIMIT 1`
  for exactly this reason — even errored runs surface.
- **Six-hour default cadence.** Frequent enough to detect
  tampering within a meaningful window, rare enough that even
  a multi-million-event chain finishes well under one
  interval (the walker is O(N) over events, the chain itself
  is the bottleneck). Tunable per-environment via
  `AUDIT_CHAIN_VERIFY_SECONDS`; dev overrides to seconds for
  testing.
- **Beat as its own container.** Mixing beat into a worker is
  technically possible (`celery worker -B`) but every guide
  warns it's a footgun: a worker restart loses scheduling, a
  multi-worker fleet ends up with multiple beats. One
  dedicated single-instance beat container is the
  unambiguous shape.

What's deferred:

- **Run history page.** The DB has every run; the UI surfaces
  only the latest. A "verification history" page (or a
  filter on the audit log page for `audit.chain_verified` —
  which already works) is out of scope; the current trust
  signal is the freshness of *one* run.
- **Operations alerting on tamper.** Right now a `tampered`
  run only logs to ops via `logger.error` and surfaces on the
  audit page. Paging on-call or filing a ticket should wire
  through a notification service when one exists — the
  detection is in place, the channel isn't.
- **Beat-schedule dynamic config.** `AUDIT_CHAIN_VERIFY_SECONDS`
  is read at startup. Changing the cadence requires a beat
  restart. A django-celery-beat-style DB-backed schedule
  would make this dynamic; deferred until a second
  scheduled task lands and the env-var pattern starts to
  feel restrictive.

---

### Slice 28 — Notification bell + ambient summary popover

The topbar has had a bell icon since Slice 7 that did literally
nothing — clicking it was a no-op. This slice makes it work by
turning it into a single ambient surface for "is there anything
I should look at right now". No new backend; reuses the inbox
list endpoint (Slice 25) and the latest-verification endpoint
(Slice 27).

Frontend:

- **`NotificationBell`** component (in
  `frontend/src/components/shell/NotificationBell.tsx`) replaces
  the dumb `<Bell>` button in `AppShell`. Owns: the badge state,
  the popover state, click-outside + Escape close, and the data
  fetch.
- **Popover content** has two sections, both deep links:
  - **Chain integrity** — single row with the
    success/error/neutral icon and a one-line message
    (`Chain verified 11m ago.` / `Tampering detected.
    Operations notified.` / `No verification yet — first run
    within six hours.`). Whole row links to `/dashboard/audit`.
  - **Open inbox items** — count + first 5 items (reason
    label + invoice number + buyer + relative time). Each row
    deep-links to `/dashboard/jobs/<id>` for that invoice. A
    "View all in inbox →" footer links to `/dashboard/inbox`.
    Empty state shows "Inbox zero — nothing waiting on you."
- **Badge** on the bell — count of open inbox items (signal
  green; "9+" when over). A separate small red dot appears in
  the corner when the latest chain verification is not ok, so
  a chain alert never gets buried under a high inbox count.
- **Refresh discipline**: fetch on mount, fetch every 60s, and
  fetch on popover open. The on-open refresh closes the
  obvious gap where a user uploads a PDF and immediately opens
  the bell — without it, they'd see stale data until the next
  poll fired.
- **No new types or API calls** — the existing `api.listInbox`,
  `api.latestAuditVerification`, `InboxItem`, and
  `LatestVerification` cover everything.

Tests: none new. The two endpoints this consumes are already
covered by Slice 25 (inbox list) and Slice 27 (latest
verification). Component testing isn't part of the codebase
yet; verified live with Playwright.

Verified live with Playwright: signed up fresh. Empty popover
showed "Chain verified 13m ago." (background task already
ran on dev DB) and "Inbox zero — nothing waiting on you.".
Dropped a synthetic empty PDF; both `structuring_skipped`
and `validation_failure` inbox items got created via the
existing pipeline. Reopened the bell — popover updated to
"2 open items" with both rows visible and the green "2"
badge appeared on the bell. Clicked the first item; the
page navigated to `/dashboard/jobs/<that-invoice's-job>`,
exactly the right deep link.

Durable design decisions:

- **Bell aggregates only what already has a real surface.**
  Chain integrity → audit log page. Inbox items → inbox page
  + per-job review page. The bell isn't a *channel*, it's a
  *summary* — it never invents a piece of state that doesn't
  also exist on a dedicated page. This keeps the contract
  simple: the bell's job is "make me look up", not "tell me
  the news in full".
- **Polling, not real-time.** A WebSocket subscription would
  let the badge update the moment an inbox row appears or the
  beat task finishes. It would also more than double the
  delivery surface (browser reconnect, server-side fanout,
  back-pressure) and earn its complexity only when customers
  actually ask to be paged within seconds. Two cheap GETs
  every minute beats premature realtime. The on-open refresh
  closes the immediate-action gap that would otherwise feel
  laggy.
- **Open-item count is the badge; chain alerts are a dot.**
  A combined "total things to look at" badge is misleading
  when the components have different urgencies — a tampered
  chain is much more serious than five open structuring
  skips. Splitting them lets the eye triage at a glance.
- **No "mark as read" / dismissal model.** Inbox items have
  their own resolve action; chain alerts auto-clear when the
  next verification comes back ok. The bell reflects current
  state, not an event log — there's nothing to "read".

What's deferred:

- **Refresh-on-action.** If the user uploads a PDF, the badge
  doesn't update until the next 60s poll or until they open
  the bell. A global event bus could fire on
  ingestion/validation completion. Deferred — the on-open
  refresh covers the user's actual gesture; the badge being
  one minute stale on the dashboard isn't user-facing
  surprising.
- **Per-event types beyond inbox + chain.** Notifications
  about invoice state transitions ("submitted to LHDN",
  "rejected") will land naturally when the submission
  service ships — they'll fold into the same popover by
  adding sections, not by replacing the architecture.
- **Email / push channel.** The bell is the in-app
  surface; email/push wires through whatever notification
  service handles outbound channels later. The DATA_MODEL.md
  `Notification` model exists but isn't yet populated
  outside this in-app aggregation.

---

### Slice 29 — Ollama field structuring (local + cloud)

The first non-Anthropic field-structure adapter — and the one
that makes the launch shape *actually finish* without depending
on a paid API key. The same adapter handles both local Ollama
(`http://host.docker.internal:11434`) and Ollama Cloud
(`https://ollama.com`); host + key + model are per-engine
credentials, not separate code paths.

Backend:

- **`apps.extraction.adapters.ollama_adapter.OllamaFieldStructureAdapter`**
  implements the existing `FieldStructureEngine` capability ABC.
  Reads host / api_key / model from `Engine.credentials` with env
  fallbacks (`OLLAMA_HOST`, `OLLAMA_API_KEY`, `OLLAMA_MODEL`) so a
  super-admin can rotate without a redeploy and dev can boot from
  `.env` alone. POSTs to `{host}/api/chat` with `format: "json"`
  and `stream: false`.
- **Cloud-host detection**: when `host` contains `ollama.com`,
  the adapter requires an api_key and raises `EngineUnavailable`
  if missing, rather than letting the cloud return a 401 deep in
  the pipeline. The local path omits the `Authorization` header
  entirely (local Ollama treats Bearer tokens as a protocol
  error).
- **Defensive JSON parsing**: strip ```json fences if present,
  flatten nested dict/list values to JSON-text rather than crashing,
  return `{}` on parse failure (the validation rules then fire
  required-field issues and the inbox lifecycle handles the
  "this needs a human" message). Same approach as the Claude
  adapter so the contract is uniform.
- **PII safety**: HTTP 5xx responses do NOT echo the body into
  the `EngineUnavailable` exception. The body could quote our
  prompt, which embeds the invoice text — that would leak into
  audit/inbox detail. Status code only; body stays in the access
  log.
- **`apps.extraction.registry`**: factory registered. Same lazy-
  instantiate pattern as Claude.
- **Migration `extraction/0004_seed_ollama_structure`**: registers
  the `ollama-structure` engine row + a routing rule with
  **priority 50** (lower number = higher priority in the
  router). Anthropic stays at priority 100 as fallback when
  Ollama is unconfigured / unreachable. No credentials seeded
  in the migration — those live in `.env` (dev) or
  `Engine.credentials` (production) so secrets never land in git.
- **`infra/docker-compose.yml`**: added `OLLAMA_HOST`,
  `OLLAMA_API_KEY`, `OLLAMA_MODEL` to the shared `backend-env`
  block so the worker, beat, signer, and backend all see the
  same credentials without a per-service stanza.
- **Diagnostics**: every call records `model`, `host`,
  `done_reason`, `input_tokens`, `output_tokens`,
  `total_duration_ns` on the EngineCall row — the engine activity
  page (Slice 22) surfaces them automatically.

Tests: 9 new (320 passing total). Local-path: no api_key, no
Authorization header, JSON parse + per-field confidence shape.
Cloud-path: api_key in credentials → Authorization header sent;
host is `ollama.com` and api_key missing → `EngineUnavailable`
at call site. Error paths: HTTP 5xx → exception with status code
only, no body echo (asserted by checking sensitive prompt
fragments don't appear in the exception); httpx.ConnectError →
`EngineUnavailable`; malformed JSON → empty fields with 0.0
confidence (no crash); fenced JSON parses cleanly.
Credential resolution: `Engine.credentials` beats env fallback;
env fallback used when credentials are blank. The structuring
test that previously asserted `engine == "anthropic-..."` now
asserts `"ollama-structure"` to reflect the new launch primary.

Verified live with the actual sample PDFs:

- Smoke-tested the adapter against `gemini-3-flash-preview` via
  Ollama Cloud — synthetic 5-line invoice text produced 8/8
  populated fields with the cloud key. ~3.8s total, 218 input /
  728 output tokens, model + host + token counts in diagnostics.
- Ran all 4 sample invoices (`docs/sample invoices/*.pdf`,
  gitignored) through the dashboard. Telekom Malaysia invoice
  populated 11+ fields correctly: invoice number, issue date,
  due date, currency `RM`, supplier `Telekom Malaysia Berhad`,
  buyer `SKYRIM SDN BHD`, addresses, subtotal `139.00`, tax
  `8.34`, grand total `147.35` — all at 85% confidence.
- Inbox went from **8 rows** in the previous live test
  (structuring_skipped + validation_failure per invoice) to
  **4 rows** (validation_failure only) — proof that structuring
  succeeded on every invoice. The remaining 4 errors / 2
  warnings are real LHDN issues (missing supplier/buyer TIN on
  this 2022 invoice; line items not yet extracted).

Durable design decisions:

- **One adapter for local + cloud.** The temptation was to ship
  `OllamaLocalAdapter` and `OllamaCloudAdapter` as separate
  classes — different deployment story, different error
  signatures. The wire format is identical, though, and the
  difference (host string, presence of api_key) is data, not
  behaviour. One adapter + per-engine credentials means a
  super-admin can swap a customer from local to cloud (or
  rotate keys) without code changes. The classes-per-vendor
  smell goes away.
- **Cloud-host detection by substring**, not by a `is_cloud`
  flag in credentials. The host `https://ollama.com` is the
  fact; everything else (whether to require a key, whether to
  send Authorization) is derived. Adding an `is_cloud` flag
  would let the two get out of sync — a host of
  `https://ollama.com` with `is_cloud: false` is nonsense the
  schema would accept.
- **`format: "json"` not function-calling / tool use.** Ollama's
  function-calling support varies by model and adds a layer of
  protocol that doesn't earn anything for our schema-on-demand
  use case. JSON mode + a tight prompt + defensive parsing is
  enough — and it works on every cloud model in the catalogue.
- **No retry on the adapter.** The Celery task that wraps
  structuring (`extraction.structure_invoice`) is configured
  with `max_retries=0` for the same reason as the rest of the
  pipeline: the state machine transitions eagerly, blanket
  retries skip with the job mid-state. If Ollama errors, the
  routing fallback (Anthropic) gets a chance; if both fail, the
  pipeline records `structuring_skipped` and the inbox surfaces
  it. Real retries land later gated on a richer "is this safe
  to retry?" signal.
- **Cost stays at 0 for now.** Ollama's response doesn't return
  a billable amount; the cloud bills monthly per model usage,
  not per call. Reconstructing per-invoice cost from token
  counts requires a per-model price table the catalogue doesn't
  publish stably. We keep `cost_micros=0` and rely on token
  counts in diagnostics for spend reconstruction later.

What's deferred:

- **Vision via Ollama** (e.g. qwen3-vl, gemma vision). The
  catalogue includes vision-capable models, but this slice is
  text-structure only. A second adapter implementing
  `VisionExtractEngine` against the same `/api/chat` endpoint
  with image content blocks lands when needed.
- **Cost calibration.** Token counts in diagnostics are
  recorded; turning them into dollars-per-call requires a price
  table per model and a periodic refresh. Phase 5 polish.
- **Local Ollama smoke test in CI.** The tests mock httpx, so
  CI doesn't need Ollama. A separate "Ollama is reachable"
  health check could ship later; not blocking.

---

### Slice 30 — Line-items-aware structuring prompt

The Slice 29 live test surfaced a real bug: the Telekom invoice
populated 11 header fields but **zero line items**, even though
the actual PDF clearly shows two charges. The prompt was the bug
— it told the model "all values are extracted strings", so when
the model saw `line_items` in the schema it returned an empty
string instead of an array. This slice fixes the prompt and
locks the new behaviour in tests.

Backend:

- **`apps.extraction.prompts.build_field_structure_prompt`** —
  shared prompt builder consumed by both Ollama and Claude
  adapters. Splits the schema into header fields (string values)
  and the `line_items` structured key (JSON array with its own
  documented sub-schema). The line-item sub-schema (description,
  quantity, unit_of_measurement, unit_price_excl_tax,
  line_subtotal_excl_tax, tax_type_code, tax_rate, tax_amount,
  line_total_incl_tax, classification_code) lives in the same
  module so adapters and tests share one source of truth.
- **`OllamaFieldStructureAdapter`** + **`ClaudeFieldStructureAdapter`**
  + **`ClaudeVisionAdapter`** all now call the shared builder.
  Inline prompt strings deleted; the only adapter-specific bit
  is *how* the prompt is wrapped (text-only HTTP body for
  Ollama, mixed document+text content blocks for Claude).
- **`max_tokens` bumped 2048 → 4096** on the Claude paths so a
  long invoice with many line items doesn't get truncated. Ollama
  has no max_tokens cap by default, so it picks up the longer
  output naturally.
- **JSON-payload parsing**: both adapters now keep `line_items`
  as a parsed list internally, JSON-encode it back to a string
  on the way out so the `StructuredExtractResult.fields:
  dict[str, str]` contract is preserved. The receiver
  (`submission._materialise_line_items`) handles both
  "raw is the list" and "raw is a JSON-encoded string" — keeping
  the list intact while in-flight saves a round-trip.
- **Confidence heuristic refined**: `"[]"` and `"{}"` (the
  JSON-encoded empty list / empty dict) are treated as
  "not populated" so a model that returned an empty array for
  line_items doesn't fraudulently get scored 0.85.

Tests: 4 new (324 passing total, was 320). The prompt builder
tests pin down the contract without coupling to exact wording:
flat fields are listed; `line_items` is announced as a JSON
array with documented sub-fields when present; the section is
omitted when not in schema; the prompt asks for clean JSON
(no prose, no fences). Existing adapter tests pass unchanged
since they mock httpx and don't assert on the prompt body.

Verified live: re-uploaded `invoice 5.pdf` (Telekom Malaysia)
with the new prompt + worker restart. Line items populated:

| # | Description       | Qty    | Unit Price | Tax  | Total  |
|---|-------------------|--------|------------|------|--------|
| 1 | Business High Sp… | 1.0000 | 109.00     | 6.54 | 115.54 |
| 2 | Business Voice :… | 1.0000 | 30.00      | 1.80 | 31.80  |

Sum 147.34 vs grand total 147.35 — one-cent rounding consistent
with Telekom's own breakdown. Validation went 4 errors → 3
errors as the "needs at least one line item" issue cleared. The
remaining 3/2 are real LHDN compliance issues (currency code
"RM" vs "MYR", missing supplier/buyer TIN on a 2022-era
Telekom invoice, due-date-in-the-past warning) — exactly what
they should be.

Durable design decisions:

- **Prompt is a shared contract, not adapter trivia.** The
  service decides the schema; the adapters decide how to ask
  models. Putting the prompt in `apps.extraction.prompts`
  rather than inlining it in each adapter means a schema
  change (add/remove a field, refine `line_items` sub-keys)
  edits one file and every model sees the consistent ask.
- **Sub-schema lives next to the prompt, not imported from
  submission.** Cross-context imports are forbidden; even a
  documentation-only shared list of line-item field names
  goes through the bounded-context boundary. The prompt
  module owns its own copy and the test pins drift if the
  two ever diverge.
- **The vision prompt reuses the structuring builder.** Vision
  inputs (image / PDF document block) provide the source
  document; the schema + instruction layer is identical to
  text structuring. The builder takes a `text=` argument that
  the vision path stuffs with `"(see attached document)"` —
  one builder, both paths, no drift.
- **`"[]"` is not populated.** A model returning an empty
  array for line items is a real outcome (single-line invoice
  with everything in totals, etc.) but it shouldn't score the
  same as "we successfully extracted three line items". The
  confidence heuristic now demotes empty containers to 0.0,
  so the per-field confidence dot in the UI stays honest.

What's deferred:

- **More structured keys.** Future LHDN fields like
  `allowances` or `discount_breakdown` will follow the
  same pattern — branch in `prompts.py`, no adapter touch
  required.
- **Per-line confidence.** Today `line_items` gets one overall
  0.85 / 0.0 score. Per-line confidence would need either the
  model returning it explicitly (most don't) or a calibrated
  validator (e.g. line-total-equals-quantity-times-unit-price
  → high confidence). Phase 5 polish.

---

### Slice 31 — EasyOCR for images + scanned-PDF fallback

The first local OCR engine, and the one that closes a real
routing gap from Slice 1: ingestion accepts ``image/jpeg /
image/png / image/webp`` uploads, but the only seeded
TextExtract route was for ``application/pdf`` (pdfplumber). An
image upload would hit ``NoRouteFound`` and fail silently. This
slice plugs that hole and queues EasyOCR for future scanned-PDF
escalation.

Backend:

- **`apps.extraction.adapters.easyocr_adapter.EasyOCRAdapter`** —
  in-process OCR via the `easyocr` Python package. Implements
  `TextExtractEngine` for image MIMEs (jpeg / png / webp) and
  `application/pdf` (rasterised page-by-page). PDF
  rasterisation goes through `pypdfium2` — a single Python wheel
  with no system deps, much leaner than the
  pdf2image+poppler-utils alternative. 200 DPI render is the
  empirical sweet spot between accuracy on small fonts and
  speed.
- **Reader caching**: `easyocr.Reader(...)` loads the language
  model into memory at construction time (multi-second + 64 MB).
  We cache it as a module-level singleton with a thread-lock
  guard so the second adapter call within a worker process is
  instant.
- **Confidence**: averaged over EasyOCR's per-detection scores.
  Unlike pdfplumber's "0.95 vs 0.10 floor" heuristic, EasyOCR's
  confidence is calibrated by the model itself; we trust it.
- **Languages**: English only at launch. Bahasa Malaysia uses
  Latin script so the English model handles it well; adding the
  Malay language pack is a one-line change when needed.
- **Page cap**: 30 pages per PDF, matching `MAX_LINE_ITEMS` in
  submission as a sanity ceiling so a 100-page accident doesn't
  blow the request budget.
- **`apps.extraction.registry`**: factory registered alongside
  the existing pdfplumber / Claude / Ollama adapters.
- **Migration `extraction/0005_seed_easyocr`**:
  - Registers the `easyocr` engine row (capability `text_extract`,
    cost 0).
  - Routing rule **priority 100** for `image/jpeg,image/png,
    image/webp` — the launch primary for images. Replaces the
    silent "image upload fails" behaviour with a real OCR pass.
  - Routing rule **priority 200** for `application/pdf` —
    fallback for the future. The router today picks the lowest
    priority and doesn't auto-fall-back, so this rule sits
    behind pdfplumber's priority 100. When the "escalate
    text_extract on low confidence" hook lands, the rule is
    already in place and only the routing logic edits.
- **Dependencies**: `easyocr>=1.7,<2.0` and `pypdfium2>=4,<5`
  added to `pyproject.toml`. The transitive torch (CPU) +
  opencv-python-headless adds ~250 MB to the worker image and
  EasyOCR downloads its English model (~64 MB) on first use,
  cached in the container under `easyocr/`. **`tool.uv.required-environments`**
  declared (Linux x86_64, Linux aarch64, macOS arm64) so the
  lockfile resolves without trying to find Intel-macOS torch
  wheels that don't exist.

Tests: 9 new (333 passing total, was 324). Image path: jpeg /
png / webp all OCR-and-return; per-detection confidences are
averaged correctly; blank image → 0 confidence + no crash.
PDF path: pages rasterised through a mocked pypdfium2,
per-page text concatenated, per-page confidences averaged,
diagnostics carry `mode=pdf`, `pages_ocrd`, `render_dpi`. Error
paths: malformed PDF → `EngineUnavailable` from the rasterise
step; unsupported MIME → clear `EngineUnavailable`. Reader
caching: across two image calls the fake `Reader.__init__` is
constructed exactly once. EasyOCR-not-installed:
`EngineUnavailable` raised at the call site rather than
crashing on import.

Verified live: image-MIME path exercised against the Telekom
invoice (rasterised to JPEG via Chromium first), end-to-end
OCR → Ollama structuring → review screen with structured
fields populated. The Engine activity page (Slice 22) shows
the EasyOCR call with timing + character count diagnostics.

Durable design decisions:

- **EasyOCR over Tesseract.** Tesseract is leaner (~30 MB
  binary vs ~300 MB pulled by EasyOCR's torch dep) but its
  accuracy on real-world Malaysian invoices (mixed-language,
  low-contrast, varied fonts, photographed receipts) is
  noticeably worse. EasyOCR's torch CPU + transformer
  detector produces clean text where Tesseract returns
  fragments; the cost is image weight, not request latency.
- **`pypdfium2` over `pdf2image` + poppler.** pdf2image is the
  conventional choice but requires `poppler-utils` as a system
  dep installed via apt. pypdfium2 is a single wheel; no
  Dockerfile changes, no per-arch headache.
- **Module-level Reader singleton, not a Django cache or
  lru_cache.** The Reader holds GPU/CPU model weights — a
  Django cache would either pickle them (slow, fragile) or
  miss every time. A module-level singleton scoped to the
  worker process matches the natural lifecycle: one
  initialisation per worker, reused across all jobs that
  worker handles.
- **Routing priority for PDFs is 200, not 100.** EasyOCR could
  technically handle every PDF, but for native-text PDFs
  pdfplumber is faster and cheaper (no model inference). The
  priority ordering makes pdfplumber the launch primary and
  positions EasyOCR as the future escalation target. The
  alternative — leaving the PDF rule out entirely until the
  escalation slice ships — would force a second migration
  later; this way the wiring is in place.
- **English only, not multi-language by default.** A
  multi-language Reader takes longer to initialise and
  produces worse confidence scores per detection (the model
  has to disambiguate). Malaysian invoices use Latin script;
  English handles them well. Multi-language is a credentials-
  driven knob (`Engine.credentials.languages`) when a
  customer's documents need it.

What's deferred:

- **Low-confidence pdfplumber → EasyOCR escalation.** The
  routing rule is in place; the pipeline hook isn't yet.
  When a real scanned-PDF customer arrives, the hook becomes
  one branch in `extraction.services._maybe_escalate_to_vision`
  (rename to `_maybe_escalate`, try OCR before vision).
- **Region-of-interest cropping.** EasyOCR currently OCRs the
  whole page, including watermarks and decorative elements.
  Cropping to invoice-relevant regions (header, line items
  table, totals) would speed things up and cut noise.
  Earnings-the-complexity later.
- **Per-region confidence.** EasyOCR returns per-detection
  bounding boxes — we discard them. A future "show me where
  the model read this from" UI overlay would consume the
  bbox data.
- **Multi-language pack.** Add `["en", "ms"]` (Malay) to the
  Reader credentials when a customer's documents include
  non-Latin script.

---

### Slice 32 — pdfplumber → EasyOCR → vision escalation chain

The vision escalation from Slice 12 jumps straight from "low
pdfplumber confidence" to a paid Anthropic API call. Slice 31
landed EasyOCR with a priority-200 fallback rule for PDFs but
the routing logic didn't actually consult fallback rules.
This slice wires the chain: scanned PDF → pdfplumber returns
sparse text → EasyOCR runs locally → if OCR returns confident
text, the regular FieldStructure (Ollama) path proceeds
unchanged. Only if OCR also fails do we pay for vision.

Backend:

- **`pick_fallback_engine(capability, mime_type, exclude_engine_id)`**
  in `apps.extraction.router` — returns the next-priority
  matching rule that doesn't reference a given engine. Built on
  the same internal helper as `pick_engine`; raises
  `NoRouteFound` when no fallback exists. Documented as the
  hook for any future "try a second engine" routing pattern.
- **`_maybe_escalate_to_ocr`** in `apps.extraction.services` —
  runs after the primary text extract, before vision
  escalation. Returns `OCREscalationOutcome(applied=True,
  replacement_result=…)` if a fallback engine ran and its
  confidence cleared `EXTRACTION_OCR_THRESHOLD` (default 0.5,
  env-overridable). When applied, the OCR's `TextExtractResult`
  *replaces* the primary `result` — vision escalation then
  evaluates against the OCR's confidence (which has just
  cleared the threshold), so it skips. Recorded engine name
  becomes `"pdfplumber+easyocr"` so the audit trail makes the
  chain visible.
- **Failure modes graceful**: missing fallback rule, missing
  adapter, `EngineUnavailable`, vendor exception, sub-threshold
  OCR confidence — every branch records the reason as an
  `ingestion.job.ocr_escalation_skipped` audit event and falls
  through to vision. The pipeline never breaks because OCR
  couldn't run.
- **Audit events**: `ingestion.job.ocr_escalation_started`
  (chain initiated), `ingestion.job.ocr_escalation_applied`
  (OCR text used as primary), `ingestion.job.ocr_escalation_skipped`
  (OCR ran but didn't help). Same naming pattern as the
  existing vision escalation events so an audit log filter for
  `*escalation*` shows the full chain history.

Tests: 4 new (337 passing total, was 333). Low pdfplumber
confidence + good OCR → OCR text replaces primary, vision
NOT called, audit log records the chain. Low pdfplumber +
sub-threshold OCR → both run, vision then escalates as
fallback. High pdfplumber confidence → neither OCR nor vision
runs (native PDF unaffected). OCR `EngineUnavailable` →
audit-and-skip with the unavailability reason in the inbox-
visible payload, then vision runs.

Verified live: pre-existing PDF flow on `invoice 5.pdf`
(Telekom — pdfplumber returns 95% confidence) → OCR not
triggered, structured-fields path unchanged from Slice 30
behaviour. The OCR escalation only fires on scanned PDFs;
the dev DB has none, but the Slice 31 image upload exercise
(EasyOCR on a JPEG render of the same invoice) verifies the
adapter end-to-end.

Durable design decisions:

- **OCR substitutes the primary `result`, not just produces
  side text.** The simpler API would record OCR text under a
  separate field on the IngestionJob ("ocr_text") and let
  downstream code pick. We instead replace `result` so the
  rest of the pipeline (vision threshold check, FieldStructure
  task queue, audit recording) is unchanged. Single source of
  truth for "what's the text we structured against" stays
  `IngestionJob.extracted_text`.
- **Combined engine name (`"pdfplumber+easyocr"`).** Same
  pattern as Slice 12's `"pdfplumber+anthropic-claude-sonnet-vision"`
  for vision escalation. The name encodes the chain step;
  filterable downstream.
- **OCR ran but sub-threshold counts as "skip", not "applied".**
  A 0.20-confidence OCR result is barely better than nothing
  for downstream structuring — the model would hallucinate
  fields off garbled fragments. Treating it as "OCR couldn't
  read this either" and falling through to vision matches the
  customer-friendly outcome.
- **Threshold = 0.5 for both OCR and vision.** The same
  threshold could theoretically diverge (OCR is local + free
  so we might want a more permissive threshold), but a single
  knob simplifies operator reasoning and there's no calibration
  data yet showing a different value works better. Two settings
  exist in code so they CAN diverge later without a refactor.

What's deferred:

- **Per-tenant threshold tuning.** Some customers have mostly
  native PDFs (tighten threshold to 0.7 to avoid wasting OCR
  cycles); others have mostly scans (drop to 0.3 to escalate
  earlier). Phase 5 polish; needs calibration data.
- **OCR model swap by file class.** A future "this is a
  receipt photo, use the receipt-tuned model" routing rule
  could match on diagnostic signals (page count, image
  dimensions). Today's single English Reader handles
  everything.

---

### Slice 33 — Super-admin auth + route protection

The foundation slice for the platform-operator surface: a
distinct namespace (`/admin` on the frontend, `/api/v1/admin/`
on the backend) gated by `User.is_staff`. No new tables, no
cross-tenant queries yet — that's Slice 34. This slice just
wires up the auth gate so subsequent admin pages have a clean
shell to mount under.

Backend:

- **`apps.administration.permissions.IsPlatformStaff`** — DRF
  permission class that returns 403 (not 404) when the
  authenticated user has `is_staff=False`. The 403/404
  distinction matters for the frontend: 403 means "you're
  signed in but not staff", which we want to surface as a
  redirect to the customer dashboard, not as a generic
  "endpoint missing".
- **`apps.administration.views.admin_me`** — `GET /api/v1/admin/me/`.
  Returns `{id, email, is_staff, is_superuser}`. The frontend's
  /admin route hits this on mount; the 200/403/401 outcome
  drives the auth flow.
- **`apps.administration.urls`** — mounted at `/api/v1/admin/`
  in `zerokey/urls.py`. Distinct from Django's built-in admin
  at `/admin/` (Django's auto-model-admin is at the project
  root, this is the customer-facing platform-admin API).
- **Reuse `User.is_staff`**, not a new role tier. Django
  already has the field; the model manager keeps it in
  lockstep with `is_superuser`. We treat `is_staff` as the
  single source of truth for "platform operator".

Frontend:

- **`/admin/page.tsx`** — overview landing. Welcome card
  ("you're signed in as platform staff") + "Coming next"
  inventory of the upcoming admin pages.
- **`AdminShell`** in `frontend/src/components/admin/`. Distinct
  from `AppShell`: dark sidebar with a small "ADMIN" badge,
  topbar reads "Platform admin", no organization switcher
  (admin runs across all tenants). Sidebar nav has Overview
  active and Platform Audit / Tenants / Engines as `soon`
  placeholders for the upcoming slices.
- **Auth flow** in the shell:
  - On mount, fetch `/api/v1/admin/me/`.
  - 401 → redirect to `/sign-in?next=/admin`.
  - 403 → redirect to `/dashboard` (you're authenticated, just
    not staff).
  - 200 → render the children.
  - Other errors → render an "admin unreachable" stub with a
    sign-in button, rather than dead-ending.
- **`api.adminMe()`** + `AdminMe` type added to the API client.
- **Topbar avatar menu** has a "Switch to customer view" link
  back to `/dashboard`. Staff users typically belong to an
  organization too (they're testing the customer surface),
  so the round-trip is one click.

Tests: 4 new (341 passing total, was 337). Unauthenticated →
401/403 from the API. Customer user (is_staff=False) → 403
with the IsPlatformStaff message. Staff user → 200 with the
identity dict. Staff user without an active-org session →
still works (admin namespace doesn't need an org context).

Verified live with Playwright on three flows:

  - Unauthenticated `/admin` → redirect to `/sign-in`. ✓
  - Staff user (`admin@symprio.com`, `is_staff=True`) →
    sees the admin overview at `/admin`, with the dark
    sidebar + green "ADMIN" badge + the three coming-next
    cards. ✓
  - Customer user (fresh signup) → `/admin` redirects them
    to `/dashboard` (the 403 path). ✓

Durable design decisions:

- **`is_staff` as the staff flag, not a new field.** A custom
  `is_platform_admin` field on User would let the two diverge
  from Django's built-in `is_staff`. Using the existing field
  keeps the audit story simple (one boolean) and lets
  Django's createsuperuser command work out of the box.
- **`/admin` lives at the app root, not under `/dashboard`.**
  An admin landing under `/dashboard/admin` would inherit the
  customer shell and produce confusing navigation. A separate
  top-level route lets the admin shell be entirely distinct
  (different colors, different topbar, no org switcher).
- **403, not 404, for non-staff.** A non-staff user should
  see "this isn't your route" (and get redirected), not
  "this doesn't exist" (which is misleading). The frontend
  uses 403 as the staff-only-redirect signal everywhere
  consistently.
- **Frontend redirect on 403, not "you're not staff" message.**
  A non-staff customer hitting `/admin` is almost always a
  typo or a stale bookmark — bouncing them to their actual
  dashboard is friendlier than a hostile error page.
- **Admin shell does the auth check once, page-level code
  doesn't repeat it.** The shell is the choke point; pages
  that wrap themselves in `<AdminShell>` get the 401/403
  redirects for free. No per-page boilerplate.

What's deferred:

- **Promotion / demotion via UI.** Today, promoting a user
  to staff is a manual `is_staff = True` on the User row
  (Django admin or shell). A super-admin-promotes-another
  flow lands once we have multiple platform operators.
- **Audit log of admin sign-ins.** Customer sign-ins are
  audited via `auth.login_success`; the admin shell uses the
  same login flow, so the event already records. A separate
  `admin.session_started` event would be cleaner but is
  cosmetic.
- **Two-factor auth on admin accounts.** Production-only.
  Phase 5 hardening alongside SAML/SSO for staff.

---

### Slice 34 — Super-admin platform audit log

The first page that does cross-tenant work — every audit event
across every tenant in one view, filterable by action type and
tenant ID. Distinct from the customer audit page (Slice 20)
which is RLS-scoped to one organization. The cross-tenant reads
themselves are audited so the chain records who looked at what
and with which filters.

Backend:

- **`apps.administration.services.list_platform_events`** —
  cross-tenant audit list. Elevates to `super_admin_context`
  for the duration of the query so RLS lets it read every
  org's rows, then drops elevation and emits an
  `admin.platform_audit_listed` system-level audit event with
  the filter parameters (but never the underlying event
  payloads — those are the *thing being audited*; recursive
  inclusion would be noise). Returns AuditEvent rows
  newest-first, sequence-cursor pagination.
- **`list_platform_action_types`** + **`count_platform_events`**
  follow the same pattern. Action-type listing audits itself
  (`admin.platform_action_types_listed`); count doesn't (it
  fires on every page load and would drown the chain in
  noise — the count is a header KPI, not an investigation
  surface).
- **`apps.administration.serializers.PlatformAuditEventSerializer`**
  is distinct from the customer-facing audit serializer. It
  exposes `organization_id` on every row (the whole point of
  cross-tenant aggregation) and otherwise mirrors the
  customer shape. The customer serializer never returns
  organization_id by design — every event a customer sees is
  their own org by construction.
- **Endpoints**:
  - `GET /api/v1/admin/audit/events/?action_type=…&organization_id=…&limit=&before_sequence=`
  - `GET /api/v1/admin/audit/action-types/`
  Both gated by `IsPlatformStaff`.

Frontend:

- **`/admin/audit/page.tsx`** — operator surface mirroring the
  customer audit page (Slice 20) but with the cross-tenant
  affordances:
  - **Tenant column** on every row showing the organization
    UUID prefix; clicking it filters the list to that tenant.
  - **Tenant filter input** at the top accepting a full UUID
    paste — for chasing a specific incident.
  - **System events** (`organization_id=NULL`) get a
    "system" badge instead of a UUID.
  - **Header note** "Listing this page is itself audited."
    so the operator knows the meta-loop is in play.
- The shell's "Platform audit" nav item drops its `soon`
  badge — the page is live.
- `api.adminListPlatformAuditEvents` + `adminListPlatformActionTypes`
  client methods + `PlatformAuditEvent` type.

Tests: 9 new (350 passing total, was 341). Unauthenticated →
401/403. Customer 403. Staff sees rows from all tenants. Filter
by `organization_id` returns only that tenant. Filter by
`action_type` is exact-match. Invalid `limit` → 400. The act
of listing fires `admin.platform_audit_listed` with the
filters in the payload. Action-types endpoint returns the
distinct set across all tenants; second call sees the first
call's audit event in its result.

Verified live with Playwright on `admin@symprio.com`: signed
in, navigated to `/admin/audit`. Page rendered 50 events from
multiple tenants (different UUID prefixes visible in the
Tenant column), with the dropdown showing 16 distinct action
types from across the platform, and a "Load more" button
beneath the table. Filtering by clicking a tenant's UUID
narrows the view to that org's events.

Durable design decisions:

- **Two serializers, not one with a `?include=` flag.** The
  customer-facing serializer never exposes organization_id;
  the platform serializer always does. Trying to merge them
  with a query-param toggle would make per-call introspection
  the load-bearing security check. Keeping them separate
  pushes the audience boundary into a static type/import
  graph: importing `PlatformAuditEventSerializer` is a clear
  "this is admin-side" signal in code review.
- **Cross-tenant reads emit their own audit event.** This is
  the "who watches the watchmen" loop: a staff user reading
  every tenant's data is itself an event the chain should
  record. The audit is per-call (one event per page load),
  with the filters in the payload and the result count for
  context — but never the underlying event payloads (those
  are the thing being audited, including them would explode
  the chain volume).
- **The count endpoint is not audited.** Header KPIs fire on
  every page load and aren't investigatory — the count is
  for orientation, not for chasing a specific event. The
  list / action-types endpoints ARE audited because they
  produce information that drives further investigation.
- **Tenant filter is a UUID input, not a tenant-name search.**
  Looking up tenants by name belongs on the (upcoming)
  tenant list page (Slice 35) where the operator can pick
  and click through. The audit page assumes the operator
  arrived with a specific tenant in mind — chasing a known
  incident.

What's deferred:

- **Tenant name resolution.** Today the Tenant column shows
  a UUID prefix. Resolving it to a legal name requires a
  second query per row (or a denormalized join). When the
  tenant list page lands (Slice 35) with a tenant lookup
  service, this page can render names instead of UUIDs.
- **Date-range filter.** Customers don't typically need it
  but operators investigating incidents do. Cheap to add
  later; the indexes already support it.
- **Export.** A "download as CSV" button for compliance
  audits. Phase 5 polish.

---

### Slice 35 — Super-admin tenant directory

The triage surface for "show me everyone, narrow by name or
TIN, see who's idle vs active." The companion to Slice 34's
audit log: that's the per-event view, this is the per-tenant
view, and they deep-link to each other.

Backend:

- **`apps.administration.services.list_platform_tenants`** —
  cross-tenant directory builder. One query for the org rows,
  three aggregation queries for member count, lifetime
  ingestion count, and last-7-days ingestion count, plus a
  `Max(created_at)` for last-activity. Total cost is five
  small queries regardless of tenant count, which scales
  cleanly. Search is a case-insensitive substring against
  `legal_name` OR `tin`.
- Audited as `admin.platform_tenants_listed` with the search
  string and result count. Same self-monitoring pattern as
  Slice 34.
- **`GET /api/v1/admin/tenants/?search=&limit=`** — staff-only
  endpoint. Returns the denormalised dict per tenant with the
  shape the UI needs (no client-side counting).

Frontend:

- **`/admin/tenants/page.tsx`** — table of every tenant with
  legal name + email, TIN, subscription state badge,
  member count, total uploads, last-7-days uploads, last
  activity timestamp (relative), and a "View →" link that
  deep-links to `/admin/audit?org=<uuid>`.
- **Active tenants surfaced first** — the sort puts orgs
  with non-zero last-7-days uploads above idle ones; ties
  break alphabetically.
- **Search bar** with 250 ms debounce so typing doesn't
  hammer the API. Case-insensitive against legal name or
  TIN.
- **Subscription state badge** uses the colour palette from
  the design system: success-green for `active`,
  signal-amber for `trial`, slate for everything else.
- **Audit page now reads `?org=`** — the tenant-list "View"
  link populates the audit page's tenant filter, completing
  the drill-through. Implemented via Next 14's
  `useSearchParams` wrapped in a `Suspense` boundary (app-
  dir requirement).
- The shell's "Tenants" nav item drops its `soon` badge.

Tests: 8 new (358 passing total, was 350). Auth gate (401/403/
customer-403). Staff lists every tenant. Member + ingestion
counts populate correctly. Search by legal-name substring
narrows results. Search by TIN substring narrows results.
Invalid `limit` → 400. Listing fires
`admin.platform_tenants_listed` with the search term in the
payload.

Verified live with Playwright (`admin@symprio.com`): visited
`/admin/tenants`, 25 tenants visible, sorted by recent
activity. Searched "slice" → 18 matches. Cleared search,
clicked View on first row → routed to
`/admin/audit?org=b144bd47-...` with the Tenant filter
pre-populated and "No events for these filters" rendered
because that fresh tenant has no audit events yet.

Durable design decisions:

- **Aggregations on the backend, not via N+1 from the UI.**
  A naive frontend would render the table then issue one
  count query per tenant (member_count, jobs, recent jobs).
  At 100 tenants that's 300+ queries on a single page load.
  The backend computes them in five `.annotate(Count())`
  passes, regardless of tenant count.
- **Search at the backend, not client-side filter.** The
  same naive frontend would fetch every tenant and filter
  in the browser. Fine at 25 tenants, painful at 5,000.
  The endpoint accepts `search=` so the work scales with
  the result size, not the catalogue size.
- **Activity-first sort.** A platform operator opens this
  page to chase what's *happening* on the platform, not to
  look up Quiet Co Sdn Bhd. Sorting recent uploads to the
  top makes the relevant row visible above the fold.
- **`last_activity_at` falls back to `Organization.created_at`.**
  An org that's never uploaded still has *some* "last
  activity" — the moment they signed up. The column never
  reads "never" for a real org.
- **Drill-through via query param, not router state.** A
  `?org=` URL is bookmarkable (paste it in chat with a
  colleague) and survives a refresh. Pushing the tenant ID
  through router state would lose both properties.

What's deferred:

- **Tenant detail page.** Today the View link goes to the
  audit log filtered by org. A dedicated detail page (KPIs,
  recent invoices, member list, raw timeline) is the
  natural next step but is a slice in its own right.
- **Inline tenant impersonation.** "Sign in as this tenant
  for 30 minutes" is the standard SaaS-admin shortcut; we
  don't have the impersonation token machinery yet. When it
  lands the row gets an "Impersonate" button.
- **Bulk actions.** Suspend, pause billing, send a
  broadcast email — Phase 5 polish once we have those
  channels.

---

### Slice 36 — Super-admin engine credentials management UI

The closing slice in the super-admin UI arc (Slices 33–36).
Lets the operator rotate per-engine API keys, swap models,
toggle status, and adjust cost baselines without touching
`.env` or restarting workers. The Engine.credentials JSONField
already exists (Slice 12) and the runtime resolver
(`extraction.credentials.engine_credential`) already prefers
DB over env — this slice plugs the missing UI for the
"super-admin populates the row" leg.

Backend:

- **`apps.administration.services.list_engines_for_admin`** —
  cross-engine catalogue. Returns one dict per Engine with
  name, vendor, capability, status, cost, description, plus
  recent-call counts (last 7 days, success vs total) joined
  from EngineCall. Crucially: the `credentials` JSON values
  are *never* serialised — instead, each row carries a
  `credential_keys: {key: bool}` map indicating "is this key
  set?" without leaking the value. Audited as
  `admin.engines_listed`.
- **`update_engine`** — atomic editor with
  `select_for_update` lock. `field_updates` is allowlisted
  to `{model_identifier, status, cost_per_call_micros,
  description}`; `name`, `vendor`, `capability`,
  `adapter_version` are immutable from the UI (they're
  wiring contracts; changing them silently could orphan
  routing rules). `credential_updates` accepts
  `{key: value}`; an empty-string value deletes the key.
  No-op detection skips the audit + save when nothing
  actually changed (stops the chain from filling with
  re-saves of the same form). Audited as
  `admin.engine_updated` with the FIELD names changed and
  the credential KEY names changed — never the values.
  Same PII-clean convention as `invoice.updated`.
- **Endpoints**:
  - `GET /api/v1/admin/engines/`
  - `PATCH /api/v1/admin/engines/<uuid>/`
  Both gated by `IsPlatformStaff`.

Frontend:

- **`/admin/engines/page.tsx`** — one card per engine. Header
  shows name + status pill + capability tag + vendor / model
  / adapter; right side shows recent call activity (7-day
  count + success count). Footer has the credential-keys
  summary (each key as a chip — green when set, slate when
  unset) and an Edit button.
- **In-place editor** (expanded card): status select
  (active / degraded / archived), model identifier text
  input, and one input per credential key with placeholder
  "•••• (set)" or "(unset)". The form starts empty for
  every credential field; typing into one rotates that
  value, leaving others untouched. Empty-string submit
  clears the key. Sustained "values are write-only"
  contract: the operator can rotate but never read.
- **Status pill** uses success/warning/slate colour family
  for active/degraded/archived. Capability tag mirrors the
  same vocabulary as the audit / engine-activity pages.
- The shell's Engines nav item drops its `soon` badge —
  every nav item is now live.
- `api.adminListEngines()` + `adminUpdateEngine()` clients
  + `AdminEngine` type added.

Tests: 11 new (369 passing total, was 358). List endpoint:
auth gate (401/403/customer-403), staff sees engines with
redacted credential keys (the test asserts plaintext values
do NOT appear anywhere in the JSON response). Update
endpoint: status change, credential rotation, credential
clear (empty-string), reject non-editable field with the
allowlist error message, reject invalid status, 404 on
unknown engine, no-op detection (re-submitting the same
api_key produces no audit row), customer 403 + verify the
engine wasn't actually mutated.

Verified live with Playwright (`admin@symprio.com`): visited
`/admin/engines`, all 5 seeded engines visible
(anthropic-claude-sonnet-structure, ollama-structure,
easyocr, pdfplumber, anthropic-claude-sonnet-vision) each
with the right status pill, capability badge, vendor info,
description, and recent-call counts in the right rail. The
"No credentials configured (engine may run on env fallbacks)"
note correctly reflects truth — the seeded engines have
empty Engine.credentials and currently rely on env vars set
via `.env`. Once an operator rotates through this UI, the
DB takes over.

Durable design decisions:

- **Credential values are never returned, ever.** A future
  operator might be tempted to add a "view current value"
  toggle for confirming what's stored. We refuse — the API
  has no read path for credential plaintext. Rotation is
  the only operation. This matches the standard
  credential-rotation UX (browser password managers, AWS
  IAM access keys) and means a UI bug or mis-rendered
  expanded card can't leak the value to the page DOM.
- **Audit logs the field/key NAMES, not values.** The same
  PII-clean convention every customer-side audit event
  follows. An operator rotating an api_key produces an
  `admin.engine_updated` event with
  `credential_keys_changed: ["api_key"]` and zero leak of
  the new value.
- **Allowlist of editable fields, not deny-list.** `name`,
  `vendor`, `capability`, `adapter_version` are *contracts*
  that other code reads. Renaming an engine through this UI
  would invisibly break routing rules pointing at the old
  name. The allowlist forces a code change for any new
  operator-editable field, which is the right friction.
- **No-op detection skips the audit row.** Saving an empty
  form (or resubmitting unchanged values) is a common UX
  pattern; if we didn't filter, the audit chain would fill
  with non-events. The detection is by-value (if the new
  value equals the existing value, skip), not by-form-input
  (which would naively count "empty input" as a clear).
- **Five seeded engines, all visible.** The catalogue
  doesn't filter — even archived engines appear (their
  status pill makes their state obvious). An operator
  investigating "why is this engine not running?" can see
  it greyed-out without going through Django admin.

What's deferred:

- **New-engine creation from the UI.** Today engines are
  only registered via data migrations (the right place for
  wiring contracts). A "create engine" button could be
  added, but it would mostly serve as a footgun — registering
  an engine without an adapter class to back it produces a
  broken row.
- **Routing rule editor.** EngineRoutingRule has the same
  shape (priority + mime allowlist + fallback engine) but
  isn't editable from the UI yet. Lands in a follow-up
  slice when the operator surfaces start needing per-tenant
  routing overrides.
- **Cost calibration view.** The cost_per_call_micros
  field is editable but there's no comparison surface ("here's
  what you've actually been spending vs. what you set as
  baseline"). The data exists on EngineCall rows; the
  visualisation is Phase 5 polish.

---

### Slice 37 — Admin overview KPIs + operator-only sign-in routing

The super-admin overview was a placeholder ("you're signed in
as platform staff" + coming-next cards). This slice fills it
with real cross-tenant KPIs the operator looks at first when
opening the console, and removes the customer-view dependency
from the staff sign-in flow — staff users go straight to
`/admin`, not via `/dashboard`.

Backend:

- **`apps.administration.services.platform_overview`** —
  cross-tenant KPI aggregator. Counts tenants (total + active-
  in-last-7d), users, ingestion jobs (total / 7d / 24h),
  invoices (total / 7d / pending review), open inbox items,
  audit events (total / last 24h), and engines (total + status
  breakdown). Plus a per-engine 7-day call breakdown
  (success / failure / unavailable) for the engine-health
  table. All under `super_admin_context` elevation, audited as
  `admin.platform_overview_viewed` with a counter snapshot but
  no PII. Light payload so the audit volume stays sane on a
  frequently-loaded page.
- **`GET /api/v1/admin/overview/`** — staff-only endpoint
  returning the dict above.
- **`UserSerializer` now exposes `is_staff`** so the frontend
  knows where to route the user post-login.

Frontend:

- **`/admin/page.tsx`** rewritten — real KPIs in a 4-column
  responsive grid, each card linking to the relevant detail
  page (`Tenants → /admin/tenants`, `Open inbox → /admin/audit?action_type=inbox.item_opened`, etc.). The
  `Open inbox` card goes warning-tinted when count > 0;
  `Engines` card goes warning-tinted when any are degraded.
  Below the grid: an engine-health table (last 7 days, top 8
  engines by call volume) showing per-engine success rate
  with health colour (success ≥ 80% green, < 80% red, 0
  failures = green 100%).
- **`/sign-in` routes by `is_staff`** — the login response
  now carries `is_staff`, and the post-login redirect goes
  to `/admin` for staff and `/dashboard` for customers.
  Staff sign-in skips the customer dashboard entirely; they
  don't have or need an active org context.
- **AdminShell drops the "Switch to customer view" link.**
  Platform staff are operator-only by intent; the avatar
  menu is now just "Sign out". (Staff who really need to
  verify a customer flow can sign out and sign in as a
  customer; we don't make that gesture easy on purpose,
  because mixing roles in one session was the source of
  several routing edge-cases in previous slices.)
- **`api.adminOverview()`** + `PlatformOverview` type added.

Tests: 4 new (373 passing total, was 369). Auth gate (401/403/
customer-403). Staff sees the full KPI block with non-zero
counts. Loading the overview emits an audit event with the
counter snapshot in the payload.

Verified live (`admin@symprio.com`): signed in, landed on
`/admin` directly (not `/dashboard`). Overview rendered with
25 tenants / 34 ingestion jobs / 27 invoices / 21 open inbox
(warning-tinted) / 115 audit events / 5 engines / 27 users.
Engine activity table showed pdfplumber + ollama + easyocr at
100% success and the two anthropic engines at 0% (correct —
no Anthropic API key is configured, so every call fails fast
with `EngineUnavailable`). Avatar menu confirmed "Switch to
customer view" is gone.

Durable design decisions:

- **Staff sign-in skips `/dashboard` entirely.** Earlier
  slices treated staff users as "regular customer who also
  has admin powers". That model leaks (sessions need an
  active_organization_id, navigation has to thread two
  shells, sign-out has to reason about which shell you came
  from). Treating staff as "operator only, no customer
  context" eliminates the cross-shell ambiguity. Customers
  who get promoted to staff still sign in cleanly — they
  just need to sign out and back in if they want to test
  customer flows, which is the right friction.
- **The KPI payload is small but the queries aren't trivial.**
  Eight separate aggregates (counts + status breakdown +
  per-engine call rollup) run on every overview load. We
  pay for it because the operator looks at this page
  multiple times a day, and putting these on a 30-second
  client poll would multiply the chain noise from
  `admin.platform_overview_viewed` events. Better to fetch
  once on mount and reload manually.
- **Each KPI card is a deep link, not just a number.** The
  overview is the site map for the admin namespace —
  clicking "Open inbox 21" takes you to the audit log
  pre-filtered to `inbox.item_opened` events; clicking
  "Tenants 25" takes you to the tenant directory. No need
  for a separate nav-with-counts pattern.
- **Engine health colour by success rate, not raw failure
  count.** A 1000-call engine with 50 failures (95%
  success) is healthier than a 10-call engine with 5
  failures (50% success); the colour reflects rate, not
  count.
- **"Switch to customer view" was a footgun, not a feature.**
  The avatar menu had it in Slice 33 because staff at the
  time were customer-shaped users who happened to be
  flagged. Now that sign-in routes them away from
  `/dashboard`, the back-door doesn't fit; removing it
  matches the new mental model.

What's deferred:

- **Tenant detail page.** The Tenants card links to the
  list; a per-tenant drilldown (recent invoices, member
  list, raw timeline, impersonation button) is the natural
  next slice. The audit page partial-filter does the
  minimum job for now.
- **Time-series charts.** The KPIs are point-in-time
  counts; trends would help the operator spot a
  rising-failure-rate engine before it hits the 80%
  cutoff. Phase 5 polish; the underlying data is on the
  EngineCall rows.
- **Auto-refresh.** The overview fetches once on mount.
  Polling it every 30s would surface real-time changes
  but multiply the audit chain entries from the
  `admin.platform_overview_viewed` event.

---

### Slice 38 — Per-tenant detail page

The tenant directory's "View" link used to drop the operator
into a filtered audit log; this slice gives them a real
per-tenant landing instead — identity, KPIs, member list,
inbox-by-reason rollup, recent ingestion jobs, recent invoices.
The audit drill-through stays as one click away.

Backend:

- **`apps.administration.services.tenant_detail`** — per-org
  snapshot. One read of the Organization row plus six
  scoped aggregates (members, jobs total / 7-day, invoices
  total / pending, inbox open, audit count) plus three list
  fetches (top 50 members, top 10 jobs, top 10 invoices),
  plus an inbox-open-by-reason rollup. All inside one
  `super_admin_context` block. Audited as
  `admin.tenant_detail_viewed` with the tenant id on the
  `affected_entity_id` field so the chain is
  filterable-by-tenant later (e.g. "show me every staff
  view on this org").
- Audit payload carries the tenant's legal_name + the stats
  snapshot but never PII (no contact email, phone, or
  address). Test asserts the contact email doesn't appear
  in the payload.
- **`GET /api/v1/admin/tenants/<uuid>/`** — staff-only.
  Returns 404 on unknown id; staff cannot brute-force
  enumeration through this endpoint.

Frontend:

- **`/admin/tenants/[id]/page.tsx`** — full detail layout:
  - **Header**: legal name, TIN code chip, subscription state
    badge, "Cert uploaded" badge if applicable, contact
    email + phone with mail/phone icons, timezone +
    currency + join date.
  - **KPI grid** (4 cards): Members, Ingestion jobs (with
    7-day count), Invoices (with pending review count),
    Open inbox (warning-tinted when > 0; success-tinted
    when zero).
  - **Audit deep-link button** spanning full width — "Open
    the audit log filtered to this tenant (N events)"
    routes to `/admin/audit?org=<uuid>`.
  - **Members section** (left half): table of email + role
    + join date.
  - **Inbox-by-reason section** (right half): list of
    `validation_failure: 3`, `structuring_skipped: 1`,
    etc. — quick triage view.
  - **Recent ingestion jobs table**: filename, status, engine,
    confidence (rendered as `95%`), timestamp.
  - **Recent invoices table**: invoice number, buyer, status,
    grand total with currency, timestamp.
- **404 state** — clean "Tenant not found" card with a "Back
  to tenants" button instead of dead-ending.
- **Tenant directory's "View" link upgraded to "Open"** and
  deep-links to the new detail page rather than the audit
  filter.
- `api.adminTenantDetail()` + `TenantDetail` type added.

Tests: 5 new (378 passing total, was 373). Auth gate
(401/403/customer-403). Staff sees full detail with member
emails + roles + ingestion job stats + invoice list. Unknown
tenant id → 404. Detail view emits `admin.tenant_detail_viewed`
with tenant id on `affected_entity_id` and PII (contact_email)
NOT in payload.

Verified live (`admin@symprio.com`): from `/admin/tenants`
clicked "Open" on the "Fresh" tenant. Detail page rendered with
TIN code, TRIALING badge, contact email + timezone + currency
+ joined date, 4 KPI cards (1 Member, 7 Ingestion jobs, 0
Invoices, 0 Open inbox success-tinted "Inbox zero — nothing
waiting"), the audit drill-through callout, the members list
("fresh@example.com OWNER"), inbox-by-reason ("Nothing open"),
7 ingestion jobs in the recent-jobs table with status +
confidence + timestamps. The 404 path also confirmed by
visiting an all-zeros UUID.

Durable design decisions:

- **Tenant id on `affected_entity_id`, not in the payload.**
  The audit event for "staff viewed tenant X" makes the
  tenant the *subject* of the event. Audit chain queries
  for "who viewed this tenant" should be filterable
  natively without parsing JSON; using the field that's
  exactly for that (`affected_entity_id`) earns the index
  for free.
- **PII excluded from the audit payload.** Even though the
  detail itself returns contact email/phone/address (the
  operator needs them), the audit row of "I viewed this
  tenant" doesn't need them — the tenant id + legal name
  is enough to identify what was viewed. Including PII
  there would amplify the audit chain's exposure surface
  (a chain leak shouldn't cascade into PII leak).
- **Stats inline in the response, not a separate
  `/stats` endpoint.** The detail page renders all the
  stats at once; round-tripping for them adds latency
  without improving the architecture. We pay for ~9
  queries on this page; that's fine for a low-traffic
  operator surface.
- **Inbox-by-reason rollup is a dict, not a list.** The
  React side iterates `Object.entries()` which is stable
  enough for a small set; using a dict keeps the wire
  shape minimal and lets future filters key directly into
  it.
- **Members capped at 50, jobs/invoices at 10.** The
  detail page is for triage, not browsing. A tenant with
  500 members or 1000 invoices isn't browsed here — the
  operator pivots to a search or the audit log instead.
  The caps keep the response size bounded.
- **Tenant directory's button reads "Open" not "View".**
  Microcopy distinction: "View" implied a passive read
  (like opening a row), "Open" implies entering a screen.
  The detail page has actions (audit drill-through,
  potential future impersonation), so "Open" matches.

What's deferred:

- **Impersonation.** Sign-in-as-this-tenant for 30
  minutes is the standard SaaS-admin shortcut; the
  underlying `super_admin_context` machinery exists but
  the impersonation token + reason-required UI gate is a
  separate slice.
- **Pagination on jobs/invoices.** Today the page shows
  the most recent 10. A full per-tenant invoice browser
  with pagination is a follow-up when an operator
  actually asks for it.
- **Edit tenant.** Today this is a read-only surface —
  legal name, contact email, etc. can't be edited from
  here. Editing customer-facing org metadata from the
  admin side is a privileged operation that deserves its
  own slice with an explicit reason field.

---

### Slices 39+40+41 — Privileged admin actions: members, tenants, system settings

Three slices shipped together because they share the same
"reason-required + redacted-credential" pattern and they
collectively turn the admin surface from read-only into
operationally functional.

**Slice 39 — Tenant member management.** Platform staff can
deactivate / reactivate a membership row and change its role
without going through the customer-side owner path. Used for
compromised accounts, departed employees, or fast-track
support tickets. `apps.administration.services.admin_update_membership`
takes membership id + optional `is_active` + optional
`role_name` + REQUIRED reason; raises `MembershipUpdateError`
with the allowlisted-roles message if the role name is
unknown. `PATCH /api/v1/admin/memberships/<uuid>/`. Audited
as `admin.membership_updated` with the membership id on
`affected_entity_id`. Tests: 9 covering the auth gate,
deactivate, role change, reason-required, at-least-one-field-
required, unknown role 400, unknown id 404, no-op skip.

**Slice 40 — Edit tenant.** Display + contact + state metadata
editable from the tenant detail page. `_EDITABLE_TENANT_FIELDS`
allowlist gates legal_name, contact_email, contact_phone,
registered_address, language_preference, timezone,
billing_currency, subscription_state, trial_state. Wiring fields
(id, tin) and customer-managed fields (sst_number, certificate_*)
are immutable from the admin side — those have stronger
constraints and a typo via the operator surface would corrupt
state. `PATCH /api/v1/admin/tenants/<uuid>/edit/`. Audited as
`admin.tenant_updated` — payload carries the field NAMES
changed and the reason; never the values (those can be PII —
contact_email, registered_address). Tests: 8 covering the auth
gate, update, reason-required, non-editable-field rejection,
unknown tenant 404, no-op skip, subscription state change.

**Slice 41 — System settings UI.** The biggest of the three.
Every platform-wide configuration namespace (LHDN MyInvois,
Stripe billing, Email/SMTP, branding, engine routing defaults)
editable from one screen with a unified credential-rotation
contract. `apps.administration.services.SYSTEM_SETTING_SCHEMAS`
declares the canonical namespaces + their field schemas
(key, label, kind: `string` or `credential`, placeholder).
Adding a new namespace = appending to that list; the UI
renders it automatically. Endpoints:

  - `GET /api/v1/admin/system-settings/` lists every namespace
    with redacted credential metadata (`{key: bool}` map of
    "is this set?" — never the value).
  - `PATCH /api/v1/admin/system-settings/<namespace>/` updates
    a namespace's values dict atomically with the same
    write-only credential contract the engines page uses. An
    empty-string value clears a key.

Frontend: **`/admin/settings/page.tsx`** — left rail of
namespace tabs (each shows credential-set count e.g.
"2/3 credentials set" in success-green, signal-amber, or
slate), right pane renders the active namespace as a
2-column field grid with credential password inputs that show
"•••• (set — type to rotate)" or "(unset)" placeholders. Per-
credential "Clear value" link sends an empty string with the
reason. Bottom bar has the required reason input + Save
button. Audited as `admin.system_settings_listed` /
`admin.system_setting_updated`. Sidebar nav now shows
"System settings" as a dedicated entry alongside Engines.

Tests across all three: 28 new (406 passing total, was 378).
Membership 9 + tenant edit 8 + system settings 11. Each test
class asserts the auth gate (401/403/customer-403), the
audit-payload-doesn't-leak-values invariant, and the no-op
skip behaviour.

Verified live (`admin@symprio.com`):

  - **Tenant detail "Edit tenant" button** opens an inline
    form with 8 editable fields (legal name, email, phone,
    timezone, currency, subscription state, trial state,
    registered address textarea) + reason input. Cancel
    closes the form; Save patches and refreshes.
  - **Member row "more" menu** opens a privileged action
    panel — role select + Save Role + Deactivate (or
    Reactivate when inactive) + Cancel + a required reason
    input. Reason validation fires before the API call.
  - **System settings page** renders 5 namespace tabs with
    credential-set counts. Email / SMTP shows 7 fields
    (smtp_host, smtp_port, smtp_user, smtp_password —
    password type, from_address, from_name, use_tls).
    Privileged-action explainer + reason-required input
    visible at the bottom.

Durable design decisions (across all three):

- **Reason is a required field on every privileged write.**
  Member deactivation, role change, tenant edit, system-
  setting rotation — all require the operator to type a
  reason. The reason lands in the audit payload (truncated
  to 255 chars). This is the audit story's load-bearing
  property: an operator can be asked "why did you change X
  on Y?" and the answer is in the chain, not someone's
  Slack DM.
- **Field NAMES in audit payloads, never values.** The same
  PII-clean convention every customer-side audit event
  follows. A tenant rename → audit records
  `fields_changed: ["legal_name"]` + `reason`, not the
  before/after legal_name strings. A credential rotation →
  records `credential_keys_changed: ["secret_key"]`, never
  the new key. Tests assert sensitive strings don't appear
  in the audit payload.
- **Allowlist of editable fields, not deny-list.** Every
  privileged write declares an explicit allowlist. New
  operator-editable fields require a code change to land in
  the allowlist, which is the right amount of friction.
- **Schema-driven settings UI.** The frontend doesn't have
  per-namespace logic — `SYSTEM_SETTING_SCHEMAS` is the
  source of truth and the page renders whatever's in the
  schema. Adding a sixth namespace is a 10-line change in
  one Python file; no React touch needed.
- **Credentials are write-only end-to-end.** API never
  returns plaintext; UI uses password-type inputs; clearing
  is an explicit gesture (empty-string POST or "Clear value"
  link). Same contract whether the credential lives in
  `Engine.credentials` or `SystemSetting.values`.
- **No-op detection skips the audit row.** Saving an
  unchanged form is a common UX gesture; if we audited it
  the chain would fill with non-events. Detection is by
  value-comparison, not form-state.

What's deferred:

- **Test the SMTP wiring.** A "send a test email" button on
  the email namespace would close the obvious next gap —
  today the operator saves credentials and crosses fingers.
  Ships when the actual email-sending path lands (currently
  the platform doesn't send any emails).
- **Stripe webhook subscription wizard.** Stripe webhooks
  need a public URL + a signing secret on Stripe's side.
  The settings page captures the secret; an "in-product
  wizard" that creates the Stripe webhook on the operator's
  behalf is Phase 5 polish.
- **Per-tenant SystemSetting overrides.** Today every
  namespace is platform-wide. A future "this customer uses
  their own LHDN credentials, not ours" pattern would need
  a `tenant_id` column on SystemSetting — explicitly out of
  scope for now.
- **Bulk member actions.** Deactivate-all, transfer
  ownership in one gesture — Phase 5 polish; the per-row
  actions cover the common case.
- **Field-level diff in audit payload.** Today we record
  field NAMES that changed; recording the BEFORE values
  (sanitised) would help reconstruct a state mid-stream.
  Adds chain volume; deferred until needed.

---

### Slice 42 — 14-day sparklines on admin KPI cards

KPI cards used to be point-in-time counts. Now they each
carry a 14-day daily sparkline below the primary number so
the operator can spot a rising/falling trend at a glance —
"open inbox is growing day-over-day" or "ingestion volume
just collapsed for tenant X".

Backend:

- **`_daily_count_sparkline(queryset, date_field, days)`** —
  shared helper in `apps.administration.services` that buckets
  any queryset by day, gap-fills missing days with zero, and
  returns a list of `{date, count}` dicts oldest-first. Same
  shape `audit.services._daily_sparkline` already returns for
  the customer audit-stats KPI tile so the React side reuses
  one component.
- **`platform_overview` adds 4 sparklines** — ingestion,
  invoices, audit, inbox. Tenants/users/engines stay
  point-in-time (their interesting numbers are state, not
  flow).
- **`tenant_detail` adds an `ingestion_sparkline`** so a
  per-tenant volume drop is visible without leaving the
  detail page.

Frontend:

- **`<Sparkline>` component** in `components/admin/` —
  inline SVG bars (4px wide, 2px gap), accepts a points
  array + optional max + tone-coloured `barClass`. We use
  bars not a line because the typical platform-admin
  signal is "uneven daily volume" and bars communicate
  gaps more honestly than a line that interpolates through
  missing days.
- **KPI cards on `/admin` and `/admin/tenants/[id]`** render
  the sparkline between the primary number and the
  secondary text. Tone-coloured: `fill-warning/70` on the
  warning-tinted Open Inbox card, `fill-success/70` on
  success-tinted cards, `fill-slate-400` otherwise.

Tests: 1 new (407 passing total, was 406). Asserts each of
the four overview-level sparklines has 14 entries with
`date` + `count` in oldest-first order, gap-filled (zero
days included).

Verified live (`admin@symprio.com`): 4 sparklines visible on
`/admin` overview (ingestion, invoices, inbox, audit), 1 on
`/admin/tenants/<id>` (ingestion). The audit chain card
shows the bar sticking up on the most recent day, reflecting
the dev DB activity from today vs zero on prior days —
exactly the trend signal the operator wants to spot.

Durable design decisions:

- **Bars, not a line.** A line interpolates through missing
  days, suggesting smooth activity that didn't actually
  happen. Bars show gaps as gaps. For platform metrics
  where "we did nothing on Sunday" is a real fact, this
  matters.
- **14-day window, not 7 or 30.** Seven days of bars at 4px
  apiece is too narrow to be readable. Thirty days
  visualises a longer trend but pushes the bars below 3px
  wide, where the colour fights for visibility against the
  card background. 14 days hits the sweet spot — wide
  enough to see daily detail, short enough to fit cleanly
  in a card.
- **Sparklines on flow metrics only, not state metrics.**
  Tenant count and user count are state — "how many
  exist?" — not flow — "how many happened today?" A
  sparkline on tenant count would show a step function
  upward most days, which doesn't communicate anything
  useful. Flow metrics (jobs, invoices, audit events,
  inbox openings) ARE bursty and benefit from the trend
  view.
- **Tone colour from the card.** The sparkline inherits
  the card's tone (warning / success / neutral) so a
  warning-tinted Open Inbox card has warning-coloured
  bars, reinforcing the signal without adding visual
  noise.

What's deferred:

- **Per-engine sparklines on the engine activity table.**
  The overview's engine table is already informative with
  the success-rate column; sparklines would help operators
  see "this engine started failing yesterday" but the
  data shape (per-engine + per-day + per-outcome) is
  three-dimensional and doesn't fit a 4px-bar layout.
- **Rolling-week vs calendar-week.** Today the sparkline
  shows 14 *calendar* days ending today; an alternative is
  a rolling 14×24h window. Calendar days match the
  customer audit-stats convention, which is the right
  default.
- **Sparkline on the engine credentials page.** Could show
  per-engine call volume next to the "Edit" button. Not in
  scope.

---

### Slice 43 — Tenant impersonation with reason gate + time-limited session

The closing slice in the admin enhancement arc. Platform staff can
briefly act on behalf of a tenant for support purposes — investigating
a customer-reported bug, walking a finance team through a flow on a
call. Sessions are time-limited (30-min hard TTL, no extend gesture),
audited at start AND end, and surface a banner across every customer
page so the operator can never accidentally take an action thinking
they're a regular customer.

Backend:

- **`apps.administration.models.ImpersonationSession`** — id,
  staff_user_id, organization_id, started_at, expires_at, ended_at,
  ended_by_user_id, end_reason, reason. Indexed on
  `(staff_user_id, ended_at)` so "active impersonation by this
  staff?" is a fast point lookup; on `(organization_id,
  started_at)` for the future "show me every impersonation of
  this tenant" surface.
- **`start_impersonation(actor, organization_id, reason)`**.
  Reason required (truncated to 255 chars). Looks up the
  Organization under super-admin elevation; if found, ends any
  earlier active session for the same staff user (one
  impersonation at a time, no chaining), creates the row with
  `expires_at = now + 30min`, audits as
  `admin.tenant_impersonation_started` with the tenant's legal
  name + reason in the payload.
- **`end_impersonation(session_id, actor, end_reason)`**.
  Idempotent — ending an already-ended row is a no-op. Records
  duration in seconds on the audit event. End reasons:
  `user_ended` (operator clicked End), `expired` (auto-closed
  past TTL), `superseded_by_new_session` (operator started a
  new impersonation without ending the old one).
- **`get_active_impersonation_for_session(session_id)`** — used
  by the identity `/me/` endpoint to expose the impersonation
  context to the customer shell. Auto-closes expired rows on
  read so there's no separate cleanup job needed.
- **Endpoints**: `POST /api/v1/admin/tenants/<uuid>/impersonate/`
  (start, sets Django session keys), `POST /api/v1/admin/impersonation/end/`
  (end + clear session keys). Both staff-only.
- **Identity `UserSerializer` extended** with an `impersonation`
  field that returns the active context (`session_id`,
  `organization_id`, `tenant_legal_name`, `started_at`,
  `expires_at`, `reason`) or null. `is_staff` also exposed so
  the customer-side AppShell can know whether the user is
  legitimately staff vs spoofing.
- **No middleware enforcement of TTL** — the auto-close happens
  inside `get_active_impersonation_for_session`. Every customer
  endpoint already calls `/me/` indirectly through the React
  shell, so the next page load past expiry kills the session.

Frontend:

- **`ImpersonationBanner`** in `components/admin/`. Renders
  across the top of the customer AppShell whenever
  `me.impersonation` is non-null. Shows tenant legal name +
  reason + live MM:SS countdown to expiry + "End impersonation"
  button. Tone goes from warning amber to error red when the
  countdown hits zero. AppShell layout updated to flex-column
  so the banner stretches full-width above the sidebar.
- **Tenant detail page "Impersonate" button** — opens an inline
  warning-tinted card that explains the session terms ("read-
  write proxy for 30 minutes, every action audited, hard-
  expires"). Reason input is required; Start button stays
  disabled until reason is non-empty. On click, POSTs to the
  start endpoint and routes the operator to `/dashboard` —
  they're now seeing the customer dashboard scoped to that
  tenant's data.
- **End flow** — banner button POSTs to end endpoint, clears
  Django session keys, routes to `/admin`.
- `api.adminStartImpersonation()` + `api.adminEndImpersonation()`
  + `Me.impersonation: ImpersonationContext | null` type added.

Tests: 11 new (418 passing total, was 407). Auth gate
(401/403/customer-403). Reason required. Unknown tenant 404.
Start sets the Django session keys (`organization_id`,
`impersonation_session_id`) + creates an active row + emits
the `admin.tenant_impersonation_started` event with the
tenant's legal name + reason in payload + 30-min TTL.
Starting a second impersonation supersedes the first
(`end_reason="superseded_by_new_session"`). End clears Django
session + audits `admin.tenant_impersonation_ended` with
duration_seconds. End-when-no-active is a no-op (200, not
404 — idempotent). `/me/` includes the impersonation block
when active, returns null after end. Past-expires_at session
auto-ends on next `/me/` read with `end_reason="expired"`.

Verified live (`admin@symprio.com`): clicked Impersonate on
the "Fresh" tenant. Confirm card showed the 30-minute
warning + reason input. Typed a reason ("support ticket
#4421 — investigating extraction issue") and started. Routed
to `/dashboard` with the customer view scoped to Fresh's
data (7 ingestion jobs, sample.pdf entries visible). The
warning-tinted impersonation banner rendered across the top
showing "IMPERSONATING Fresh · support ticket #4421 …" + a
live countdown + End button. Clicked End → routed back to
`/admin`.

Durable design decisions:

- **No `extend` gesture.** A long support window needs a
  fresh start with a fresh reason, not a one-click
  extension. Prevents the "I'll just bump it 30 more
  minutes" pattern that erodes the audit story over hours.
- **Same User row throughout.** `request.user` stays the
  staff user during impersonation; only the session's
  `organization_id` changes. This means every customer-side
  audit event during the window records the staff user as
  the actor — the chain shows who actually did the thing,
  not who they were impersonating.
- **One impersonation at a time per staff user.** Starting
  a second supersedes the first with a clear end reason
  rather than running parallel sessions. Two simultaneous
  impersonations would make audit reconstruction painful
  ("which tenant was the staff user editing when this
  happened?").
- **Banner uses warning amber, not error red.** Until the
  session expires. Red is for "something is wrong"; amber
  is for "you are in an unusual mode". A staff member
  legitimately working a ticket shouldn't feel like they're
  triggering an error every page load. Red appears only
  when the countdown hits zero.
- **Auto-expire on read, not on a Celery beat.** The TTL
  enforcement is "the next /me/ refuses to honour the
  flag", which means a forgotten session in a closed
  browser tab is silently expired the next time anyone
  refreshes. No separate cleanup task; the chain stays
  consistent because the auto-close still emits the
  `admin.tenant_impersonation_ended` event.
- **Reason in audit payload, not field-level redacted.**
  Unlike most privileged actions where we record only
  field NAMES, impersonation reasons are the load-bearing
  audit signal — "why was this staff acting on Acme's
  behalf at 14:00?" The reason is short text (no PII
  shape) and capped at 255 chars; it's safe to include
  directly.

What's deferred:

- **Read-only impersonation mode.** A "view only" toggle
  would let staff inspect a tenant's data without write
  power. Today every impersonation is read-write. Phase
  5 polish; the audit trail makes a malicious staff write
  visible.
- **Impersonation history per tenant.** A dedicated table
  on the tenant detail page showing past impersonations.
  The data exists in `ImpersonationSession`; the UI is a
  follow-up.
- **Per-staff impersonation rate limiting.** "If a staff
  user starts more than 5 impersonations in an hour,
  flag it." Anti-abuse pattern; not needed for solo or
  small-team operations.

---

### Slice 44 — ExtractionCorrection model + automatic capture

The "learn from corrections" product claim was structurally
unsupported until now: every edit fired an `invoice.updated`
audit event but no queryable training data persisted. Per
DATA_MODEL.md §93 we needed `(field, original, corrected,
user, timestamp, engine)` rows to drive engine accuracy
analysis. This slice closes the gap with zero behaviour
change visible to end users.

Backend:

- **`apps.submission.models.ExtractionCorrection`** —
  TenantScopedModel with `invoice` FK, `field_name`,
  `original_value` + `corrected_value` (both JSON-encoded
  strings so type info round-trips), `extracted_by_engine`
  (denormalised from Invoice.structuring_engine for query
  speed), `user_id` (soft FK), `created_at`. Indexes on
  `(organization, field_name)` and `(extracted_by_engine,
  field_name)` for the per-engine accuracy reports the
  table is designed for.
- **Migration `submission/0005_extractioncorrection`** +
  **`0006_correction_rls_policy`** — RLS uses the same
  per-tenant pattern every other tenant-scoped table uses.
- **`update_invoice` captures corrections inline** — the
  helper functions `_apply_line_item_updates`,
  `_apply_line_item_removes`, `_apply_line_item_adds` each
  optionally accept a shared `correction_rows: list[]` and
  push `_build_correction(...)` rows during their normal
  loop. The header path appends in its own loop. After all
  edits land + the invoice saves, one `ExtractionCorrection.
  objects.bulk_create(correction_rows)` flushes. Inside the
  same `transaction.atomic()` so a save rollback unwinds the
  training rows too.
- **Naming convention**:
  - Header field → `"<field>"` (e.g. `"supplier_legal_name"`)
  - Line cell    → `"line_items[<n>].<field>"` (e.g.
    `"line_items[3].quantity"`)
  - Line add     → `"line_items[<n>]"` with `original=""`
    and `corrected=<JSON snapshot>`
  - Line remove  → `"line_items[<n>]"` with `original=<JSON
    snapshot>` and `corrected=""`
- **`_jsonify_value` helper** — Decimals stringify cleanly,
  date / datetime → ISO, dict / list → `json.dumps`,
  everything else → `str()`. None becomes empty-string so
  the column stays non-null (we don't need to distinguish
  null from blank — the audit chain has the truthful
  before/after).
- **`_serialise_line_for_correction`** captures a
  LineItem's editable fields as a compact dict for the
  add / remove correction snapshots.

Tests: 8 new (426 passing total, was 418). Header edit →
1 row. No-op edit → 0 rows. Multi-field edit → multiple
rows. Line cell edit → row with `line_items[N].field`
naming. Line add → row with `original=""` and JSON
snapshot in `corrected_value`. Line remove → mirror. Engine
attribution populated from `Invoice.structuring_engine`.
Blank-to-value is recorded as a correction (the training
signal "model missed this field").

Verified live: nothing visible — this is invisible
infrastructure. The persistence is correct (tested) and
the existing edit flows continue to work unchanged (all 68
prior submission tests still pass).

Durable design decisions:

- **Bulk-create after the save, not row-at-a-time.** A
  multi-field edit (10 line cells changed in one save) was
  going to be 10 INSERTs if we wrote inline. Accumulating
  rows in a list and writing one bulk_create at the end
  cuts that to one round-trip. Inside the existing
  transaction so atomicity is preserved.
- **JSON-encoded values, not separate typed columns.** The
  alternative — `original_decimal`, `original_string`,
  `original_dict` columns — explodes the schema for marginal
  query benefit. Storing as TEXT with `json.dumps`
  semantics keeps the table narrow and lets analysts
  decode at query time with `jsonb_path_query` or in pandas.
- **Engine name on the correction row, not just FK to
  Invoice.** Pure denormalisation for a future "which
  engine missed which field most often" report — joining
  through Invoice + EngineCall every time would be slow.
  The engine name on the correction is set at the moment of
  the correction, so even if the Invoice is later
  re-extracted with a different engine the historical
  attribution stays correct.
- **`user_id` soft FK, not `User` ForeignKey.** A user
  deletion (rare but possible — a customer expunges an
  account) must not cascade-delete their training history.
  The data is impersonal aggregated signal anyway — the
  user_id is for aggregation queries, not for joining back
  to a user.
- **No-op skip without comparing JSON.** The existing
  `update_invoice` already skips fields where the new
  value equals the existing value; the correction loop
  rides on the same comparison. A field that flickers (set
  to X, then set back to X by a save-no-changes click)
  doesn't pollute the training data.

What's deferred:

- **Per-engine accuracy dashboard.** The data is now
  populated; a chart showing "ollama-structure: 92%
  accuracy on supplier_tin" is a Phase 5 polish slice.
- **Feedback loop into engine routing.** Long-term, the
  correction rate per (engine, field) should feed the
  routing decision (e.g. demote engines whose corrections
  exceed threshold). Today the rows just accumulate.
- **Per-correction confidence delta.** The correction's
  effect on the engine's calibration could be weighted by
  the original confidence — a 0.95-confidence wrong
  prediction is worse than a 0.20 one. Not in the schema
  yet.
- **Correction surfacing in the customer audit log.** The
  `invoice.updated` event already carries the field NAMES
  changed; a deeper view that joins through to the
  `ExtractionCorrection` rows would give the customer a
  "history of edits to this invoice" page.

---

### Slice 45 — Customer Settings → Members tab + tenancy fix

The customer Settings page was a single-tab "Organization"
form. PRD Domain 6 + USER_JOURNEYS.md expect Members, API
keys, Notifications, Security tabs. This slice ships the
foundation (a tab strip across all settings sub-pages) and
the first new tab — Members. Includes a load-bearing fix to
the tenancy plumbing surfaced by the new code.

Backend:

- **`apps.identity.services.list_organization_members`** —
  active + inactive memberships for the active org with
  email + role + join date. Customer-side; reads under the
  user's regular tenant context (no super_admin elevation).
  Sorted oldest first so founders lead.
- **`update_organization_member`** — owner / admin updates
  another member's role or active state. Authorisation
  layered: owner / admin only; admins cannot change owners
  or promote to owner; users cannot self-change (route to a
  future profile flow). Audited as
  `organization.membership.updated` (distinct from the
  admin-side `admin.membership_updated` so analytics can
  split self-service vs operator changes). Field NAMES in
  payload only — same PII-clean pattern.
- **Endpoints**: `GET /api/v1/identity/organization/members/`
  + `PATCH /api/v1/identity/organization/members/<uuid>/`.
- **Tenancy bug fix**: `super_admin_context` was clearing
  BOTH the tenant variable and the super-admin variable on
  exit, dropping the regular tenant set by
  `TenantContextMiddleware`. Subsequent tenant-scoped reads
  in the same request returned zero rows under RLS. Surfaced
  the moment a customer-side service did
  `can_user_act_for_organization` (which elevates briefly)
  and then ran a tenant query right after — Members tab
  rendered "Members (0)" despite the row existing. Fix:
  capture `SHOW app.current_tenant_id` on enter; restore via
  `set_tenant(prior)` on exit. Every customer-side service
  that uses elevation followed by a regular query benefits
  immediately.

Frontend:

- **`SettingsTabs` component** — shared tab strip rendered
  at the top of every settings sub-page. Tabs are full
  Next.js routes (`/dashboard/settings`,
  `/dashboard/settings/members`); active state derived from
  pathname so deep-linking highlights correctly. Adding a
  third tab is one line in `TABS`.
- **Existing Organization page** updated to render the tab
  strip + a unified "Settings" header (vs. the old
  "Organization" page-specific h1).
- **New `/dashboard/settings/members` page**:
  - Lists members with email + role chip + join date + "YOU"
    badge on the caller's row + "Inactive" badge on
    deactivated rows.
  - Owner/admin sees a "more" button on every row except
    their own + (for admins) every owner row. Click opens an
    inline action panel with role select + Save Role +
    Deactivate/Reactivate buttons.
  - Role dropdown is restricted client-side: admins don't
    see "owner" as a choice (server enforces too).
  - Read-only banner shows on the section header for
    viewer/approver/submitter roles, but only after `me`
    has loaded so non-owners don't see a flash of "you
    can manage" before the gate kicks in.
- **`api.listOrganizationMembers()` + `patchOrganizationMember()`**
  + `OrganizationMemberRow` type added.

Tests: 15 new (441 passing total, was 426). Auth gate.
No-active-org → 400. Member can list. Owner can change
admin role. Owner can deactivate. Admin cannot change owner.
Admin cannot promote to owner. Owner can promote to owner.
Viewer cannot change anyone. Self-change rejected. Unknown
membership → 404. Unknown role → 400. At-least-one-field
required. No-op skips audit. Cross-org membership not
visible (404).

Verified live: signed up fresh, navigated to
`/dashboard/settings`, tabs visible (Organization +
Members), clicked Members, "Members (1)" with the user's own
row showing OWNER badge + "YOU" pill + join date. The
tenancy fix means the API actually returns the user's row
where it returned `[]` before.

Durable design decisions:

- **Tabs as full routes, not client tab state.** Each tab
  is a separate Next.js page, so deep-linking works
  natively (`/dashboard/settings/members` is a real URL),
  the back button does the right thing, and there's no
  "lost form state when switching tabs" footgun. Cost is
  one file per tab; benefit is the entire browser-history
  story comes for free.
- **Distinct audit action for customer vs admin
  membership changes.** `admin.membership_updated` and
  `organization.membership.updated` look identical
  semantically but are distinct signals — analytics can
  measure "how often does customer self-service vs.
  needing operator help" without parsing payloads.
- **Self-changes route through a future profile flow.**
  An owner accidentally demoting themselves locks the org
  out — there's no recovery path that doesn't involve
  staff (even an admin can't promote themselves to owner
  without an existing owner). Refusing self-changes here
  is the right friction; a dedicated profile page can
  later add the "promote a co-owner first, then leave"
  flow safely.
- **Tenancy fix preserves the prior tenant.** The
  super_admin_context exit was a `clear_tenant()` which
  drops both vars. The new exit reads the prior value with
  `SHOW` and re-sets it — same DB round-trip count, no
  observable behaviour change inside the elevated block,
  fixed behaviour outside.

What's deferred:

- **Invitations.** Adding a member by email needs an
  outbound email channel + an invitation token model.
  Email config exists (Slice 41) but the actual
  email-sending wiring doesn't. Members list shows
  existing members; new members still register
  themselves and get added by an existing owner manually
  via the admin shell or DB.
- **Self-edit profile page.** A `/dashboard/profile` route
  for the user's own email, password, language, timezone.
  Outside the Members tab; a separate slice.
- **Per-tenant API keys + Notifications + Security tabs.**
  Slices 46 and 47 next.

---

### Slice 46 — APIKey model + Settings → API keys tab

Closes the SECURITY.md gap: customers can now mint per-org
API keys for programmatic access (CI pipelines, Zapier,
direct API integrations) and revoke them on demand. The
plaintext is shown ONCE at creation; only a SHA-256 hash is
stored.

Backend:

- **`apps.identity.models.APIKey`** — TenantScopedModel with
  ``label`` (customer-facing identifier), ``key_prefix``
  (first 12 chars of plaintext, indexed for auth lookup),
  ``key_hash`` (SHA-256 hex, the verification value),
  ``created_by_user_id`` (soft FK), ``is_active`` /
  ``revoked_at`` / ``revoked_by_user_id`` (soft revoke),
  ``last_used_at``. RLS migration follows the per-tenant
  pattern.
- **`apps.identity.api_keys`** — service module:
  - ``create_api_key`` mints a fresh ``zk_live_<random>``
    plaintext via ``secrets.token_urlsafe`` (~200 bits
    entropy), stores prefix + hash, returns
    ``(row, plaintext)`` so the caller can render the
    plaintext exactly once.
  - ``list_api_keys`` returns label + prefix + status + last-
    used timestamps. Plaintext is NEVER in the response;
    ``key_hash`` isn't exposed either.
  - ``revoke_api_key`` flips ``is_active=False`` +
    ``revoked_at`` + ``revoked_by_user_id``. Idempotent on
    already-revoked rows (no audit noise).
  - All three audited:
    ``identity.api_key.created`` (label + prefix in payload)
    and ``identity.api_key.revoked``. Plaintext never in
    audit payloads — same PII-clean pattern.
- **Endpoints**:
  - ``GET /api/v1/identity/organization/api-keys/`` →
    list (no plaintext).
  - ``POST /api/v1/identity/organization/api-keys/`` →
    body ``{"label": "ci-pipeline"}``. Response includes
    ``plaintext`` ONCE.
  - ``DELETE /api/v1/identity/organization/api-keys/<id>/``
    → soft revoke.

Frontend:

- **`/dashboard/settings/api-keys`** new tab. List shows
  label + prefix chip + status + last-used + created-at.
  Active rows have a trash icon for one-click revoke.
  Revoked rows show a "Revoked" badge and dim out.
- **"New key" inline form** captures label + creates;
  on success, shows a warning-tinted **"Save this key now —
  you won't see it again"** banner with the plaintext +
  Copy button + "I've saved it" dismiss. Banner blocks the
  "New key" button so the operator can't accidentally
  trigger another create before saving the current one.
- **Clipboard write** via ``navigator.clipboard.writeText``;
  falls back silently when blocked (the operator can still
  select + copy manually).
- **Tabs strip extended** to include "API keys" alongside
  Organization + Members.
- **`api.listApiKeys`/`createApiKey`/`revokeApiKey`** + the
  `APIKeyRow` type added.

Tests: 11 new (452 passing total, was 441). Auth gate.
Create returns plaintext with the right prefix; row stores
hash, not plaintext; audit event records label + prefix
only. List does NOT return plaintext (asserted by
serialising the body and grepping). Revoke flips
``is_active``, emits audit, idempotent on already-revoked
(no extra audit). Revoking unknown id → 404. Cross-org
revoke → 404 (RLS isolation). Service contract: hash is
deterministic SHA-256; two creates produce different
plaintexts.

Verified live: signed up fresh, navigated to
`/dashboard/settings/api-keys` (3rd tab visible). Clicked
New key, typed "ci-pipeline", Created. Warning banner
showed the plaintext (`zk_live_Kme1U_…`), Copy button
worked, "I've saved it" dismissed. List then showed the
key with prefix chip + "Never used" + Created date + trash
icon for revoke.

Durable design decisions:

- **Plaintext write-only end-to-end.** API never returns
  it after creation; UI shows it ONCE in a dismissible
  banner; tests assert it doesn't reappear in list
  responses. A customer who lost the key revokes + creates
  a new one. Same contract the engine credentials surface
  uses (Slice 36).
- **Soft revoke, not delete.** Audit-log queries by
  ``actor_id=<api_key_id>`` need to keep resolving forever
  (a future "what did this key do?" investigation is
  meaningful even after revocation). Soft revoke + indexed
  ``is_active`` keeps the hot path fast.
- **Prefix length = 12, not 8.** Customers visually
  distinguish keys by prefix in the list (when they have
  multiple). 8 chars (``zk_live_``) is just the env tag;
  12 chars adds 4 random characters — enough variation
  for the list to read clearly without revealing the body.
- **No reason field on revoke.** Customer-side action;
  the audit chain still records the actor + key. A reason
  field would add friction for a panic-revoke scenario
  ("I think this key leaked, just kill it now"). Admin-
  side actions need reasons; customer self-service does
  not.
- **`last_used_at` populated by the future auth path.**
  Today the column exists but stays null because no API-
  key auth middleware reads it yet. The middleware lands
  in a follow-up; until then the field is a placeholder
  the UI already renders ("Never used").

What's deferred:

- **API-key auth middleware.** Today the keys exist + can
  be revoked, but no view actually accepts them as auth.
  Adding a middleware that resolves
  ``Authorization: Bearer zk_live_…`` to a User-equivalent
  identity is the natural next slice — paired with a
  documented public API surface.
- **Scopes / permissions.** Today every key is a fully-
  privileged proxy for its org. Future scopes (e.g.
  "upload only", "read invoices only") need a
  ``scopes: list[str]`` column + a permission-check layer.
- **Key rotation reminder.** Banner the customer when a
  key is older than N days. Phase 5 polish.

---

### Slice 47 — NotificationPreference + Settings → Notifications tab

The customer Settings now has its fourth tab. Per-user, per-
tenant notification preferences for the in-app bell + email
channels. The bell aggregator (Slice 28) already exists; this
slice ships the *preferences* layer the bell + future email
channel will read at delivery time.

Backend:

- **`apps.identity.models.NotificationPreference`** —
  TenantScopedModel keyed by ``(user, organization)`` with a
  ``preferences`` JSONField. Per-event toggles use a JSON dict
  rather than column-per-event so adding an event type doesn't
  require a migration. RLS migration follows the per-tenant
  pattern. Same user belonging to two orgs has two independent
  rows — preferences may legitimately differ per role.
- **`apps.identity.notifications`**:
  - ``EVENT_KEYS`` — canonical list of recognised events
    (key, label, description). Today: inbox.item_opened,
    invoice.validated, invoice.lhdn_rejected,
    audit.chain_verified, organization.membership.updated.
    Adding an event is a one-line change here.
  - ``get_preferences`` — auto-materialises the row with
    defaults (all channels on) on first read. Returns the
    full schema (event allowlist + label + description) plus
    the user's settings, so the UI renders both pieces from
    one round-trip.
  - ``set_preferences`` — replaces per-event channel toggles
    atomically. Unknown event keys reject (typo on FE side
    surfaces the contract violation); unknown channels (a
    future ``push`` or ``sms``) are silently dropped so a
    stale FE doesn't block the save when a new channel
    lands. Audited as
    ``identity.notification_preferences.updated`` with the
    list of event keys whose preferences changed — no
    boolean values in payload (PII-clean).
- **Endpoint**: ``GET / PATCH /api/v1/identity/organization/notification-preferences/``.

Frontend:

- **`/dashboard/settings/notifications`** — table with one
  row per event (label + description) and two toggle switches
  per row (in-app bell + email).
- **Optimistic updates + 350ms debounce** — toggles respond
  instantly; quick clicks across multiple events collapse
  into one PATCH. Saved-flash indicator appears in the
  header for ~1.2s on success. On failure, the page reloads
  from server to discard the optimistic state.
- **"Email needs SMTP" footer note** — until the operator
  configures SMTP credentials (Slice 41 namespace), email
  toggles capture preference but nothing actually sends.
  The frontend says so honestly rather than pretending email
  works.
- **Tabs strip extended** to include "Notifications" as the
  fourth tab.
- ``api.getNotificationPreferences`` /
  ``setNotificationPreferences`` + ``NotificationPreferenceRow``
  type added.

Tests: 9 new (461 passing total, was 452). Auth gate. GET
returns full event schema with defaults. First GET
materialises the row. PATCH disables one channel without
touching others. Unknown event key → 400. Unknown channel
silently dropped. Audit event records event keys only (no
boolean values in payload — sanity-checked by serialising +
grepping for "true"/"false"). No-op skips audit. Per-(user,
org) isolation: same user in two orgs has independent
preferences; setting one doesn't affect the other.

Verified live: signed up fresh, navigated to
`/dashboard/settings/notifications`. 4 tabs visible
(Organization, Members, API keys, Notifications). 5 events
render with description + 2 toggle switches each. All defaults
on (success-green). Footer note about SMTP visible.

Durable design decisions:

- **Per-(user, org), not per-user.** A user who's owner at
  one tenant and viewer at another has different stakes in
  notifications. The bell is already tenant-scoped (it
  filters by active org); preferences must be too.
- **JSON dict, not column-per-event.** Adding a new event
  is a one-line ``EVENT_KEYS`` append in code; no migration.
  The cost is no per-event index, but we never query "give
  me everyone who wants email for X" — the preferences are
  read at *delivery* time per (user, event), which is a
  point lookup on a small JSON.
- **Allowlist enforcement on event keys, silent drop on
  channels.** Event keys are part of the schema contract —
  a typo means the FE is broken. Channel names will grow
  over time (push, sms, slack); a stale FE that doesn't
  know about the new channel shouldn't lose the ability to
  save its old preferences. Asymmetric strictness is the
  right call here.
- **Auto-materialise on first read.** Same lazy-init
  pattern the SystemSetting resolver uses (Slice 41). The
  alternative — failing if no row exists — forces every
  consumer to handle the absence explicitly, which buys
  nothing.
- **Audit event records keys only.** A user's notification
  toggles are arguably PII (preference signal). Recording
  WHICH events they tweaked is enough for compliance; the
  ON/OFF state of each is recoverable from the row itself
  if needed.

What's deferred:

- **Actual email delivery.** SMTP credentials slot exists
  (Slice 41 ``email`` namespace); a delivery service that
  reads NotificationPreference + sends via the platform
  SMTP is the natural next slice.
- **Push notifications + Slack.** Channel additions —
  drop into ``VALID_CHANNELS`` + a delivery worker.
- **Per-tenant defaults.** Today defaults are platform-
  wide (all on). A future "this org's owners get email
  on rejections by default" preset would land as another
  layer in ``get_preferences``.

### Slice 52 — Email delivery wiring (SMTP + dispatch + test-send)

The four prior slices on the notifications track (Slice 28
in-app bell, Slice 41 SMTP creds namespace, Slice 47 per-event
preferences) all built the *persistence + UI* surface for email
notifications. None of them actually sent a byte over SMTP.
Slice 52 closes the loop: a real email goes out when an invoice
clears validation, and the operator can verify SMTP creds work
from the admin shell.

Backend:

- **`apps.notifications` app** — was previously empty. Now
  hosts:
  - `email.py` — stdlib `smtplib` + `EmailMessage` wrapper.
    No new dependency. `is_email_configured()` cheap precheck;
    `send_email(*, to, subject, body, html_body=None)` returns
    a structured `EmailDeliveryResult` (ok / detail / duration_ms
    / smtp_response_code). SMTP errors are caught — class name
    only is recorded in `detail`, never `str(exc)`. SMTP
    servers can echo credentials in error strings (LDAP-bind-
    style auth failures especially), so swallowing the message
    text is a deliberate security move. Tested explicitly:
    `assert "nope" not in result.detail`.
  - `services.py` — `_EMAIL_TEMPLATES` dict keyed by event_key
    (`invoice.validated`, `invoice.lhdn_rejected`, `test.ping`).
    `_SafeFormatDict` makes missing context vars render as
    empty string instead of `KeyError` — better to send a
    slightly-wrong email than crash the dispatcher. Two entry
    points:
    - `deliver_for_event(*, organization_id, event_key, context)` —
      fans out to active members of the org. For each, reads
      `NotificationPreference` (Slice 47), defaults to
      email=True if no row exists yet (matches the auto-
      materialise contract). Queues `send_email_task.delay()`
      per recipient. Returns a summary
      `{recipients_email_queued, no_template, no_recipients}`.
      Reads under `super_admin_context(reason="notifications:fanout")`
      because the caller is typically a Celery task with no
      session-org binding.
    - `send_test_email(*, to, actor_user_id)` — synchronous
      test send for the admin "send test" button. Bypasses
      preferences (admin is verifying SMTP, not asking the
      recipient). Audited as `notifications.email.test_sent`
      or `notifications.email.test_failed` so platform support
      can see who tested when.
  - `tasks.py` — `send_email_task` Celery shared_task with
    `max_retries=3, retry_backoff=True, retry_backoff_max=300`.
    Records `notifications.email.sent` / `notifications.email.failed`
    audit events with ok/duration/event_key only — no
    recipient PII in payload.
- **`submission/services._sync_validation_inbox`** — when an
  invoice transitions out of `error` to a clean state, fires
  `deliver_for_event(event_key="invoice.validated", ...)`
  with invoice_number + filename + invoice_url context. Wrapped
  in try/except with audit: notification failures never break
  validation — the invoice is still saved, the user still sees
  it in the UI, the email simply doesn't go.
- **Admin endpoint `POST /api/v1/admin/system-settings/email/test/`** —
  body `{"to": "ops@example.com"}`, returns the SMTP outcome
  synchronously so the operator sees the round-trip happen.
  Validates the recipient, gates on `IsPlatformStaff`, audits.
  URL placed before the catchall slug pattern so it doesn't
  resolve as a namespace named `email`.

Frontend:

- **`/admin/settings` → `TestEmailPanel`** — renders only when
  the `email` namespace is selected. Email input + Send button
  + result panel (success-green or error-red). Calls
  `api.adminTestEmail(to)`. The operator can sanity-check
  their AWS SES creds in 5 seconds without leaving the admin
  shell.

Tests: 18 new (515 passing, was 497). Cover: SMTP-not-configured
path, invalid recipient, successful smtplib mock, SMTP exception
handling (and the credential-leak guard explicitly), HTML
alternative, test-send audit (success + failure), template
rendering with missing context, dispatch fan-out skipping
opted-out users + inactive members, admin endpoint auth gate
(401, 403, 400, 200).

Verified live: configured SMTP creds in admin (Slice 41
namespace), sent a test from the admin shell, observed the
round-trip succeed in under 400ms; uploaded an invoice that
extracted clean and saw the `invoice.validated` audit event
land with the email queued.

Durable design decisions:

- **stdlib `smtplib`, not Django's email backend.** Django's
  backend reads from settings.EMAIL_*, which we'd have to
  rewire to the database-stored namespace anyway. Using
  smtplib directly + reading the namespace per-call lets
  the SMTP creds be live-edited in the admin and pick up
  on the next send without restarting. One layer of
  abstraction, not two.
- **No `str(exc)` in SMTP error detail.** Some SMTP servers
  echo the username on auth failures, and a few echo the
  full bind credentials. The class name is enough to diagnose;
  the bytes that come back are not safe to surface or log.
- **Templates inline as constants.** Three events today.
  When this hits ten, move to `templates/notifications/*.txt`
  — but premature jinja2 / django-templates infrastructure
  for three short strings is the wrong tradeoff right now.
- **Audit at the task layer, not the dispatcher.** The
  dispatcher records "queued N"; each delivery audits
  itself with the actual outcome. So a fan-out to 12 users
  produces 12 sent / 12 failed / mixed audits, not one
  rolled-up event with a buried failure count. Per-recipient
  observability is what an operator actually wants.
- **`is_email_configured()` ≠ "test it works".** It only
  checks that host + port + from_address are present. The
  admin test button is the actual liveness check, because
  SMTP creds can be present but wrong (typo, expired,
  rate-limited). Two-stage validation matches reality.
- **Notification failures don't block business logic.**
  Every `deliver_for_event` call from a state-machine
  transition is in a try/except. The invoice MUST get
  saved even if SES is down — losing a notification is
  recoverable; losing the invoice itself is not.

What's deferred:

- **HTML email templates.** Plain text only today. When
  marketing wants branded emails, swap `body` for `html_body`
  in the templates — `send_email` already supports both.
- **Per-event opt-out for outbound webhooks.** Webhook
  fan-out (Slice 53) will read the same NotificationPreference
  row but for the `webhook` channel, not email.
- **Bounce + complaint handling.** SES sends bounce/complaint
  to an SNS topic; we don't subscribe yet. When we do, an
  `apps.notifications.bounces` view ingests them and flips
  the recipient's email-channel preference off automatically.

### Slice 53 — Webhook delivery worker (sign + POST + retry + fan-out)

The Slice 49 webhook surface persisted endpoints, generated
signing secrets, and showed deliveries — but the deliveries
were synthetic rows with `response_body_excerpt = "(synthetic
— worker not yet wired)"`. Customers couldn't actually receive
events. Slice 53 closes that loop end-to-end.

Backend:

- **`apps.integrations.crypto`** — Fernet AEAD using a key
  derived from `settings.SECRET_KEY` via SHA-256. `encrypt_secret`
  / `decrypt_secret` (returns None on tamper, never raises).
  Why this exists: signing requires the *plaintext* secret, but
  Slice 49's create-time contract was write-only (only SHA-256
  hash persisted). Adding the encrypted column keeps that
  customer-facing contract — the customer still sees their
  plaintext exactly once — while letting the delivery worker
  reconstruct it for HMAC. A future swap to a dedicated
  `WEBHOOK_SECRET_FERNET_KEY` env var with rotation procedure
  is a one-line change in `crypto._fernet`.
- **Migration `0003_secret_encrypted`** — adds
  `WebhookEndpoint.secret_encrypted` (TextField, default empty).
  Endpoints created before Slice 53 land have the empty value
  and deliver unsigned; the operator surface flags this
  (planned follow-up: surface the "regenerate to enable
  signing" prompt on those rows).
- **`apps.integrations.delivery.deliver_one(delivery_id)`** —
  pure delivery primitive. Looks up the row, decrypts the
  signing secret, builds the canonical body
  `{id, type, created, data}`, computes Stripe-style
  `X-ZeroKey-Signature: t=<unix>,v1=<hex>` where v1 is
  HMAC-SHA256(secret, f"{t}.{body}"), POSTs via httpx with
  `follow_redirects=False` + 10s timeout. Updates the row's
  outcome/status/body_excerpt/error_class/duration_ms in place
  and bumps `endpoint.last_succeeded_at` /
  `last_failed_at` so the UI's "last delivered N min ago"
  cursors stay current. Returns a `DeliveryResult`. Critical:
  network errors record only the exception class name — never
  `str(exc)` — same security posture as the SMTP wrapper from
  Slice 52.
- **`apps.integrations.tasks.deliver_webhook_task`** — Celery
  task with `acks_late=True` and `max_retries=4` (so up to 5
  total attempts). Calls `deliver_one`, audits each attempt as
  `integrations.webhook.delivered` /
  `integrations.webhook.delivery_failed` with payload
  `{endpoint_id, event_type, attempt, ok, status_code,
  duration_ms, error_class}` — never the body or signature.
  Retry decision via `_should_retry(status_code, error_class)`:
  5xx and 429 retry, 4xx do not (the receiver is saying "your
  request is wrong" — repeating won't help), network errors
  retry, the synthetic `EndpointRevoked` class never retries.
  Backoff is exponential (30s base, doubling, capped at 5min)
  and jittered by Celery natively. Final-attempt failure marks
  the row `abandoned`.
- **`apps.integrations.services.fan_out_event(*, organization_id,
  event_type, payload)`** — finds active endpoints in the org
  whose `event_types` list contains the event, creates a
  `pending` `WebhookDelivery` row per match, queues
  `deliver_webhook_task.delay(delivery_id=...)`. Reads under
  `super_admin_context(reason="webhooks:fanout")` — same
  pattern as the email dispatcher.
- **`send_test_delivery` rewired** — was a synthetic row,
  now creates a `pending` row + calls `deliver_one` synchronously
  so the operator sees the round-trip outcome (success or
  failure) in the UI without polling. No retry on test sends —
  the operator is actively waiting; they want the verdict now.
- **Submission hook** — `_sync_validation_inbox` already fired
  `invoice.validated` to email (Slice 52); now it also fans
  out to subscribed webhooks via `fan_out_event`. Wrapped in
  try/except so a Celery broker outage can't break the
  validation path.

Frontend: no FE changes — Slice 49 already shipped the UI.
Customers who registered endpoints + the `invoice.validated`
event type pre-Slice 53 immediately start receiving real
deliveries the next time an invoice clears validation.

Tests: 14 new (529 passing total, was 515). Cover: real
HTTP test-send via mocked httpx, 5xx → failure outcome,
ConnectError → failure with class-name-only error, signature
header attached + cryptographically verifiable with the
plaintext from create-time, event headers
(`X-ZeroKey-Event-Type`, `-Attempt`, `-Event-Id`,
`-Delivery-Id`), fan-out only to subscribed endpoints,
inactive endpoint skipped, full retry-policy table (5xx /
429 / 4xx / network / EndpointRevoked), Fernet roundtrip +
empty-string + tampered-token cases.

Verified live: created an endpoint pointing at
`requestbin.io/r/abc`, hit the test button, observed the
real POST land + signature header verify by hand against
the plaintext shown at create time.

Durable design decisions:

- **Stripe-style signature header**, not naked HMAC. Receivers
  in any language can pull `t` and `v1` out of one string
  with a regex — easier to recreate than a multi-header
  scheme. The timestamp prefix lets receivers reject stale
  replays (>5min old) without a clock-sync.
- **Encrypted plaintext alongside hash, not in place of it.**
  Hash stays as the verification primitive for any future
  "customer presents secret to revoke" flow. Encrypted column
  is purely for outbound signing. Two tools, two columns.
- **`follow_redirects=False`.** A receiver redirecting our
  POST is misconfigured. Following silently would hide that
  + open up SSRF-adjacent surface. Treating 3xx as a failure
  is the safer default.
- **No `str(exc)` in error_class.** httpx exception messages
  sometimes include the request URL fragment + TLS handshake
  bytes. Class name is enough to triage; the full string is
  not safe to surface in customer UIs.
- **Audit per attempt, not per logical event.** A 3-retry
  delivery produces 3 audit rows. Operators investigating
  why a customer didn't receive an event need to see each
  attempt's HTTP status, not a rolled-up "eventually failed".
- **4xx never retries.** 5xx says "I'm broken right now" —
  retry helps. 4xx says "your request is wrong" — retry
  cannot help; only the customer fixing their endpoint can.
  Looping on 4xx is the most common cause of webhook-induced
  rate-limit problems on customer infrastructure.
- **Synchronous test-send, async fan-out.** Test sends are
  human-in-the-loop — the operator sees the outcome
  immediately. Fan-out is machine-to-machine — async lets
  validation return fast.

What's deferred:

- **Old endpoints (no encrypted secret)** still send unsigned.
  A follow-up surfaces the "secret missing — please regenerate"
  state in the UI + auto-disables those endpoints after a
  customer-acknowledged warning.
- **Per-event filtering on the receiver side.** We send all
  configured event types; receivers that want a subset must
  filter on `X-ZeroKey-Event-Type`. Subscribing to fewer
  event types at create time is the supported workflow.
- **Dead-letter queue.** Abandoned deliveries today just sit
  in the DB — no operator inbox surfacing yet. Adding a
  `WebhookDelivery.requires_attention` flag + an admin view
  is the natural next slice.
- **Outbound signature for `inbox.item_opened`** + other
  events — only `invoice.validated` is wired to the fan-out
  hook today. Adding more events is a one-line
  `fan_out_event(...)` call at the producing site.

---

### Slice 54 — Two-mode extraction selector (AI vision vs OCR-only)

The first of three slices implementing dual-mode extraction.
Slice 54 ships the *selector* + per-tenant plumbing; Slices 55
(PaddleOCR + PP-Structure tables) and 56 (LayoutLMv3 KIE)
upgrade the OCR lane's quality.

Backend:

- **`Organization.extraction_mode`** — TextChoices field with
  values `ai_vision` (default) and `ocr_only`. Migration
  `identity/0008_extraction_mode` adds the column with
  default `ai_vision` so all existing tenants stay on the
  current behavior. Audited as `identity.organization.updated`
  with field-name only — never the value, since tenants
  switching to `ocr_only` is arguably commercial-sensitive
  signal.
- **`apps.extraction.adapters.regex_adapter.RegexFloorStructurer`** —
  deterministic field structurer. Implements
  `FieldStructureEngine` so it slots into the same call site
  as the LLM structurers but invokes zero external services.
  Pulls out invoice number, dates, currency, supplier TIN,
  SST number, totals, subtotal, tax via labelled-line regex;
  line items via a coarse `<desc> <qty> <unit> <total>` row
  matcher that emits a JSON array of `{description, quantity,
  unit_price, line_total}`. Confidence scoring is fixed-band
  (0.6–0.75 per hit) and overall scales by coverage so a
  document yielding 8/10 fields scores higher than one
  yielding 2/10. Cost is always 0.
- **`apps.extraction.services.run_extraction`** — branches on
  the mode. In `ocr_only` mode the vision-escalation path is
  short-circuited (the tenant never pays for an LLM vision
  call); in `ai_vision` mode the existing escalation runs
  unchanged. The OCR fallback (Slice 32) still runs in both
  modes — that's deterministic + free, so it's part of the
  shared text-extraction floor.
- **`apps.submission.services.structure_invoice`** — branches
  on the mode. `ocr_only` calls `RegexFloorStructurer` directly,
  bypassing the engine router so LLM-route adapters aren't
  even consulted. `ai_vision` uses the existing pick_engine
  flow. Both lanes converge on `apply_structured_fields`,
  so downstream (enrichment, validation, line-item
  materialization, validation inbox sync) doesn't care which
  lane produced the fields.
- **`update_organization` allowlist** — `extraction_mode`
  added to `EDITABLE_ORGANIZATION_FIELDS`. The update path
  validates the value against `_EXTRACTION_MODE_VALUES` so
  a 400 surfaces immediately on a typo or attack — Django's
  ORM doesn't enforce TextChoices on `.save()`.

Frontend:

- **Settings → Extraction mode card** — two radio buttons.
  Each card shows title + price band + 3 honest bullets:
  - **AI extraction** (recommended): "~RM0.10–0.30 per
    invoice / Highest accuracy / Best when document quality
    is unpredictable."
  - **OCR only** (cost-saver): "No per-document cost / Best
    for clean PDFs / May need more manual review on poor-
    quality or handwritten inputs."
  Honest about tradeoffs rather than hiding the OCR lane's
  weaknesses behind marketing language.
- **`OrganizationDetail.extraction_mode`** added to API type.
  Same FieldRow / SaveBar pattern as the rest of the
  Settings page — change the radio, hit Save, audit fires.

Tests: 14 new (543 passing total, was 529). Cover:
- `RegexFloorStructurer` extracts invoice number, dates,
  currency, supplier TIN, totals with thousand separators,
  per-field confidence populated, zero cost, line items
  returned as JSON-string.
- Sparse text returns empty result without crashing.
- Overall confidence scales with coverage.
- `Organization.extraction_mode` defaults to `ai_vision`.
- PATCH switches the value; audit captures field name only
  (asserts the literal value `"ocr_only"` never appears in
  the JSON-serialised audit payload).
- PATCH with invalid value (`"magic_unicorn"`) returns 400.
- GET returns the field in the org payload.

Verified live: switched a test org to `ocr_only`, uploaded
the same Acme invoice that previously routed through Claude;
extraction completed in <1s with zero cost, regex floor
populated 7 of 11 header fields + 2 line items, validation
inbox surfaced the missing fields as expected.

Durable design decisions:

- **Per-tenant default = `ai_vision`.** New customers
  optimize for "does it work?" before "is it cheap?"; the
  first invoice extraction is a make-or-break moment for
  retention. Surface the cost-saver lane as an opt-in once
  the customer trusts the product.
- **Audit field-name only on mode change.** Some customers
  may not want competitors knowing they're on the cost-saver
  lane. Field name leaks the *capability* edit, not the
  commercial position.
- **Branch BEFORE the engine router, not inside it.** Adding
  a `mode_filter` column on the Engine row + filtering at
  routing time would be more uniform — but it would couple
  the registry to a tenant attribute the registry doesn't
  otherwise know about, and it would make engine selection
  silently fail in ways that look like routing bugs. The
  explicit two-line branch in `run_extraction` /
  `structure_invoice` is more honest about what's
  happening.
- **Regex floor stays as the last-resort even after Slices
  55 + 56.** PP-Structure / LayoutLMv3 will own the primary
  OCR-lane structurer, but they can both come back empty.
  The regex floor is the floor — never an empty Invoice if
  there's any plausible labelled value in the OCR text.
- **Per-upload override deferred.** Three knobs (org
  default, per-upload override, auto-fallback) is too many
  for one slice. Org default ships first; per-upload
  override is a future enhancement when we see customers
  actually wanting it (instrument the audit log first).
- **No EngineCall row for the regex floor.** Cost is zero,
  latency is sub-millisecond — recording it would clutter
  the engine-call dashboard with rows that don't represent
  paid spend. The structuring engine_name on the Invoice
  (`regex-floor-structurer`) is the breadcrumb operators
  need.

What's deferred:

- **Per-upload override** on the dropzone (org default for now).
- **Auto-fallback** ("OCR-only confidence < threshold; offer
  AI") — needs the auto-flag-for-review logic from Slice 56.
- **PaddleOCR + PP-Structure** (Slice 55).
- **LayoutLMv3 KIE for header fields** (Slice 56).

---

### Slice 55 — KMS envelope encryption bundle

Closes the highest-leverage security gap from the docs audit: the
`SECURITY.md` design called for envelope encryption on platform
secrets but `SystemSetting.values` and `Engine.credentials` both
sat as plaintext JSON in Postgres. Anyone with database access
could read every customer's LHDN client secret, every vendor API
key, the SMTP password, the Stripe key.

Slice 55 lands at-rest encryption with a clean KMS swap point.

Backend:

- **`apps.administration.crypto`** — Fernet (AES-128-CBC + HMAC-
  SHA256, AEAD) with a key derived from `settings.SECRET_KEY` via
  SHA-256. `encrypt_value` / `decrypt_value` for single strings
  + `encrypt_dict_values` / `decrypt_dict_values` for the JSON
  dict columns. Ciphertext carries the `enc1:` marker prefix so
  the decrypt path distinguishes ciphertext from legacy plaintext
  on read — no schema column change, no per-row migration mode
  flag, just a prefix sniff.
- **Idempotent encrypt** — re-encrypting an already-encrypted
  value returns it unchanged. The migration that ships with the
  slice walks every existing row + rewrites; idempotency lets
  partial-replay safely converge.
- **Tamper-tolerant decrypt** — flipped-byte ciphertext returns
  `""` (with a logging warning) rather than raising. The application
  degrades gracefully to "no value" + the env-fallback path picks
  up; an operator notices the warning and rotates.
- **`system_setting` resolver** — decrypts on read.
- **`upsert_system_setting`** + **`admin_update_system_setting`** —
  encrypt on write. The latter additionally decrypts the existing
  values to compare in plaintext (so a no-op resave doesn't fire
  spurious "changed" entries) then re-encrypts.
- **`engine_credential` resolver** — same pattern.
- **`admin update_engine`** + **`_engine_admin_dict`** — same
  pattern. Note `credential_keys` in the admin readout is just
  `bool(value)` per key (presence indicator); ciphertext is
  truthy-non-empty so the contract holds without changes.
- **Data migration `administration/0005_encrypt_existing_secrets`** —
  walks every `SystemSetting.values` + `Engine.credentials` row
  + encrypts plaintext entries. Reversible (decrypt-back) for
  test-suite migrations; in production a rollback is fine because
  the read path tolerates ciphertext indefinitely.

Frontend: no changes — the API surface returns plaintext as it
always did; the encryption is invisible to the customer-facing
read path.

Tests: 15 new (558 total, was 543). Cover:
- Single-value roundtrip + idempotent encrypt + tamper detection
  + ciphertext never contains the plaintext substring.
- Dict encryption: only string values get encrypted, keys stay
  plaintext (load-bearing for audit log "WHICH keys changed"
  semantics), non-strings (ints, bools) pass through unchanged,
  defensive None handling.
- Mixed legacy + encrypted dict (the migration-in-progress state)
  reads correctly.
- `system_setting` resolver: upsert stores ciphertext at rest +
  resolver returns plaintext + legacy plaintext rows still resolve.
- `engine_credential`: same — ciphertext at rest + plaintext
  on resolve + legacy plaintext compatibility.
- 7 existing tests updated to decrypt-then-assert (they had been
  asserting the raw column equalled plaintext; now the row holds
  ciphertext but the resolver still returns plaintext).

Verified live: dev DB migration ran clean — 5 SystemSetting +
5 Engine rows transitioned from plaintext to `enc1:`-prefixed
ciphertext. Re-resaved a webhook test send via the admin UI;
SMTP password decrypted at delivery time, email landed.

Durable design decisions:

- **Marker prefix, not a column.** Adding `is_encrypted: bool`
  next to every JSON-typed credential column would have been
  uniform but noisy + would require a schema migration on every
  table that gets the treatment. The ciphertext-prefix approach
  is invisible to the schema; rolling out to a new column is a
  one-import, one-call change in the consuming service.
- **Key derived from SECRET_KEY today, KMS-DEK tomorrow.** One
  less moving piece for dev. Threat-model-correct: an attacker
  with SECRET_KEY can already forge sessions, signed cookies,
  password reset tokens — coupling field encryption to the same
  key doesn't make the situation materially worse. Production
  swap point is `_dek()` — replace the body with a KMS Decrypt
  call against an envelope-encrypted DEK. Call sites don't change.
- **Encrypt values, not keys.** Audit chain records WHICH keys
  changed when an admin edits a SystemSetting (by name only).
  That operator-visibility is a feature; encrypting key names
  would break it without buying confidentiality (the keys are
  schema-level, not secret).
- **Idempotent + tamper-tolerant.** Both properties are
  load-bearing for the operational story: idempotency makes the
  migration replay-safe, tamper-tolerance turns "DEK rotation
  half-applied" from a crash into a visible warning + an
  env-fallback rescue.
- **Audit field-name only on changes (unchanged).** Existing
  contract; this slice doesn't alter it. The audit chain still
  reads "namespace.lhdn keys: [client_id, client_secret] changed"
  — never the values, never the ciphertext.

What's deferred:

- **Organization PII** (contact_email, contact_phone,
  registered_address) — these are plaintext today by docs
  acknowledgement. Encrypting them now would break the cross-
  tenant lookups the platform does on contact_email (e.g. "find
  org by contact email" in support flows). Deterministic /
  searchable encryption is the right tool there + a separate
  slice.
- **Audit chain Ed25519 signature column** (also flagged by the
  docs audit). Distinct cryptographic primitive; deserves its
  own focused slice rather than bundling with at-rest secrets.
- **Customer signing certs** (the Phase-3 CSR bundle): those
  are S3-stored blobs, not DB columns. KMS envelope encryption
  on the blob path is part of the LHDN signing slice (Slice 57).
- **Real KMS integration** (`_dek()` swap). One-line change
  when production deployment lands — gated on having an actual
  AWS account + IAM policy.

---

### Slice 56 — Member invitations (Settings → Members → Invite)

The docs audit flagged this as a customer-pain item: the Members
tab (Slice 45) had a footer note saying "Sign up flow creates one
membership; invitations [coming]." Slice 56 lands the actual
invitation flow.

Backend:

- **`identity.MembershipInvitation`** model — TenantScopedModel
  with `email`, `role`, `invited_by`, `token_hash` (SHA-256 of a
  one-time plaintext), `expires_at` (default 14 days), `status`
  (`pending` / `accepted` / `revoked` / `expired`). RLS policy
  follows the standard tenant-isolation pattern (migration
  `0010_membership_invitation_rls`). Plaintext token shown ONCE
  at create time + embedded in the invite link — same write-only
  contract as APIKey + WebhookEndpoint.
- **`apps.identity.invitations`** service module:
  - `create_invitation(*, organization_id, email, role_name,
    actor_user_id)` → `(row, plaintext_token)`. Refuses if the
    email is already an active member or has a pending invite
    (anti-spam guard).
  - `accept_invitation(*, token, accepting_user_id)` → creates
    OrganizationMembership. Email-match required: invite must
    be accepted by the invited address (a forwarded link doesn't
    let an outsider join). Race-safe via `select_for_update`
    re-fetch in the success path. Auto-marks expired rows.
  - `revoke_invitation` — idempotent.
  - `list_pending_invitations` — Settings tab readout.
- **Endpoints** (under `/api/v1/identity/`):
  - `GET / POST /organization/invitations/` — list + create
    (owner / admin gate on POST).
  - `DELETE /organization/invitations/<id>/` — revoke (owner /
    admin only).
  - `POST /invitations/preview/` — anonymous: returns
    `{email, role, organization_legal_name, expires_at}` so
    the landing page can show the invite shape before the
    user signs in. 404 for invalid/expired (no info leak).
  - `POST /invitations/accept/` — accept as the signed-in user.
- **Email integration** — uses the Slice 52 send_email path.
  Best-effort: if SMTP is down or unconfigured, the invite still
  creates; the invite-link URL is returned in the create response
  so the inviter can share it manually. Audit chain records the
  invitation regardless of email outcome.
- **Audit privacy** — invitation events record only the *masked*
  email (`d***@example.com`) so a chain reader can't enumerate
  invitee addresses. The full address lives on the row (we need
  it to match on accept) but it's behind tenant-RLS + admin
  surfaces.

Frontend:

- **Settings → Members** — "Invite member" button (owner / admin
  only) opens an inline form with email + role dropdown.
- **Invite-link panel** — after issue, the plaintext invitation
  URL is shown ONCE with a "Copy" button + dismiss. Honest about
  the shown-once contract: "We've emailed it. If you need to
  share via another channel, copy now — it won't be displayed
  again."
- **Pending invitations section** — separate card under Members,
  shows email + role + expiry + revoke button.
- **`/accept-invitation?token=<plaintext>`** — landing page.
  Three states:
  1. Signed in with matching email → "Accept as <email>" button.
  2. Signed in with different email → amber banner + "Sign out
     + continue" that redirects through `/sign-in?return_to=...`.
  3. Not signed in → CTA to sign in (with return_to) or sign
     up (with `?invite=<token>` for the post-signup auto-accept,
     deferred).

Tests: 23 new (581 passing total, was 558). Cover:
- Create: pending status + plaintext returned + plaintext NOT
  persisted on row + audit email-masked (asserts the literal
  invitee's local-part never appears in the audit JSON) +
  invalid email rejected + unknown role rejected + existing
  active member rejected + duplicate pending rejected.
- Accept: creates membership + invalid token + email mismatch
  + expired auto-flips status to expired + double-accept
  rejected.
- Revoke: flips status + idempotent.
- Endpoints: owner POST 201 + non-admin 403 + list returns
  pending + revoke endpoint + preview returns org name +
  accept via endpoint flips session.organization_id.
- Email send is attempted (mocked) + email failure does NOT
  block invite creation.

Verified live: created an invite to `test@symprio.com` — got
the plaintext URL in the response + a copy of the link in
the issuer's email inbox + the pending row showed in the
Members tab. Opened the link in incognito, got the preview
("Join Acme as viewer"), signed up with the matching email,
accepted, landed on the dashboard already in the new org.

Durable design decisions:

- **Separate row, not pre-created inactive membership.**
  Invitee may not have a User row yet. Pre-creating one with
  no password is a footgun for the rest of the auth path.
- **Email-match required on accept.** A forwarded link
  shouldn't let an outsider join. Open question parked: do
  we ever want "invite a@x but b@x.com accepts" (assistant
  flows)? Tightening is conservative; can loosen later if
  customers ask.
- **Audit on email-masked, not full email.** Invitee
  addresses are arguably PII signal — chain readers can
  correlate "this row is an invite" without enumerating
  the invitee's address.
- **Best-effort email + invite-link in response.** If the
  customer hasn't configured SMTP yet, invitations must still
  work. Returning the URL once-after-issue is the escape
  hatch + matches our existing "show once" pattern (APIKey,
  WebhookEndpoint).
- **14-day TTL.** Industry-standard. Long enough for "I'll
  do it tomorrow" + "I went on holiday"; short enough that
  a stale link in a year-old inbox can't bring back a
  forgotten invite.
- **Anonymous preview endpoint.** Lets us render the
  invitation shape before the user has a session. Returns
  404 for invalid/expired rather than echoing the request
  (avoids token-enumeration signals).

What's deferred:

- **Sign-up + auto-accept.** Today the new user must sign up
  separately + then visit the link. Carrying the token through
  signup so it auto-accepts is a small follow-up.
- **`return_to` honoring on sign-in.** The invitation page
  passes it; sign-in doesn't read it yet. Drop-in change.
- **Resend / re-issue.** Today's flow is "revoke + create
  new"; a one-click resend is friendlier.
- **Bulk invite.** CSV import, common in onboarding new
  team-of-30 customers.

---

### Slice 57 — Per-org integration credentials with sandbox/prod toggle

The customer needs to configure their own LHDN MyInvois
credentials — every tenant has their own LHDN-issued client_id
+ secret + TIN. The earlier Slice 41 (`SystemSetting`) was
**platform-level**: one row of LHDN creds for the whole platform.
That works for Stripe (one Stripe account for ZeroKey) but breaks
for LHDN (every customer has their own LHDN account).

Slice 57 lands the per-tenant credential surface. Two slots per
integration (sandbox + production) with a one-click "go-live"
toggle and a per-environment test-connection button so the
operator gets an instant "creds are working" verdict.

This is foundational for Slice 58 (LHDN signing + submission),
which reads these creds at submit time.

Backend:

- **`identity.OrganizationIntegration`** — TenantScopedModel
  with `(org, integration_key)` unique. Two JSONField credential
  blobs (`sandbox_credentials`, `production_credentials`),
  `active_environment` enum (sandbox | production), per-env
  last-test cursors (`last_test_*_at`, `last_test_*_ok`,
  `last_test_*_detail`). RLS migration 0012 follows the standard
  tenant-isolation pattern.
- **`apps.identity.integrations`** module (distinct from the
  bounded-context `apps.integrations` package — that's the
  webhook surface). Holds:
  - `INTEGRATION_SCHEMAS` registry. Each integration declares
    its fields with `kind` (`credential` | `config`),
    `placeholder`, `required`. Today: `lhdn_myinvois` with
    `client_id` / `client_secret` / `base_url` / `tin`.
    Sandbox + production both pre-seed sensible default
    `base_url` values so first-time setup doesn't require
    copy-pasting LHDN URLs from docs.
  - `upsert_credentials(*, environment, field_updates, ...)` —
    per-environment patch. Decrypts current → diff in plaintext
    → re-encrypts on write (via Slice 55 helpers). Audit
    records WHICH fields changed by name; values never enter
    the chain.
  - `set_active_environment(*, environment, reason, ...)` —
    the go-live toggle. Audit captures `from_environment` →
    `to_environment` so a chain reader sees "this tenant
    flipped to production at T".
  - `test_connection(*, environment, ...)` — runs the
    integration's tester + persists outcome on the row.
  - `_test_lhdn_myinvois(plain)` — Slice 57 ships a
    *connectivity probe* (DNS resolution + HEAD on the base
    URL + sanity check that `client_id` / `client_secret` /
    `tin` are populated). Slice 58 swaps this for a real
    OAuth2 token request once the LHDN client lands.
- **Endpoints** under `/api/v1/identity/`:
  - `GET /organization/integrations/` — list all cards (any
    member; viewers see read-only state).
  - `PATCH /organization/integrations/<key>/credentials/` —
    upsert one environment's creds (owner / admin only).
  - `PATCH /organization/integrations/<key>/active-environment/` —
    flip the toggle (owner / admin only).
  - `POST /organization/integrations/<key>/test/` — run the
    test-connection probe (owner / admin only).

Frontend:

- **Settings → Integrations** new tab. SettingsTabs strip
  extended.
- **Per-integration card** — title + description + active-
  environment badge + "Go live →" / "Switch to sandbox" button
  (with a confirm dialog on the production switch).
- **Two stacked sub-cards**: Sandbox + Production. Each shows
  the configured fields (credentials masked + "Configured"
  pill, config fields plaintext), a Save / Discard pair on
  any draft change, and a "Test connection" button per
  environment with the result rendered inline (success-green
  or error-red panel with the detail string).
- **"Go live" gesture** — `window.confirm` on switching to
  production with a clear warning that live invoices will hit
  LHDN's real API. Customer-pleasing safety belt without being
  a modal-form burden.
- **Read-only for non-admins** — fields disabled, buttons
  hidden. Backend gate is the source of truth; the FE gate
  is for UX.

Tests: 23 new (604 passing total, was 581). Cover:
- Schema registry exposes `lhdn_myinvois` with the required
  fields (`client_id`, `client_secret`, `base_url`, `tin`).
- `list_integrations_for_org` returns the default empty shape
  for orgs with no row yet (so the form renders).
- `upsert_credentials`: defaults seeded on first save +
  values encrypted at rest (raw column read confirms ciphertext)
  + audit captures field names only (literal secret value
  never appears in payload JSON) + unknown field / unknown
  integration / invalid environment all 400 + empty value
  clears the key.
- `set_active_environment`: flips state + audit captures
  from→to transition + idempotent (no-op skips audit).
- `test_connection`: 400 if no creds saved, DNS failure +
  5xx response + missing-credentials warning all surface
  with structured detail, success persists `last_test_*_at`
  + `last_test_*_ok` on the row.
- Endpoints: list returns LHDN card + non-admin 403 on patch
  + owner can patch + switch-environment endpoint flips +
  test endpoint invokes the tester.

Verified live: configured a fresh test org's LHDN sandbox
creds (`client_id=demo-id`, `client_secret=demo-secret`,
`tin=C1234567890`) — saved + got the "Configured" pill.
Hit Test connection — got "connectivity OK + credentials
present" in 380ms with the row's `last_test_sandbox_at`
populated. Switched to production, confirm dialog fired,
the badge flipped to "Live · production".

Durable design decisions:

- **Two slots per integration, not overwrite-on-go-live.**
  Operators want sandbox creds to stay configured after
  going live so they can A/B test against the sandbox
  without rotating keys. Two columns is simpler than a
  history table.
- **Per-env test cursors.** "Last tested 5 min ago"
  beats "operator hits Test then waits 30s" for the
  always-on observability the credentials surface needs.
- **`_test_lhdn_myinvois` is a stub today.** A connectivity
  probe gets us 80% of the value (catches the most common
  misconfiguration: typo in base_url) for 5% of the work
  Slice 58's real OAuth2 tester needs. Stub matches the
  same `TestOutcome` contract so the swap is invisible to
  the UI.
- **Schema registry in code, not DB.** Adding a new
  integration is a one-entry change in `INTEGRATION_SCHEMAS`
  + a tester in `_INTEGRATION_TESTERS`. No migration. The
  list of integrations IS schema, not data — same logic
  as `EVENT_KEYS` for notifications.
- **Encryption inherited from Slice 55.** Strings → ciphertext
  via `encrypt_dict_values`; non-strings (bools, ints) pass
  through. Compatible with the migration-in-progress legacy
  plaintext state for free.
- **Confirm on go-live.** Switching to production is the
  single highest-impact gesture in the UI. A confirm
  dialog is the right amount of friction — too low and
  customers go live by accident; too high (multi-step
  modal) and engineers hate it.

What's deferred:

- **OAuth2 tester for LHDN** — connectivity probe today;
  Slice 58 ships the real token-request tester that
  proves client_id + secret are valid against LHDN.
- **Reason required on production switch.** Today reason
  is captured but optional. Likely tightened with
  compliance review (auditors want "why did this org go
  live at this moment?").
- **More integrations** — Stripe (likely platform-level
  not per-org), Peppol (later when Malaysia mandates
  cross-border via Peppol), Email-forward ingestion
  (handled by Slice 60 platform-side).

---

### Slice 58 — LHDN signing + submission (real, with self-signed dev cert)

The product's reason to exist. Slice 41 / 49 / 57 built the
configuration scaffolding; this slice ships the actual flow:

  1. Customer's invoice gets a self-signed dev cert auto-minted
     on first signing attempt (or uses their uploaded cert when
     they get one).
  2. UBL 2.1 invoice XML built from the structured Invoice +
     LineItem rows.
  3. XML-DSig (RSA-SHA256, enveloped, c14n) signs the XML.
  4. OAuth2 token request against the org's active LHDN
     environment (sandbox by default).
  5. Signed XML POSTed to LHDN's documentsubmissions endpoint.
  6. Polling reconciles the status into ``submitting`` →
     ``validated`` / ``rejected`` on the Invoice row + captures
     the LHDN UUID + QR-code URL.

The whole chain is testable end-to-end without an LHDN account
because:

  - The dev cert is self-signed (acceptable for sandbox + local
    pipeline tests).
  - The HTTP layer is `httpx` so test code mocks the four LHDN
    endpoints we touch.

When the customer obtains a real LHDN-issued cert (Slice 59
ships the upload UI), the signing path doesn't change — the
``ensure_certificate`` resolver picks up the uploaded blob,
``cert_kind`` flips to ``"uploaded"``, and the same submission
flow runs.

Backend modules added:

- **`apps.submission.certificates`** — self-signed RSA-2048
  cert generation (1-year validity, SHA-256), stored inline on
  the Organization row with the private key encrypted via
  Slice 55. ``ensure_certificate(organization_id)`` is
  idempotent: returns existing cert or mints one. Audit event
  ``submission.cert.self_signed_minted`` records the mint
  (subject CN + serial + expiry; never the PEM itself).
  Production swap point is documented in `_load`: replace the
  inline column with KMS-decrypt of an S3-stored envelope-
  encrypted blob; call sites stable.
  ``upload_certificate(...)`` for customer-supplied certs:
  validates the cert + key are a matched RSA pair before
  persisting + audits ``submission.cert.uploaded``.
- **`apps.submission.ubl_xml`** — UBL 2.1 invoice XML builder.
  Uses stdlib `xml.etree.ElementTree` (no lxml dep). Header
  fields (number, dates, currency), supplier + buyer party
  blocks (TIN / BRN / SST / MSIC identifiers, postal address,
  country code), tax totals, monetary totals, line items.
  Output is canonicalised (`ET.canonicalize`) so the digest
  the signer computes matches what LHDN sees.
- **`apps.submission.xml_signature`** — hand-rolled enveloped
  XML-DSig. Algorithm URIs match the W3C recommendation:
  c14n + enveloped-signature transform + SHA-256 digest +
  RSA-SHA256 signature. KeyInfo carries the X.509 cert in
  base64-DER. Reasoning for hand-rolling: `signxml` needs
  lxml (not in deps), `xmlsec` needs the libxmlsec1 system
  lib (Docker complication), and the enveloped variant is
  bounded enough that ~150 lines of stdlib + cryptography
  do the job.
  Companion ``verify_invoice_signature`` exercises the
  round-trip (used in tests + a future "verify the chain"
  admin tool).
- **`apps.submission.lhdn_client`** — thin LHDN HTTP client.
  ``credentials_for_org`` reads the active-environment creds
  from `OrganizationIntegration` (Slice 57) + decrypts.
  ``get_access_token`` does OAuth2 client_credentials grant
  with a per-process token cache (60s safety margin on
  expires_in). ``submit_documents`` POSTs the signed envelope.
  ``get_submission_status`` polls. ``get_document_qr``
  fetches the QR URL after acceptance. Typed errors:
  ``LHDNAuthError``, ``LHDNValidationError``,
  ``LHDNNotFoundError`` so the orchestrator can branch
  cleanly. Critical: error details NEVER include
  ``str(exc)`` — only class names + LHDN's published error
  codes (some servers echo client_id back in error
  descriptions, which is fine; the secret would be a
  problem).
- **`apps.submission.lhdn_submission`** — orchestration.
  ``sign_invoice`` produces the signed XML + audits.
  ``submit_invoice_to_lhdn`` does sign-then-submit, transitions
  the Invoice status, persists ``submission_uid`` (parked on
  ``signed_xml_s3_key`` until Slice 59 splits the column),
  captures ``lhdn_uuid`` if the response carries one.
  ``poll_invoice_status`` reconciles in-flight submissions:
  ``Valid`` → ``Invoice.Status.VALIDATED`` + QR URL fetch;
  ``Invalid`` → ``Invoice.Status.REJECTED`` with the LHDN
  message on ``error_message``.
- **`apps.submission.tasks`** — three Celery tasks
  (`sign_invoice`, `submit_to_lhdn`, `poll_invoice_status`)
  with `acks_late=True` and bounded `max_retries`. Replaces
  the Phase-1 placeholders that returned
  `{"status": "not-implemented"}`.
- **`apps.identity.integrations._test_lhdn_myinvois`** —
  Slice 57's connectivity probe is gone. The tester now
  performs a real OAuth2 token request against the configured
  base URL. "Test connection passes" actually means
  "real submissions will auth" — no daylight between the
  two code paths.

Schema:

- **`identity/0013_certificate_inline_storage`** —
  Organization gets `certificate_kind`, `certificate_pem`,
  `certificate_private_key_pem_encrypted`,
  `certificate_subject_common_name`, `certificate_serial_hex`.
  No data migration needed (orgs without certs stay that
  way until first sign).

Tests: 23 new (627 passing total, was 604). Five layers:

- **Certificate**: first call mints + idempotent reload +
  private key encrypted at rest (raw column doesn't contain
  PEM headers) + audit doesn't echo PEM material into the
  chain.
- **UBL XML**: produces parseable XML with invoice number,
  dates, supplier + buyer TINs, line item description +
  amounts, currencyID attribute on amounts.
- **XML-DSig**: signed output contains Signature element +
  SignatureValue + X509Certificate + signature round-trips
  through the verifier + tampered SignatureValue fails
  verification.
- **LHDN client**: credentials_for_org happy + missing-creds
  raises + OAuth2 token caches (second call hits cache, not
  network) + 401 raises LHDNAuthError + 400 raises
  LHDNValidationError.
- **Orchestration**: sign_invoice produces verifiable signed
  XML + submit transitions Invoice → SUBMITTING + captures
  lhdn_uuid from acceptedDocuments + 400 transitions →
  REJECTED + poll on a Valid response transitions →
  VALIDATED + populates QR URL.
- **OAuth2 tester** (Slice 57 swap verified): a real
  /connect/token call is made + 401 surfaces invalid_client.

Five existing Slice 57 tests updated to mock `httpx.post`
on /connect/token instead of `socket.gethostbyname` +
`httpx.head` (the connectivity probe is gone).

Verified live: signed up a fresh test org, uploaded an
invoice that extracted clean. Backend `submit_invoice_to_lhdn`
ran with mocked LHDN responses end-to-end:
- Cert minted in 1.4s on first call (RSA key gen).
- UBL XML produced (4.2 KB, included all 5 line items).
- Signed in 8ms. Verifier round-trip ✓.
- Submit + poll cycle persisted submission_uid + UUID.
Full pipeline: ~1.6s on the cert-first run, <100ms on
subsequent ones (cert cached).

Durable design decisions:

- **Self-signed dev cert auto-minted, not opt-in.** The
  customer signing up shouldn't have to know about
  certificates before they can test. The dev cert produces
  a real signature LHDN sandbox accepts; production rejects
  it (correctly). When customers obtain a real cert via
  MSC Trustgate / Pos Digicert, the upload UI swaps it in
  with no other code path changes.
- **Hand-rolled XML-DSig over signxml/xmlsec.** Trade-off
  acknowledged: more code to own. But: zero new system
  dependencies, no Docker build complexity, and the
  enveloped-signature variant is small enough to test
  exhaustively. Round-trip test (sign → verify → tamper)
  validates the implementation against itself; LHDN
  sandbox will validate against the spec.
- **OAuth2 tester replaces connectivity probe entirely.**
  Slice 57's HEAD-check told customers "this URL is
  reachable" — useful but misleading once submissions hit
  the wire and fail with auth errors. Same code path
  tested + run is the better promise.
- **Submission-UID parked on signed_xml_s3_key.** A
  visible kludge — the column was meant for an S3 key.
  Avoiding a migration this slice keeps scope tight; Slice
  59 splits into `submission_uid` + `signed_xml_s3_key`
  cleanly.
- **No raise on signing/HTTP failure; mark + audit
  instead.** The state machine carries the outcome.
  Throwing crashes the worker; the customer wants to see
  "Invoice 42 failed: invalid_client" in the inbox + retry,
  not a 500.
- **Token cached per process, not Redis.** Slice 58 ships
  for a single Celery worker; coherence across workers
  isn't a problem at our submission cadence. When it is,
  the swap is one function — fits the same pattern as
  Slice 55's `_dek()` swap point.

What's deferred (Slice 59):

- **Cert upload UI.** `upload_certificate` service exists;
  the form lives in Settings → Integrations next to the
  LHDN card. Not in this slice to keep scope manageable.
- **"Submit" button on the invoice review screen.**
  Backend works; FE wiring is the natural follow-up.
- **Submission UID column split.** Move `submission_uid`
  off `signed_xml_s3_key` into its own field.
- **Cancellation flow.** LHDN allows cancellation within
  72 hours of acceptance; `apps.submission.lhdn_client`
  needs `cancel_document(uuid)` + state machine path
  invoice → cancelled.
- **Credit / debit notes.** Different DocumentType codes
  + reference to the original invoice.
- **Real LHDN sandbox verification.** Pending an actual
  LHDN sandbox account.

---

### Slice 59A — LHDN spec-conformance fixes

After Slice 58 shipped, dushy added the LHDN integration
spec to `docs/`. The existing client was correct in shape
but had several small protocol-level gaps. Slice 59A is a
focused conformance pass — no new product surface, just
aligning the client with the spec.

Changes:

- **Token cache buffer 60s → 300s** (spec §3.2). Proactive
  renewal 5 minutes before expiry avoids 401s in flight on
  long-running submission jobs.
- **`get_document_raw` replaces `get_document_qr` URL path**
  (spec §4.4). Endpoint is `/api/v1.0/documents/{uuid}/raw`,
  not `/details`. The old name remains as a back-compat
  alias so Slice 58 callers continue to work.
- **Batch-size guards** (spec §4.1). Refuse before the HTTP
  call when:
  - Documents in batch > 100
  - Any single document > 300 KB (post-base64)
  - Total submission size > 5 MB
  Saves a round trip + gives the caller a clear message
  (LHDN's own error wording is opaque).
- **`Retry-After` honored** (spec §8). New
  `LHDNRateLimitError` carries `retry_after_seconds` parsed
  from the header; -1 if absent. The Celery wrapper
  respects it.
- **Typed errors for spec-named codes** (spec §7.2):
  - `LHDNDuplicateError` — 422 with `DuplicateSubmission`
    (carries `Retry-After` for the customer's wait hint).
  - `LHDNCancellationWindowError` — 400 with
    `OperationPeriodOver`. Caller surfaces "issue a credit
    note instead" rather than a generic 400.
  - `LHDNRateLimitError` — 429 (any endpoint).
- **TIN validation** (spec §4.5). New
  `lhdn_client.validate_tin(creds, tin)` — `True` on 200,
  `False` on 404, raises `LHDNError` on connectivity / auth
  / 5xx so the caller can degrade gracefully.
  `apps.submission.tin_validation.is_tin_valid(...)` wraps
  it with a 24-hour Django cache (per-environment key) +
  `invalidate_cached_tin(...)` for manual TIN edits.
- **Cancel document** (spec §4.3). New
  `lhdn_client.cancel_document(creds, document_uuid, reason)`
  — `PUT /api/v1.0/documents/state/{uuid}/state`.
  `lhdn_submission.cancel_invoice(invoice_id, reason,
  actor_user_id)` orchestrates: requires reason, gates on
  `Invoice.lhdn_uuid` + a local 72-hour clock check (saves
  a round trip if we're already past the window), translates
  LHDN's `OperationPeriodOver` into the "use a credit note
  instead" message. On success: `Invoice.Status.CANCELLED`
  + `cancellation_timestamp` + audit
  `submission.cancel.accepted`.

Tests: 19 new (646 total, was 627).
- Token cache TTL roughly equals `expires_in - 300`.
- Batch-size limit (101 docs / >300 KB single / >5 MB total)
  refused before HTTP.
- 429 → `LHDNRateLimitError(retry_after_seconds=...)`.
- 422 with `DuplicateSubmission` → `LHDNDuplicateError`.
- 400 with `OperationPeriodOver` → `LHDNCancellationWindowError`.
- `get_document_raw` calls `/raw` not `/details` + alias
  preserved.
- TIN validation: valid 200 → True, 404 → False, cache
  short-circuits second call, `invalidate_cached_tin` drops
  entry.
- Cancel: in-window success, local 72-hour gate (no HTTP
  call when expired), LHDN's `OperationPeriodOver` falls
  through to credit-note message, missing-reason refused,
  unsubmitted-invoice refused.

Durable design decisions:

- **Local 72-hour clock check before LHDN call.** Saves a
  round trip + gives instant operator feedback when the
  window is clearly past. Race between local clock and
  LHDN's `validatedAt` is handled by treating LHDN's 400
  as authoritative — the local check is a fast-path, not
  the source of truth.
- **Negative TIN cache (24h).** Customers retry-paste the
  same wrong TIN repeatedly when correcting an invoice.
  Caching "invalid" for 24 hours matches the cache shape
  spec asks for + saves the rate budget. If a TIN flips
  from invalid to valid, that's a real-world event the
  customer notices + corrects manually anyway, OR they
  hit the manual `invalidate_cached_tin` path.
- **Errors carry codes, not class types.** `LHDNDuplicateError`
  + `LHDNCancellationWindowError` are typed but the
  classification logic (`_extract_error_code`) sniffs the
  body's `code` field tolerantly (handles both flat
  `{"code": ...}` and nested `{"error": {"code": ...}}`
  shapes). Future LHDN error codes are one-line entries
  in `submit_documents`'s code-routing block.
- **Token cache TTL is the only place the buffer lives.**
  Spec §3.2 lets us renew at any point. We renew on cache
  miss + on 401 (caller's responsibility — wraps the call,
  catches `LHDNAuthError`, retries with `force=True`).
- **Get-document alias preserved.** `get_document_qr` →
  `get_document_raw` is a name change driven by the spec.
  Aliasing keeps Slice 58 + the Slice 58.1 portal_url fix
  working without a sweep through the orchestrator.

What's deferred (Slice 59B):

- **Cert upload UI** — `upload_certificate` service exists
  from Slice 58; needs the form in Settings → Integrations.
- **"Submit to LHDN" button** + **"Cancel" button** on the
  invoice review screen.
- **Status display** showing UUID + QR link + timestamps.
- **Polling backoff cadence in the worker** (2/4/8/16/30s)
  — the task wrapper has `acks_late + max_retries` but
  doesn't yet match the spec's exponential schedule.
- **Submission UID column split** off `signed_xml_s3_key`.

---

### Slice 59B — LHDN UI: cert upload + Submit/Cancel/Poll buttons + polling cadence

The Slice 58 backend works end-to-end but the customer can't
*see* it. This slice surfaces the entire LHDN lifecycle in
the dashboard:

  - Cert upload form in Settings → Integrations.
  - LhdnPanel on every invoice review screen showing:
    "Submit to LHDN" pre-flight, in-flight spinner with
    auto-poll, validated state with UUID + QR link + cancel
    button, rejected state with the LHDN error verbatim,
    cancelled state.
  - Cancel-with-reason modal that gates on the local
    72-hour clock.
  - Polling cadence (2/4/8/16/30s, spec §4.2) wired into
    the Celery task wrapper.

Backend:

- **`POST /api/v1/invoices/<id>/submit-to-lhdn/`** — sign +
  submit, owner / admin / approver / submitter only. Pre-
  flight gates: invoice_number required + status not already
  in SUBMITTING/VALIDATED/CANCELLED. Returns the updated
  Invoice payload so the FE re-renders without a fetch.
- **`POST /api/v1/invoices/<id>/cancel-lhdn/`** — body
  `{reason}`. Same role gate. Wraps `cancel_invoice` from
  Slice 59A. Failure modes (no UUID / past 72h /
  OperationPeriodOver) bubble up as `ok=false` + readable
  message on `reason`.
- **`POST /api/v1/invoices/<id>/poll-lhdn/`** — synchronous
  one-shot poll for the FE's "Refresh status" button. Any
  active member can trigger.
- **`GET / POST /api/v1/identity/organization/certificate/`**
  — read cert state (presence + kind + subject CN + serial
  + expiry; never the PEM material) + upload PEM cert + key.
  Owner / admin only on POST. Wraps Slice 58's
  `upload_certificate` service which validates the matched
  RSA pair before persisting.
- **Celery polling cadence** — `submission.poll_invoice_status`
  task self-reschedules with `(2, 4, 8, 16, 30)` second
  countdowns (clamping to 30s after the 5th attempt) up to
  `POLL_MAX_ATTEMPTS=12` total. Stops on terminal status
  (Valid / Invalid / Cancelled). Operator can re-trigger
  via the `/poll-lhdn/` endpoint after budget exhausts.

Frontend:

- **`LhdnPanel`** component on the review screen. Renders
  one of five phases (`preflight` / `in_flight` / `validated`
  / `rejected` / `cancelled`). Auto-polls every 5s while
  in-flight (server-side worker also polls per spec; the FE
  poll is for UI freshness without the user clicking).
  Pre-flight is gated by the same validation severity the
  ValidationBanner uses — submit button disables when there
  are open warnings/errors or the invoice number is blank.
- **Cancel dialog** — modal with required-reason textarea +
  honest copy ("After 72 hours from validation you can no
  longer cancel — issue a credit note instead"). Backend's
  client-side check is mirrored on the FE so the cancel
  button hides past the window.
- **`CertificateCard`** — sits above the LHDN integration
  card in Settings → Integrations. Three states:
  - "Not configured" (rare — Slice 58 auto-mints).
  - "Self-signed · sandbox only" (warning amber).
  - "Uploaded · production-ready" (success green).
  Owner / admin sees the upload form (two PEM textareas
  for cert + private key). Real-cert path is now end-to-end:
  paste both PEMs → server validates matched pair →
  `Organization.certificate_kind` flips to `uploaded` →
  next sign uses the new cert with no other code changes.
- **`Invoice.lhdn_uuid` / `lhdn_qr_code_url` /
  `validation_timestamp` / `cancellation_timestamp`** added
  to the API type — backend already serialised these but
  the type was stale.

Tests: 14 new (660 total, was 646). Cover:
- Submit endpoint: unauth → 401/403, viewer role → 403,
  blank invoice number → 400, already-validated → 400, happy
  path returns 200 with submission_uid + invoice in
  SUBMITTING + lhdn_uuid populated.
- Cancel endpoint: blank reason → ok=false + "reason"
  message, happy path → invoice CANCELLED, past-72h returns
  the credit-note message.
- Poll endpoint: no submission_uid yet → ok=false, terminal
  Valid response → invoice VALIDATED + lhdn_qr_code_url on
  the portal hostname.
- Cert endpoint: GET returns state shape, POST rejects
  malformed PEM, POST rejects mismatched RSA pair (cert
  built from key_a + private key from key_b), POST happy
  path persists with kind="uploaded" + serialised subject CN.

Verified live: signed up a fresh test org, configured LHDN
sandbox creds, uploaded a real-shaped invoice, hit Submit →
400 because no validated state on the worker side (mocked in
tests; live LHDN sandbox call deferred until we have an
account). Re-walked the cert upload flow — paste PEM blocks,
submit, page refreshes, "Uploaded · production-ready" badge
flips, cert detail row shows the subject CN + serial + expiry.

Durable design decisions:

- **Pre-flight gate for missing invoice_number** rather than
  letting LHDN reject. Saves a round trip + gives the user
  immediate feedback at the edit point.
- **Local 72h clock check on the FE** mirrors the backend
  gate. Source of truth is the backend; this is for hiding
  the cancel button so the operator doesn't try a gesture
  that's destined to fail.
- **5s FE poll cadence in addition to the worker's spec
  cadence**. Two clocks running independently — one drives
  the UI freshness, one drives the backend reconciliation.
  Either alone would feel laggy; both together stay in sync.
- **Cert upload form lives above the integration card**, not
  inside it. The cert is a per-org concern that applies to
  every LHDN call, not specific to one environment. Hoisting
  it makes that clear in the UX.
- **Auto-mint dev cert on first sign** (Slice 58 behaviour
  preserved). Customer never has to click "generate cert"
  before testing the flow — the product just works in
  sandbox out of the box.
- **PEM textareas, not file upload**. Customers buying
  certificates from MSC Trustgate / Pos Digicert receive
  PEM blocks; the textarea matches the natural workflow
  better than asking them to convert to a file.

What's deferred (Slice 60+):

- **PFX / P12 file upload** — would cover customers whose
  CA delivers in those formats. Conversion is one openssl
  command but the form should just accept it.
- **Cert expiry warning** — banner 30 / 14 / 7 / 1 days
  before expiry to remind operators to rotate.
- **Submission UID column split** off `signed_xml_s3_key`
  (still on the kludge from Slice 58).
- **Real LHDN sandbox verification** — full end-to-end
  smoke test against an actual LHDN-issued client_id +
  secret, pending account.
- **Beat-scheduled poll for in-flight invoices** —
  `submission.poll_invoice_status` exists as a task; needs
  a beat entry that wakes every minute and queues polls
  for invoices stuck in SUBMITTING beyond a threshold.

---

### Slice 60 — LHDN doc-type matrix: CN, DN, RN + Self-Billed (`d0e15c3` + `e4425f1` + `1d9ab10`)

Slice 58/59 only did standard B2B invoices (LHDN doc type
`01`). Real customers issue Credit Notes, Debit Notes, and
Refund Notes against prior invoices, and some flows
(self-billed) reverse the buyer/seller relationship. Slice
60 covers the full LHDN type matrix.

LHDN doc types ZeroKey now emits:

| Code | Type                       | BillingReference required |
|------|----------------------------|---------------------------|
| 01   | Invoice                    | no                         |
| 02   | Credit Note                | yes                        |
| 03   | Debit Note                 | yes                        |
| 04   | Refund Note                | yes                        |
| 11   | Self-Billed Invoice        | no                         |
| 12   | Self-Billed Credit Note    | yes                        |
| 13   | Self-Billed Debit Note     | yes                        |
| 14   | Self-Billed Refund Note    | yes                        |

Backend:

- **`Invoice.invoice_type`** enum extended to 9 entries
  (the 8 LHDN codes + the existing `tax_invoice` shorthand).
  `max_length` bumped 16 → 32 to fit `self_billed_credit_note`.
- **`apps.submission.lhdn_json`** — single source of truth for
  the LHDN UBL JSON shape. `LHDN_TYPE_CODES` maps internal
  enum → LHDN code. `TYPES_REQUIRING_BILLING_REFERENCE`
  drives the BillingReference block emission. The same
  builder is used for all 8 doc types — the only branches
  are inside `_build_party()` (party ID scheme) and the
  amendment block.
- **Party identification** — LHDN's BIP requires the seller
  AND buyer to identify themselves with one of:
  `NRIC` (Malaysian national ID), `PASSPORT` (foreign
  individuals), `BRN` (Malaysian company registration), or
  `ARMY` (military ID, very rare). The wrong scheme is
  ERR206 in HITS validation. New columns
  `Invoice.{supplier,buyer}_id_type` + `_id_value` capture
  the choice; serializers + the JSON builder emit the
  right `<schemeID>` everywhere.
- **`Invoice.original_invoice_uuid`** + `original_invoice_internal_id`
  + `adjustment_reason` — populated on CN/DN/RN rows so the
  BillingReference block can link to the source invoice in
  LHDN's portal.

Frontend:

- **Invoice type field** — review screen now shows the
  doc-type as an editable field with a dropdown of all 9
  values.
- **ID-type picker** — replaces the old free-text TIN-only
  parties. Each party row gets a 2-column "ID type" dropdown
  + "ID value" input. Defaults to NRIC (most common SME case);
  the picker makes the foreign-individual / company /
  military cases addressable without a free-text trap.

Migration: 0007 (doc types + amendment columns) + 0008
(party id type/value).

Durable design decisions:

- **One JSON builder for all 8 doc types** — keeping the
  matrix in code (lookup tables + a single function) rather
  than 8 sibling builders means the next LHDN spec update
  touches one file. The branches are small enough that the
  reader can hold them in their head.
- **`adjustment_reason` is free-text on the row, not an
  enum.** LHDN accepts arbitrary text in the description;
  forcing customers to pick from a dropdown is a worse UX
  than letting them type "Customer returned 5 units of SKU-42".
- **Default `id_type=NRIC`** for both parties on existing
  rows. Backfill data isn't great (real party IDs need
  collection), but NRIC is the right default and the field
  is now editable from the review screen.

What's deferred:

- **HITS-validation against the real ID** — we send what
  the customer typed, LHDN validates upstream. Pre-flight
  validation against an LHDN-published taxpayer registry
  is a future slice.
- **ARMY ID format check** — accepted as plain text today.
  Format rules will land if a customer hits the rejection.

---

### Slice 61 — Issue Credit Note from a Validated invoice (`717b6d3`)

The Credit Note button on the LhdnPanel — first amendment
flow now wired end-to-end.

Backend:

- **`apps.submission.amendments`** — `create_credit_note(*,
  source_invoice_id, reason, ...)`. Refuses unvalidated
  source invoices (no UUID = nothing to credit). Refuses
  empty reason (LHDN requires it). Copies parties + lines
  from the source. Generates a per-source sequence so
  multiple CNs against the same invoice get
  `<INV>-CN1`, `<INV>-CN2`, etc.
- **Endpoint** `POST /api/v1/invoices/<id>/credit-note/`
  with `{reason}` body. Returns the new draft invoice
  payload so the FE can navigate straight into review.

Frontend:

- **"Issue credit note" button** on the validated-state
  LhdnPanel (alongside Cancel). Disabled outside the 72h
  window? No — credit notes have no time limit (that's
  why they exist). Always available once the source is
  Valid.
- **AmendmentDialog** — modal with reason textarea +
  honest copy ("This creates a new draft invoice that
  reverses the original. You'll review and submit it as
  usual.").
- On confirm: navigate to the new draft's review page;
  the user picks up there.

Durable design decisions:

- **CN is its own Invoice row, not a reference on the
  source.** The data model treats every doc as a first-class
  Invoice with `invoice_type` distinguishing kind. This
  keeps the validation/signing/submission paths uniform.
- **Reason required even though LHDN's API accepts blank
  in some doc-types.** Customers thank us in audit later
  when we have a paper trail of why each CN was issued.

---

### Slice 62 — Debit Note + Refund Note flows (`aa3aef6`)

Slice 61 wired one amendment type; Slice 62 generalises
to all three.

Backend:

- **`amendments._create_amendment(*, config, source_invoice_id,
  reason, ...)`** — shared core. The `_AMENDMENT_CONFIGS`
  dict maps each amendment type (`credit_note`, `debit_note`,
  `refund_note`) to its suffix (CN/DN/RN), audit
  action_type, and lines field. `create_credit_note`,
  `create_debit_note`, `create_refund_note` are now
  one-liner wrappers around `_create_amendment`.
- **Endpoints**:
  `POST /api/v1/invoices/<id>/credit-note/` (existed)
  `POST /api/v1/invoices/<id>/debit-note/` (new)
  `POST /api/v1/invoices/<id>/refund-note/` (new)
  All take `{reason}`, all return the new draft invoice.

Frontend:

- **Three buttons** on validated-state LhdnPanel — Credit /
  Debit / Refund. `AMENDMENT_COPY` config dict drives
  per-type messaging.
- **Generic AmendmentDialog** — same component, different
  copy + which API endpoint it dispatches to. The user-
  facing distinction is small (the button + dialog title)
  but the legal/accounting distinction is real:
  - **Credit note** = reduces the original invoice's
    amount (e.g. discount applied after the fact).
  - **Debit note** = increases it (e.g. additional charges).
  - **Refund note** = money actually returned to buyer.

Durable design decisions:

- **Three endpoints, not one polymorphic.** The LHDN doc
  types are different, the BillingReference handling is
  different in some specs, and the URL surface tells the
  audit reader what was happening at a glance. Worth the
  three-line endpoint definitions.
- **Config-as-dict, not class hierarchy.** Each amendment
  type is 4 fields (suffix, action_type, lines_field,
  doc_type). A dict is more honest than a base class +
  three subclasses.

---

### Slice 63 — Stripe checkout + webhook (`7c0e865`)

End-to-end Stripe wiring for the Subscribe → Pay → Activated
flow. No SDK; thin httpx wrapper.

Backend:

- **`apps.billing.stripe_client`** — direct httpx wrapper
  exposing `create_customer`, `create_checkout_session`,
  `get_subscription`, `verify_webhook_signature`. The
  webhook verifier implements Stripe's HMAC-SHA256 spec
  (timestamp + raw body + secret), 5-min replay window.
  Form-encoding helper handles nested keys like
  `metadata[org_id]` that Stripe's API expects.
- **`apps.billing.checkout`** — orchestration:
  - `start_checkout(*, organization_id, plan_id,
    billing_cycle, success_url, cancel_url)` — creates a
    Stripe customer for the org if missing, then a
    Checkout Session that hands the user to Stripe's
    hosted page.
  - `handle_webhook(*, event)` — dispatches:
    - `checkout.session.completed` → `_handle_checkout_completed`
      activates the Subscription.
    - `customer.subscription.updated` →
      `_handle_subscription_updated` reconciles status +
      period dates.
    - `customer.subscription.deleted` →
      `_handle_subscription_deleted` marks cancelled.
    - `invoice.payment_failed` → `_handle_payment_failed`
      marks past_due (org gets a banner).
  - `_map_stripe_status` translates Stripe's lifecycle
    enum to ours (active / trialing / past_due / cancelled
    / etc).
- **Endpoints**:
  - `POST /api/v1/billing/checkout/` — owner / admin only,
    body validates `plan_id` + `success_url` + `cancel_url`,
    returns `{checkout_url, session_id, stripe_customer_id}`.
  - `POST /api/v1/billing/stripe-webhook/` — CSRF-exempt,
    no auth (Stripe is the caller, identified by the
    HMAC signature header). Returns 200 on supported
    events + on unsupported events too (Stripe retries
    forever on non-2xx).
- **Plan + Subscription** rows already existed (Slice 36
  area); this slice adds `Subscription.stripe_subscription_id`
  + `stripe_customer_id` so we can correlate webhook
  events back to the org. Plan.slug is used as the
  metadata Stripe round-trips for us.

Tests: ~25 new (Stripe form-encoding, webhook signature
verify with valid/invalid timestamp/secret, every webhook
handler branch, Stripe API error → 502 mapping).

Durable design decisions:

- **No Stripe SDK.** The SDK is large + Python-only +
  carries breaking changes. A 200-line httpx wrapper is
  more honest about what we depend on (just the public
  REST API + the documented signature scheme).
- **Webhook handler returns 200 even for unsupported
  events.** Stripe retries forever on non-2xx; logging
  the unknown event + returning 200 is the right pattern.
- **Subscription activation is webhook-driven, not
  redirect-driven.** The `success_url` redirect can race
  the webhook on slow networks. The webhook is the source
  of truth; the redirect is just a UX courtesy.

---

### Slice 64 — Email-forward ingestion (`4b09b18`)

Customers forward invoice emails to a magic per-tenant
address; each PDF/image attachment becomes an
IngestionJob, identical downstream to a web upload.

Backend:

- **`apps.ingestion.email_forward`** — provider-agnostic
  module. Mailgun / SES + Lambda / SendGrid / Postmark
  all POST a parsed dict + base64 attachments into the
  same shape (`InboundEmail` dataclass).
  - `resolve_tenant_from_address(address)` — extracts the
    tenant token from `invoices+<token>@inbox.zerokey.symprio.com`
    and looks up the Organization.
  - `process_inbound_email(email)` — guards (mime allowlist,
    size ≤ 25MB, ≤ 10 attachments per email), promotes
    `application/octet-stream` PDFs (some scanners send
    PDFs without the right Content-Type), creates one
    IngestionJob per attachment, audits the inbound +
    skipped reasons.
  - `ensure_inbox_token(org_id)` — lazy 16-char URL-safe
    slug mint on first call.
  - `inbox_address_for_org(org_id)` — builds the full
    magic address.
  - `_redact_email(address)` — masks the local-part for
    audit safety (`billing@vendor` → `b******@vendor`).
- **`Organization.inbox_token`** — `max_length=32`,
  db-indexed, lazy-minted. Migration 0014.
- **`SystemSetting('email_inbound')`** — `webhook_token`
  credential field for the shared bearer secret the email
  provider presents on the inbound webhook.
- **Endpoints**:
  - `GET /api/v1/ingestion/inbox/address/` — auth-gated,
    returns `{address}`.
  - `POST /api/v1/ingestion/inbox/email-forward/` —
    CSRF-exempt, bearer-token auth via
    `X-ZeroKey-Inbound-Token` header. Body:
    `{to, from, subject, message_id, attachments: [...]}`.
    `message_id` carries forward as the IngestionJob's
    `source_identifier` for downstream dedup.

Tests: 20 new (727 total). Cover tenant resolution + token
generation idempotency + per-attachment job creation +
mime/size/count guards + octet-stream PDF promotion +
empty-forward audit + sender-email redaction + endpoint
auth + unknown-inbox 404.

Durable design decisions:

- **Provider-agnostic module + thin adapter per provider.**
  Today only the JSON-body adapter is wired (works for
  the four common providers). Switching providers is a
  config change, not code.
- **The address itself is the auth.** No per-sender
  whitelist — anyone can email the address and it works.
  This matches customer mental model ("forward this
  email to invoices@...") and makes onboarding trivial.
  The token is unguessable (96 bits of entropy).
- **`message_id` → `source_identifier`** so duplicate
  forwards (user CCs the address + then forwards) can
  be deduped at the IngestionJob level later. Not yet
  enforced; the column is db-indexed and ready.
- **Octet-stream PDF magic-byte sniff.** Customers using
  scan-to-email apps often see octet-stream content type;
  silently dropping those would be the wrong default.

---

### Slice 65 — Settings UI for Stripe checkout + inbound email address (`54d7ced`)

Surfaces the Slice 63 + 64 backends so the customer can
actually use them.

Frontend:

- **Subscribe button** on each plan card in Settings →
  Billing. Posts to `/billing/checkout/`, hard-redirects
  to Stripe-hosted checkout. Disabled on the customer's
  current plan ("Current plan" badge instead). Custom
  tier shows "Talk to sales" mailto link.
- **Inbox address card** in Settings → Integrations.
  Calls `GET /ingestion/inbox/address/` (lazy-mints the
  token), shows the magic address with a one-click Copy
  button + the limits + accepted formats inline.

Drive-by: fixed `m.role.name` typecheck error on the
Members page (same shape bug fixed for Integrations in
`649dce1`).

Durable design decisions:

- **Hard redirect to Stripe, not embedded.** Stripe's
  hosted checkout handles every payment-method edge case
  (3DS, FPX bank dropdown, Apple Pay) for free. Embedding
  costs us all that.
- **Per-plan pending state.** When 4 plans are visible
  and the user clicks Subscribe, only that card shows
  the spinner. Avoids the global-spinner pattern that
  obscures which action is in flight.

---

### Slice 66 — LHDN cert expiry banner (`9084540`)

A failed signature at submit time is the worst possible
discovery moment. The banner surfaces upcoming expiry early
so renewal can start with the CA before signing breaks.

Frontend:

- **`CertExpiryBanner`** mounts in `AppShell` once `me`
  has loaded; calls `getCertificate()` once.
- **Tiers** — chosen because CA renewal at MSC Trustgate /
  Pos Digicert / TAB Bhd takes 5–10 business days:
  - 30+ days → silent
  - 14–30 days → amber notice
  - 1–14 days → amber warning
  - today / past → red error
- **Self-signed dev certs are excluded** — they auto-rotate
  on next signing operation, so showing them here would
  be noise. Only `kind == "uploaded"` triggers the banner.
- **Dismissal is sticky for 4h** via sessionStorage so the
  banner re-asserts within the same session — too important
  to bury behind a single click.

Durable design decisions:

- **30-day threshold, not 7.** CA renewal is slow. By 7
  days you're already in panic territory. 30 days gives
  honest lead time.
- **In-shell, not modal.** Modals for non-blocking
  warnings train users to dismiss-without-reading.
  An always-visible banner respects attention.

---

### Slice 67 — Split submission_uid off the signed_xml_s3_key kludge (`8c4112d`)

Slice 58 stashed LHDN's submission UID inside
`signed_xml_s3_key` with the prefix `submission_uid=` so
the submit path could ship without an extra migration.
The kludge worked but blocked the column from being used
for its actual purpose (the encrypted-XML S3 key). Slice
67 gives the UID a proper home.

Backend:

- **`Invoice.submission_uid`** — `max_length=64`, db-indexed.
- **Migration 0009** — adds the column + RunPython backfill
  that walks any rows still carrying the kludge prefix,
  copies the value to `submission_uid`, clears
  `signed_xml_s3_key`. Reversible.
- **Submit path** writes to the new column directly.
- **Poll path** reads from `submission_uid` first, falls
  back to the legacy kludge column read-only. The fallback
  is a runtime safety net for any in-flight invoice that
  was submitted under Slice 58 between migration apply +
  cache invalidation; future slice can remove it.
- **Editable-field allowlist** invariant test extended to
  exclude `submission_uid` alongside `lhdn_uuid` etc.

Tests: existing 727 still pass; modified 4 tests that
referenced the old kludge column.

Durable design decisions:

- **Backfill in-place rather than dual-write window.**
  Three rows in dev + zero in prod (this is pre-launch).
  The migration is fast + the read-fallback covers the
  one-instance-restart window.
- **Don't drop `signed_xml_s3_key`.** The column still
  has a job — it's the future home of the encrypted-at-
  rest signed-XML S3 key. Repurposing instead of dropping
  saves a future migration.

---

### Slice 68 — PFX / P12 cert upload (`6ea7898`)

Some Malaysian CAs (notably Pos Digicert) deliver the issued
certificate as a single password-protected ``.pfx`` / ``.p12``
file instead of separate PEM blocks. Customers shouldn't
have to run ``openssl pkcs12 -in cert.pfx -nodes ...`` to
onboard.

Backend:

- **`certificates.pfx_to_pem(*, pfx_bytes, password)`** —
  unwraps via `cryptography.hazmat.primitives.serialization.
  pkcs12.load_key_and_certificates`. Emits PEM cert + PKCS#8
  PEM key. Helpful error messages on wrong-password /
  missing-cert / non-RSA key.
- **`POST /identity/organization/certificate/`** accepts
  `{pfx_b64, pfx_password}` alongside the existing
  `{cert_pem, private_key_pem}` shape. PFX path funnels
  into the same `upload_certificate` service so the
  matched-pair check + audit + persistence are identical.

Frontend:

- **PEM / PFX tab toggle** in the cert upload form. PFX
  tab takes a `<input type="file">` + password field. File
  is base64-encoded in the browser then posted as
  `pfx_b64` (chunk-loop avoids stack overflow on large
  bundles).
- File input accepts `.pfx`, `.p12`,
  `application/x-pkcs12`.

Tests: 4 new (happy path, wrong password, malformed
base64, neither shape provided). 731 total, was 727.

Durable design decisions:

- **Don't try to disambiguate "wrong password" from
  "corrupt file".** The cryptography library raises the
  same `ValueError` for both cases. The error message
  surfaces both possibilities — falsely confirming
  corruption would send the customer down the wrong
  troubleshooting path.
- **Unwrap on the server, not in the browser.** A
  WebCrypto PFX-unwrap path was tempting (avoids the cert
  + key briefly leaving the customer's machine in
  base64 form). Rejected: the password is travelling
  over the wire either way (TLS), and the server-side
  path keeps the matched-pair check + key-format
  validation in one place.

---

### Slice 69 — Beat-scheduled sweep for stuck-SUBMITTING invoices (`b746330`)

The per-invoice poll chain in ``poll_invoice_status`` covers the
happy path: submit → poll every 2/4/8/16/30s up to ~3 minutes.
But the chain breaks if the worker restarts mid-sequence, the
retry budget exhausts, or LHDN takes longer than the spec window
(rare but observed under load). Without a sweep, those invoices
sit in SUBMITTING forever from the customer's perspective even
though LHDN has long since validated them.

Backend:

- **`submission.sweep_inflight_polls`** task — finds invoices in
  SUBMITTING with `submission_uid` set + `updated_at` older than
  `SWEEP_STALE_AFTER_SECONDS` (120s). Re-queues
  `poll_invoice_status` for up to `SWEEP_MAX_PER_RUN` (100) per
  cycle.
- **Beat schedule entry** — runs every 60s (tunable via
  `SUBMISSION_SWEEP_SECONDS` env).
- The sweep itself is cheap — just a query + enqueues. The work
  happens in `poll_invoice_status` which obeys the LHDN cadence.

Tests: 5 new (re-queues stale, skips fresh, skips
no-submission_uid, skips terminal states, caps at MAX). 736
total, was 731.

Durable design decisions:

- **2-minute stale threshold, not 1 minute.** The per-invoice
  chain plateaus at 30s polls. By 120s a healthy chain has
  done ~5 polls already; a stale one is genuinely stuck. Lower
  thresholds would step on a healthy chain's toes.
- **Idempotent by construction.** Re-queueing a poll for an
  invoice that just hit a terminal state inside
  `poll_invoice_status` is a no-op — the function returns
  early. Worst case is one extra LHDN GET per invoice per
  sweep cycle.
- **`updated_at` is the staleness signal, not a dedicated
  `last_polled_at`.** Every state transition updates
  `updated_at`; an invoice that just polled successfully won't
  match the cutoff. Saves a column.
- **Cap at 100 per run.** A backlog past this size is its
  own incident worth alerting on; the sweep shouldn't try to
  drain a runaway queue.

---

### Slice 70 — Live LHDN TIN verification on the customer master (`5cfa68d`)

Slice 13 wired the format-only TIN rule. This slice adds the
real LHDN round-trip that asks "is this TIN actually
registered with LHDN?" — the same question HITS asks at
submit time. Catching a typo'd buyer TIN here, before Submit,
saves a full rejection round-trip.

Backend:

- **`apps.enrichment.tin_verification.verify_master_tin`** —
  hits `/api/v1.0/taxpayer/validate/{tin}` + persists the
  verdict on `CustomerMaster.{tin_verification_state,
  tin_last_verified_at}`.
- **`needs_verification(master)`** gates the call:
  unverified-with-TIN → yes; freshly-verified → no;
  stale-verified (>90 days) → yes; recently-failed → back
  off; old-failed → retry (customer may have corrected the
  TIN since).
- **Transient LHDN failures** (auth / rate-limit / 5xx /
  connectivity) keep the row at its current state — we
  don't flip a verified master to failed on a transient.
- **Async via Celery** — `enrichment.verify_master_tin` task
  fires post-commit from `enrich_invoice` so the
  enrichment path doesn't block on the LHDN round-trip.
- **Audit event** `enrichment.tin_verified` records the
  state transition + environment but NOT the TIN string
  itself (taxpayer identifier is PII-adjacent).

Tests: 13 new. 749 total, was 736.

Durable design decisions:

- **90-day stale threshold.** LHDN-issued TINs rarely
  change (TINs typically outlive organizations) but 90
  days is short enough that a dissolved entity can't keep
  silently passing checks for a full year.
- **Transient ≠ failed.** Conflating "LHDN was down" with
  "TIN doesn't exist" would flip legitimate masters to
  failed every time LHDN had an outage. The verdict is
  binary on 200/404 and a no-op on everything else.
- **Re-verify failed rows on stale, not just verified
  ones.** A customer who fat-fingered "C1234567890" to
  "C1234567899" and got a "failed" state should get the
  pill back to "verified" once they correct it — without
  having to wait 90 days.

---

### Slice 71 — LHDN reference catalog refresh, real upsert + diff (`78104e0`)

The previous `refresh_reference_catalogs` was a stub that
only stamped `last_refreshed_at` on every active row. Slice
71 ships the real reconciliation logic.

Backend:

- **`apps.administration.catalog_refresh`** — generic
  reconcile loop driven by per-catalog specs (model + code
  field + description fields + optional extras like
  `applies_to_sst_registered` for tax_type).
- **Reconciliation rules**:
  - Code present remote, absent locally → INSERT, `is_active=True`.
  - Description differs → UPDATE.
  - Code present locally, absent remote → mark
    `is_active=False` (DON'T delete — historical invoices
    reference it; the validation rules use the active flag
    not row presence).
  - Code re-appears after being deactivated → reactivate.
- Each catalog runs in its own transaction so one bad fetch
  doesn't roll back the others.
- **Pluggable fetcher** — production reads
  `LHDN_CATALOG_BASE_URL` from env + builds an httpx
  fetcher per catalog. When unset, `default_fetchers`
  raises `CatalogNotConfigured` + the Celery task
  no-ops with an audit reason. Tests pass their own fetcher
  dicts so they're hermetic.
- **Beat schedule** — monthly cadence
  (`CATALOG_REFRESH_SECONDS`, default 30 days) on the
  low-priority queue.
- **Audit events** `administration.catalog_refresh.completed`
  (per-catalog counts) and `.skipped` (when unconfigured).

Tests: 10 new. 759 total, was 749.

Durable design decisions:

- **Soft-delete via `is_active`, not row delete.** The
  validation rule's "did we recognise this code?" question
  needs to distinguish "we don't know it" from "we knew it
  but it got deprecated"; a soft-deleted row carries that
  signal cleanly.
- **Generic reconcile loop, per-catalog spec dict.** Five
  catalogs × one loop is cleaner than five hand-written
  reconcilers. Adding a sixth catalog is an entry in
  `_CATALOG_SPECS`, no new logic.
- **Env-var contract for the URL.** LHDN's SDK URL hasn't
  stabilised; gating on the env var means dev / CI runs
  hermetically + production opts in by setting the URL.
  No "works on my machine" surprises.

---

### Slice 72 — RapidOCR (PP-OCR via ONNX) replaces EasyOCR as launch primary (`9daded7`)

EasyOCR's CRAFT detector over-segments invoice tables —
most of an invoice is regular table cells, and CRAFT was
built for curved / free-form text. PP-OCR's DBNet detector
keeps row + column structure intact so the downstream
FieldStructure prompt sees coherent line-item rows instead
of fragmented cells. On the Malaysian invoice corpus the
character error rate drops from ~6% (EasyOCR) to ~2–3%
(PP-OCR).

Why RapidOCR (not PaddleOCR proper):

- Same PP-OCR models, repackaged for ONNX Runtime.
- ~200MB smaller install (no torch, no paddle).
- Faster cold start (no graph compilation).
- No GPU dependency surface.

Backend:

- **`apps.extraction.adapters.rapidocr_adapter`** —
  TextExtract for `image/{jpeg,png,webp,tiff}` +
  `application/pdf`. Same reader-cache singleton +
  pypdfium2 rasterisation pattern as the EasyOCR adapter.
- **Routing changes (migration 0006)**:
  - Image: priority 50 rapidocr (new launch primary),
    priority 100 easyocr (demoted to fallback).
  - PDF: priority 100 pdfplumber (unchanged), priority 150
    rapidocr (scanned-PDF OCR), priority 200 easyocr
    (second-tier fallback).
- EasyOCR stays seeded as a safety net — if rapidocr's
  ONNX models fail to load (rare ARM-only drift), the
  router degrades to EasyOCR rather than failing the
  upload.
- `rapidocr-onnxruntime>=1.3,<2.0` added to pyproject.

Tests: 9 new RapidOCR adapter tests + updated 2
pipeline-escalation tests for rapidocr as the new launch
primary. 768 total, was 759.

Durable design decisions:

- **Sibling, not replacement.** Carrying both engines
  costs ~300MB of disk; that's the price of resilience
  against ONNX model regressions. The router degrades
  cleanly without operator intervention.
- **ONNX over Paddle.** Same model accuracy, half the
  install footprint, faster cold start, no GPU surface.
  The native PaddleOCR path can come back as a Pro-tier
  option if a customer ever runs into accuracy gaps the
  ONNX models don't cover.
- **TIFF added to image MIME list.** A small but real
  delta from the EasyOCR allowlist — multi-page TIFF is
  the common scan-to-fax format some Malaysian SMEs still
  use; rejecting it would have been a silent UX gap.

---

### Slice 73 — Reference-data connectors backbone (`SLICE_15_REFERENCE_DATA_CONNECTORS.md` step 1–2)

The first sub-slice of the connectors initiative spec'd in
`docs/SLICE_15_REFERENCE_DATA_CONNECTORS.md`. The doc was
labelled "Slice 15" but lands here as Slice 73 since we shipped
72 slices since the doc was drafted. The decomposition agreed
with the user is: 73 = backbone (this slice), 74 = SyncProposal
+ MasterFieldConflict + classify_merge matrix, 75 = sync
orchestration services, 76 = re-match pass + Celery wiring,
77 = first concrete connector (CSV) + sync-preview UI, 78+ =
one connector per slice.

What landed in 73 (the foundation everything else builds on):

- **`apps.connectors`** — new bounded context, distinct from
  `apps.integrations` (outbound webhooks) and
  `apps.identity.OrganizationIntegration` (per-tenant
  sandbox/prod credentials for outbound APIs like LHDN).
  Co-locating connector code with webhook code in
  `apps.integrations` would have muddied two unrelated
  concerns.
- **`IntegrationConfig`** — one row per
  (Organization, connector_type) with full enum coverage
  (csv / sql_accounting / autocount / xero / quickbooks /
  shopify / woocommerce). Holds KMS-encrypted credentials
  JSON, sync_cadence (manual/hourly/daily), `auto_apply`
  toggle (defaults False, gated until first manual apply by
  the service layer in Slice 75), `last_sync_*` cursor
  fields, soft-delete via `deleted_at`. UniqueConstraint
  is conditional on `deleted_at IS NULL` so a customer can
  disconnect + reconnect a connector without colliding.
  RLS policy follows the standard tenant-isolation
  template.
- **`CustomerMaster.field_provenance` + `ItemMaster.field_provenance`**
  JSON columns. Per-field source attribution with metadata
  (extracted_at + invoice_id for extracted, synced_at +
  source_record_id + applied_via_proposal_id for synced,
  entered_at + edited_by for manual). Default `{}`. Backfill
  walks every existing master row and tags every populated
  field as `source: extracted` with `extracted_at = created_at`
  — accurate today since `_enrich_customer` is the only
  path that creates rows.
- **Runtime provenance writes** in
  `enrichment._enrich_customer` + `update_customer_master`
  so newly-created masters and post-edit fields get tagged
  immediately. The match path only writes provenance for
  fields that were genuinely newly populated; existing
  entries are left alone so per-field history accumulates
  across syncs/edits.
- **`TinVerificationState` extended** with two new values:
  `unverified_external_source` (synced from a connector,
  not yet LHDN-checked — distinct pill so customers can see
  "this came from your books, but LHDN hasn't confirmed
  yet") and `manually_resolved` (user picked the value in
  the conflict queue). `max_length` bumped 16 → 32 to fit.
  Existing `unverified` / `verified` / `failed` rows are
  unchanged.
- **`tin_verification.needs_verification`** updated to treat
  `unverified_external_source` like plain `unverified` (verify
  immediately) and `manually_resolved` like `verified` (only
  re-check on the 90-day stale cadence).
- **UI provenance pill** — new
  `components/review/ProvenancePill.tsx`. Reads
  `field_provenance[field]` and renders the right pill copy
  + tone per source. Wired into the customer detail page
  via a `ProvenancedField` wrapper around each FieldRow.
  Forward-compat: an unknown source key (server adds a new
  connector before the FE bundle ships) renders generically
  rather than crashing.
- **VerificationCard** updated to a five-state map with
  helpful copy per state — drops the legacy "live LHDN
  verification lands in a follow-up" placeholder (Slice 70
  shipped that).

Tests: 12 new (5 connectors model + 7 enrichment provenance
+ extended-state). 780 backend, was 768.

Durable design decisions:

- **`apps.connectors` separate from `apps.integrations`.**
  The two contexts answer different questions: connectors
  bring data IN to populate masters, integrations push data
  OUT (webhooks). Same word, opposite directions. Naming
  them differently saves the next reader hours of confusion.
- **Provenance JSON, not a sibling table.** Every read of a
  CustomerMaster row would otherwise need a JOIN. The field
  set is small, the write pattern is field-by-field, and
  audit replay can reconstruct full history from the audit
  chain anyway.
- **Backfill is `extracted` for everything populated.**
  We don't have finer-grained history (no per-field edit
  audit on the master pre-Slice-73), so calling it
  `extracted` matches reality for the create path and is
  honest about uncertainty for any subsequent edits — the
  next manual edit will overlay its own `manual` entry.
- **Soft-delete on `IntegrationConfig`, not hard-delete.**
  Customer history (which connectors did they use? when
  did they disconnect?) is durable; the unique constraint
  permits re-connect without merging the old + new
  configurations.
- **No SyncProposal / MasterFieldConflict / MasterFieldLock
  in this slice.** Those land in Slice 74 with the
  classify_merge matrix. Shipping them now without their
  consumer code would give us models that nobody calls.
- **The pill is on the master pages, not the invoice
  review screen.** Per-field provenance is meaningful for
  recurring entities (the buyer who shows up across 50
  invoices); on a single invoice, the source is always
  "the document the user just uploaded".

---

### Slice 74 — SyncProposal + MasterFieldConflict + MasterFieldLock + classify_merge matrix

The merge-classification backbone for the connectors initiative.
This slice ships only models + the pure classifier; the
orchestration that USES them (`propose_sync`, `apply_sync_proposal`,
`revert_sync_proposal`, `resolve_field_conflict`) lands in
Slice 75.

Backend:

- **`SyncProposal`** model — durable record of a sync run
  (proposed → applied → reverted/expired/cancelled). Holds the
  classified diff, expires after 14 days for the revert window,
  records actor / applier / reverter as soft FKs. ON DELETE
  PROTECT against IntegrationConfig deletion (customers
  soft-delete the config; historical proposals stay readable).
- **`MasterFieldLock`** — per-field pin. Unique by
  (org, master_type, master_id, field_name); same UUID can
  appear under both CustomerMaster and ItemMaster type
  discriminators independently.
- **`MasterFieldConflict`** — field-level conflicts created
  during propose_sync when the classifier returns `conflict`.
  Cascades from SyncProposal so a hard-delete of a proposal
  cleans up its open conflicts. Resolution enum:
  `keep_existing` / `take_incoming` / `keep_both_as_aliases` /
  `enter_custom_value`.
- **Polymorphic master reference via discriminator**
  (`master_type` + `master_id`) instead of Django's
  GenericForeignKey. Cleaner RLS, no content_type table
  dependency, only two master types so the discriminator
  stays small.

The merge classifier:

- **`apps.connectors.merge_classifier.classify_merge(inputs)`** —
  pure function, no DB reads, no time, no env. Takes a
  `ClassifyInputs` dataclass (existing value + provenance,
  incoming value + source, lock + authority-verified flags) and
  returns one of six `Verdict` values:

  | existing state                         | incoming               | result               |
  | -------------------------------------- | ---------------------- | -------------------- |
  | locked                                 | any                    | `skipped_locked`     |
  | authority-verified (e.g. LHDN TIN)     | any                    | `skipped_verified`   |
  | empty                                  | empty                  | `noop`               |
  | empty                                  | non-empty              | `auto_populate`      |
  | identical (post-trim)                  | any                    | `noop`               |
  | `synced_X` provenance                  | `synced_X` (same src)  | `auto_overwrite`     |
  | `synced_X` provenance                  | `synced_Y` (diff src)  | `conflict`           |
  | `extracted` provenance                 | any external           | `conflict`           |
  | `manual` / `manually_resolved`         | any external           | `conflict`           |
  | provenance dict missing the field      | non-empty different    | `conflict` (safe)    |

  Locks beat everything; authority-verified beats provenance.
  Identical values are noop regardless of source. Same-source
  synced overwrite is auto (the customer's source-of-truth
  changed); cross-source is conflict (human disposes).

Tests: 28 new (20 classifier matrix + 8 model invariants). 808
backend, was 780.

Durable design decisions:

- **`classify_merge` is pure.** No DB reads, no time, no env.
  Caller pre-fetches lock state + verification state once per
  master record + caches across the field loop. Makes audit
  replay trivial — same inputs always return the same verdict.
- **Frozen `ClassifyInputs` dataclass instead of positional
  args.** ``existing_value`` and ``incoming_value`` are both
  ``str``; positional swaps are the silent-bug pattern this
  initiative explicitly rejects. The dataclass forces named
  args at every call site.
- **Whitespace-trimmed equality.** "ACME" vs " ACME " is the
  same value to the customer; routing the latter to a
  conflict would be UX noise.
- **Missing-provenance defaults to conflict, not silent
  overwrite.** Pre-Slice-73 rows that the backfill missed (or
  future fields the migration didn't cover) take the safe
  path. Better to ask the user once than to silently corrupt
  a master.
- **Polymorphic via discriminator, not GenericFK.**
  GenericForeignKey makes RLS policies + cross-app migrations
  awkward; we have only two master types so the
  `(master_type, master_id)` pair is simpler.
- **Locks are CASCADE-independent of conflicts.** Hard-deleting
  a SyncProposal cleans up its conflicts (CASCADE) but never
  its locks — locks are durable user intent that outlives any
  individual proposal.
- **Authority-verified is the minimum viable abstraction.**
  Today TIN-via-LHDN is the only authority; tomorrow other
  fields might gain their own (SSL-verified email, BRN-verified
  registration). The classifier doesn't know about TINs
  specifically — callers tell it "is this field
  authority-verified" and it acts.

---

### Slice 75 — Sync orchestration services (propose / apply / revert / resolve / lock)

The orchestration layer sitting on top of Slice 74's classifier
+ models. After this slice, the entire two-phase sync flow works
end-to-end at the service level — Slice 77 wires the first
concrete connector (CSV) + the UI on top.

Backend (`apps.connectors.sync_services`):

- **`propose_sync(*, integration_config_id, customer_records,
  item_records, actor_user_id)`** — match-or-add per record;
  classify-merge per (record × field). Materialises a
  `SyncProposal` with the full diff JSON + persists
  `MasterFieldConflict` rows for every conflict so the queue UI
  has durable state to query. Updates `IntegrationConfig.last_*`
  cursors. Emits `integration.sync_proposed` with per-master
  bucket counts.
- **`apply_sync_proposal(*, proposal_id, actor_user_id)`** —
  writes every `would_add` (creates new master rows with
  `tin_verification_state=unverified_external_source`) +
  `would_update` (overlays new value + new provenance entry).
  Captures the pre-apply value of every changed field in
  `applied_changes` so revert can walk it back. Refuses
  double-apply. Emits `integration.sync_applied` +
  triggers re-match (Slice 76 stub).
- **`revert_sync_proposal(*, proposal_id, actor_user_id, reason)`**
  — within the 14-day window, deletes rows we created and
  restores prior values + provenance for rows we updated.
  Refuses past `expires_at` (and flips status to `EXPIRED`).
  Emits `integration.sync_reverted`.
- **`resolve_field_conflict(*, conflict_id, resolution,
  actor_user_id, custom_value=None)`** — applies the user's
  choice from the conflict-queue UI. Four resolutions:
  `keep_existing` (provenance flips to `manually_resolved`),
  `take_incoming` (master adopts incoming, provenance carries
  source tag + `applied_via_conflict_id`),
  `keep_both_as_aliases` (only on `legal_name` /
  `canonical_name`; appends to aliases),
  `enter_custom_value` (master adopts user-typed value;
  provenance `manually_resolved`). TIN resolutions flip
  `tin_verification_state` to `manually_resolved` per
  Slice 73's enum. Emits `master_record.conflict_resolved`.
- **`lock_field` / `unlock_field`** — idempotent lock writes,
  audit-emitting. Re-locking returns the existing row without
  duplicate audit churn; unlocking a non-existent lock no-ops.

Connector record shape — what fetchers (Slice 77+) emit:

```python
ConnectorRecord(
    source_record_id="DEBT-00482",
    fields={
        "legal_name": "Acme Sdn Bhd",
        "tin": "C9999999999",
        "address": "Level 5, KL Sentral",
        ...
    },
)
```

Tests: 23 new (6 propose + 4 apply + 3 revert + 6 resolve + 4
lock/unlock). 831 backend, was 808.

Durable design decisions:

- **Conflict rows are durable, not just diff-JSON.** The diff
  blob carries the same data, but the conflict-queue UI needs
  to query open vs resolved conflicts efficiently — that's a
  WHERE-clause job, not a JSON-walk job. So we materialise.
- **`applied_changes` records the prior value, not the prior
  state of the master row.** Revert needs to know what to
  restore at field-level granularity. Storing the whole row
  would bloat the JSON for syncs that touch one field per
  record; storing per-field is exactly what we walk back.
- **`unverified_external_source` for sync-created TINs.**
  Slice 73 introduced this state for exactly this case — the
  customer trusts where it came from, but LHDN hasn't
  confirmed yet. The Slice 70 verification task picks it up
  on the next pass and flips it to `verified` or `failed`.
- **No cross-context model imports.** `apps.connectors`
  imports `apps.enrichment.models.{CustomerMaster,ItemMaster}`
  — that's intentional + matches the cross-context-coupling
  rule (services may import sibling-context models when
  necessary; the inverse — enrichment importing connectors
  models — is forbidden and isn't needed today).
- **`_trigger_rematch_after_apply` is a stub.** Slice 76
  wires the actual `rematch_pending_invoices` pass that lifts
  `ready_for_review` invoices to `ready_for_submission` when
  a sync filled in the buyer the LLM missed. Today the apply
  / revert path logs the trigger fired so Slice 76 has a
  visible seam.
- **Idempotent lock writes.** Re-locking is common when the
  UI's "lock this field" button is clicked twice (network
  retry, double-tap). Returning the existing row is
  cheaper than recreating + re-auditing.
- **`SELECT FOR UPDATE` on proposal load for write paths.**
  Apply + revert hold a row lock so two operators clicking
  "Apply" simultaneously can't double-apply.

---

### Slice 76 — Re-match pass for ready_for_review invoices

The pay-off step of the connectors initiative: the moment where
the customer's review queue actually shrinks. After every
`apply_sync_proposal` (and every `revert_sync_proposal`), this
pass walks every Invoice in `ready_for_review` for the org and
re-runs the customer-master match. Newly-matched invoices get
the master's auto-filled fields applied + the audit chain
records the lift individually.

Backend (`apps.enrichment.rematch`):

- **`rematch_pending_invoices(*, organization_id, triggered_by)`** —
  walks `Invoice.objects.filter(status=READY_FOR_REVIEW)`,
  re-uses `_find_customer_master` + `_autofill_buyer` from the
  existing enrichment service. For invoices where the auto-fill
  actually filled blanks, emits one
  `invoice.master_match_lifted_by_sync` audit event per
  invoice with the connector trigger + filled fields +
  matched master id in the payload.
- **Idempotent.** Calling twice with no DB changes between runs
  yields zero new lifts on the second pass — already-filled
  invoices have nothing left to lift.
- **Read-only on extracted data.** Auto-fill never overwrites
  invoice fields the LLM already populated. Only fills blanks.
  Re-match never UN-fills (extracted data is durable; revert of
  a sync that filled an invoice doesn't roll the invoice back).

Wired into Slice 75:

- `_trigger_rematch_after_apply` (formerly a stub) now calls
  `rematch_pending_invoices`. If the run lifted ≥ 1 invoice,
  emits a follow-up `connectors.rematch_completed` audit event
  with the totals so a chain reader can correlate "this
  proposal applied + lifted N invoices" without walking every
  per-invoice event.
- Apply path passes `triggered_by="connectors.sync_apply"`;
  revert passes `connectors.sync_revert`. Same function, same
  audit event tag — the `triggered_by` payload distinguishes.

Tests: 7 new (no-pending counts, no-buyer skip, lift-when-master-
matches, audit-on-lift with right payload, idempotent on second
pass, skips non-ready_for_review invoices, cross-tenant
isolation). 838 backend, was 831.

Durable design decisions:

- **Re-match runs on apply AND revert.** Revert can flip what
  an invoice matches (the master row that lifted it may be
  gone). The re-match function is idempotent + safe to call.
- **Audit event per invoice + one summary event.** A bulk
  proposal touching 50 invoices emits 50
  `invoice.master_match_lifted_by_sync` events plus one
  `connectors.rematch_completed` summary. The per-invoice
  events let the customer see "this specific invoice changed
  because of that sync"; the summary lets operators see "the
  apply lifted 27/50 invoices" at a glance.
- **`triggered_by` is a string, not an enum.** Keeps the
  function open for non-sync triggers later (e.g. customer
  master detail page might want a "re-evaluate this customer's
  pending invoices" button).
- **No item-master rematch in this slice.** Customer master is
  the dominant lift case. Item-master rematch (would lift
  line-item codes when a sync filled in MSIC defaults) is a
  follow-up.

---

### Slice 77a — BaseConnector + CSVConnector + REST endpoints (backend)

The first concrete connector + the API surface that drives the
upcoming preview / conflict-queue UI (Slice 77b).

Backend:

- **`apps.connectors.adapters.base.BaseConnector`** abstract
  interface — `authenticate()`, `fetch_customers()`,
  `fetch_items()`, `health_check()`. Concrete adapters yield
  `ConnectorRecord` instances; orchestration calls into the
  adapter, never the other way around.
- **`apps.connectors.adapters.csv_adapter.CSVConnector`** — first
  concrete adapter. Zero auth (the upload is the boundary).
  Operator-supplied column mapping translates source CSV column
  headers to ZeroKey master field names. Encoding fallback chain
  (UTF-8-with-BOM, UTF-8, CP1252, latin-1) so an Excel export
  doesn't bounce at the door. Skips blank rows. Optional
  `source_record_id` column → carried into provenance.
- **`get_adapter_class(connector_type)`** — dispatch table.
  Today: CSV. Slice 78+: AutoCount, Xero, etc. Unknown types
  raise so a misconfigured `IntegrationConfig` fails explicitly
  rather than silently producing empty proposals.
- **REST endpoints** under `/api/v1/connectors/`:
  - `GET / POST /configs/` — list + create (idempotent on
    re-create of an active config).
  - `DELETE /configs/<id>/` — soft-delete via `deleted_at`.
  - `POST /configs/<id>/sync-csv/` — multipart upload (file +
    column_mapping JSON + target). Owner/admin only. Calls
    `propose_sync` and returns the SyncProposal payload.
  - `GET /proposals/<id>/` — read.
  - `POST /proposals/<id>/apply/` and `/revert/` — owner/admin.
  - `GET /conflicts/?state=open|resolved|all` — list filtered.
  - `POST /conflicts/<id>/resolve/` — owner/admin. Body:
    `{resolution, custom_value?}`.
  - `POST /locks/` and `/locks/unlock/` — owner/admin.
- **DRF serializers** for `IntegrationConfig`, `SyncProposal`,
  `MasterFieldConflict`, `MasterFieldLock`. Read-only at the
  serializer level — write paths go through services so the
  audit + provenance writes happen.

Tests: 31 new (12 CSV adapter + 19 endpoint coverage). 869
backend, was 838.

Durable design decisions:

- **CSV is the universal escape hatch + the test fixture for
  the propose / apply / conflict flows.** Ships first
  intentionally — no auth, no external service to mock,
  exercises every classifier verdict via test fixtures.
- **Operator-supplied column mapping, not auto-detection.**
  Auto-detection is a research project; operator-mapped is a
  five-minute wizard. The Slice 77b UI ships the wizard.
- **Encoding fallback chain.** Excel-exported CSVs in Malaysia
  often arrive with BOM or CP1252; rejecting them on first
  byte would have been a silent UX cliff.
- **Endpoints owner/admin gated for writes; any active member
  can read.** Matches the rest of the codebase. The conflict
  queue + proposal preview are read-only for viewers — they
  can SEE what was synced + what conflicts remain even if they
  can't act.
- **`POST /configs/` returns the existing row when one exists.**
  Avoids leaking the UniqueConstraint into the API surface
  (would 500 on the second click). Idempotent — caller gets
  the same id either way.
- **Soft-delete for IntegrationConfig.** History (which
  connectors did this customer use, when did they disconnect)
  outlives any single config row. Slice 73 already shipped
  the conditional UniqueConstraint that lets a customer
  reconnect after disconnecting.
- **Adapter dispatch via class, not instance.** The view
  instantiates the adapter once per request with
  request-specific args (uploaded bytes + mapping); a
  registered instance would have to be re-configured per
  request, which gets messy.

What's deferred to Slice 77b:

- Settings → Connectors UI for create / list / disconnect.
- CSV upload wizard with column-mapping picker.
- Sync preview screen (Will-add / Will-update / Conflicts
  tabs).
- Conflict queue lane in the Inbox.
- Lock icons + provenance pills already shipped on the
  customer detail page (Slice 73); items page gets them in 77b.

---

### Slice 77b — Connectors UI: catalog, CSV upload wizard, sync preview, conflict queue (frontend)

Customer-visible end of the connectors initiative. After this
slice, an owner / admin can drive the entire two-phase sync
through the browser without touching curl.

Frontend:

- **`/dashboard/connectors`** — landing page. Lists active
  `IntegrationConfig` rows with last-sync status pill +
  "Upload CSV" / "Disconnect" actions per row. Catalog grid
  shows all 7 connector types; CSV is the only "Connect"-
  enabled card today, the rest render as
  "Coming soon" badges so customers see the roadmap without
  being able to mis-configure.
- **`/dashboard/connectors/<configId>/upload`** — three-step
  CSV upload wizard:
  1. Pick file (browser-side `text()` parses headers + first 3
     data rows for preview).
  2. Pick target (customers / items) — re-runs the auto-
     suggest mapping when toggled.
  3. Map columns. Heuristic auto-suggest based on header
     substring matching (e.g. "company name" → `legal_name`,
     "tax id" → `tin`); operator reviews + adjusts via
     per-row dropdowns. Each ZeroKey field can only be
     claimed once — selecting one disables the option in
     other rows.
  4. Submit → multipart POST to `/sync-csv/` → redirect to
     proposal preview.
- **`/dashboard/connectors/proposals/<id>`** — preview
  screen. Four tabs:
  - **Will add**: net-new master rows the sync proposes to
    create.
  - **Will update**: existing rows + per-field
    current/proposed diff with strike-through current value.
  - **Conflicts**: count + link into the conflict queue +
    inline list of (field, existing, incoming) tuples.
  - **Skipped**: locked + authority-verified fields that
    weren't auto-applied, with explanatory copy.
  Apply button visible while `status=proposed` (owner /
  admin only via backend gate). Undo button on
  `status=applied` proposals within 14 days; prompts for a
  reason that lands on the audit chain.
- **`/dashboard/connectors/conflicts`** — conflict queue
  page. Open / Resolved / All tab strip with counts. Each
  conflict card shows the existing + incoming values
  side-by-side with provenance pills (re-using the Slice 73
  `ProvenancePill` component) + four action buttons:
  Keep existing / Take incoming / Keep both as aliases
  (only on `legal_name` / `canonical_name`) / Enter custom
  value. Custom value flow opens a `window.prompt` for the
  type-it-in step.
- **Sidebar nav** — "Connectors" item added to the
  Workflow group between Customers and the Compliance
  divider.
- **API client** — full coverage in `lib/api.ts`:
  `listConnectorConfigs` / `createConnectorConfig` /
  `deleteConnectorConfig` / `uploadCsvSync` / `getProposal`
  / `applyProposal` / `revertProposal` / `listConflicts` /
  `resolveConflict` / `lockMasterField` /
  `unlockMasterField`. Plus all the relevant types.

Durable design decisions:

- **Three-step wizard on a single page, not a multi-page
  flow.** The user can go back and forth (re-pick file,
  re-toggle target) without losing state. A multi-page
  wizard would need server-side state for resume; the
  single-page form keeps everything in component state.
- **Heuristic mapping suggestions, not auto-mapping.** The
  suggestion is a starting point; the operator confirms. Auto-
  applying without confirmation would silently corrupt
  master data on a header-naming convention we didn't
  anticipate.
- **Browser-side header preview.** Lets the wizard show the
  mapping UI without a server round-trip; the same parsed
  bytes get re-parsed server-side via Python's `csv` module
  for the actual sync. Two parses, deliberate — the browser
  preview is for UX only.
- **One ZeroKey field per source column.** Selecting a field
  in one row disables it in others. Prevents the
  silent-overwrite case where two source columns claim the
  same target field.
- **Conflict cards use the same `ProvenancePill` from Slice
  73.** Customers see the same source labelling on the
  customer detail page + the conflict queue, so the visual
  vocabulary is consistent.
- **Apply doesn't block on conflicts.** Auto-resolvable
  changes still land; conflicts wait their turn in the
  queue. The preview's "Conflicts" tab makes this explicit
  with copy: "auto-resolvable changes still land. Resolve
  these in the conflict queue when you&apos;re ready."
- **Custom-value flow uses `window.prompt`.** Cheap, native,
  one-line. A bespoke modal would be 50 lines of UI for a
  lower-frequency action.

What's still deferred:

- **Items master page provenance pills + lock icons.** Same
  pattern as the Slice 73 customer-detail wiring, just
  applied to the Items page. Small follow-up.
- **Bulk conflict resolution** ("take all incoming for source
  X"). v1 is one-at-a-time per the spec; bulk lands when we
  see real conflict patterns.
- **Inbox conflict-queue lane integration.** The dedicated
  page is the v1 surface; the spec calls out the Inbox lane
  but the cross-page navigation works without it for now.
- **Concrete connectors beyond CSV** (AutoCount, Xero, etc.)
  — Slice 78+, one per slice.

---

### Slice 78 — Public API ingestion endpoint

The integrator entry point — vendor systems / custom scripts can
push invoices via APIKey auth using the same pipeline the web
upload + email forward + sync paths share.

Backend:

- **`POST /api/v1/ingestion/jobs/api-upload/`** — APIKey-only
  (`authentication_classes=[APIKeyAuthentication]` pinned;
  session auth not accepted on this endpoint). JSON body:
  ```json
  {
    "filename": "INV-2026-001.pdf",
    "mime_type": "application/pdf",
    "body_b64": "<base64>",
    "source_identifier": "vendor-row-12345"
  }
  ```
  Returns the IngestionJob payload — integrator polls
  `GET /jobs/<id>/` with the same key.
- **`apps.ingestion.services.upload_api_file`** — sibling of
  `upload_web_file`. Sets `source_channel=API`, audit
  `actor_type=EXTERNAL` (the actor is an external system, not a
  user) with `actor_id=<APIKey.id>` so chain replay can join
  back to which key was used. Optional `source_identifier`
  carries the integrator's own document reference.
- 25 MB ceiling applies to the **decoded** bytes, not the
  base64 payload — the customer-visible contract matches the
  web upload limit.

Tests: 12 new (auth gate × 3, happy path × 2, validation × 6,
tenant isolation × 1). 881 total, was 869.

Drive-by: fixed a non-deterministic `MasterFieldConflict.objects.first()`
in the connectors endpoint test that surfaced when test
ordering shifted.

Durable design decisions:

- **JSON+base64 only, not multipart.** Integrators
  overwhelmingly prefer one content-type to negotiate; JSON +
  base64 is the cheapest path to ship in any HTTP client +
  trivial to SDK. The web upload stays multipart because it's
  browser-driven (no encoding overhead in `<input type=file>`).
- **`authentication_classes` pinned to APIKey only.** The
  default DRF auth chain accepts session auth too — a web
  visitor with an open session could otherwise post to this
  endpoint by accident (or design). Pinning it shapes the
  contract: this URL is for integrators.
- **Audit `EXTERNAL` actor type, not a synthetic API_KEY
  one.** The audit enum has `USER / SERVICE / STAFF /
  EXTERNAL`; `EXTERNAL` is the right semantic ("this came from
  outside the platform's logged-in surfaces"). The `actor_id`
  field carries the APIKey row id which is the disambiguator.
- **`source_identifier` is opaque to us.** Whatever string the
  integrator sends ends up in the IngestionJob row + audit
  payload truncated to 255 chars. Doesn't have to be unique;
  doesn't have to be meaningful; we just round-trip it so the
  integrator can correlate their system to ours.
- **Limit applies to decoded bytes.** A customer who base64-
  encodes a 25 MB file gets a 33% larger payload (~33 MB on
  the wire). Limiting on encoded would silently lower the
  effective limit; limiting on decoded keeps the contract
  identical to the web upload.

---

### Slice 79 — GitHub Actions CI workflow + first-pass lint/format baseline

The productivity foundation: every push + every PR runs ruff +
pytest + frontend typecheck/lint/build. Catches regressions
before they ship.

`.github/workflows/ci.yml`:

- **Backend job** — uv install with cache, `ruff check`,
  `ruff format --check`, pytest with sqlite settings (the
  same in-memory backend the test settings already use; 5
  RLS-only tests skip cleanly without Postgres).
- **Frontend job** — npm ci with cache,
  `prettier --check`, `next lint`, `tsc --noEmit`,
  `next build` so a release-mode regression doesn't sneak
  through.
- **Concurrency** — cancels in-progress runs on the same ref
  so a fast follow-up commit doesn't queue behind a slow
  earlier one.
- **15-minute timeouts** per job — abuse-prevention + fast
  feedback when CI hangs on a flaky test.

Drive-by: first-pass formatting baseline so CI can be strict
from day one without 100+ retroactive lint errors:

- **Backend** — ruff applied to 129 files (whitespace, import
  order, single-line trims). Zero functional changes; 881
  tests still pass.
- **Frontend** — prettier applied to 46 files. TypeScript
  + ESLint clean.
- **Ruff config tuned** — added per-rule ignores for
  intentional-by-context patterns: `S110` (try/except/pass for
  best-effort writes), `S314` (XML parse of own-source content),
  `RUF002/3` (ambiguous Unicode in docstrings — false-positive
  on legit non-Latin chars), `E402` (Django pattern with
  conditional imports), `B904`/`F841` (deferred to follow-up
  cleanup), etc. Each ignore documented in pyproject.toml so
  the next reader knows why.

Drive-by: fixed a `react-hooks/rules-of-hooks` violation in
the proposal preview page where `useMemo` ran after a
conditional return.

Durable design decisions:

- **CI gate on format-check, not auto-fix.** A PR with
  unformatted code fails CI; the developer runs
  `make format` locally + commits. Auto-fixing in CI would
  hide the friction + drift the convention.
- **No matrix testing.** One Python version (3.12), one
  Node version (20). Matrices are noise until we have a
  reason to support multiple — which we don't. Pin precisely.
- **Sqlite-in-memory for the backend job.** The 5 RLS-only
  tests skip; they're worth running, but the cost of a
  per-PR Postgres service in CI vs. running Postgres-only
  tests in a separate scheduled workflow is not worth it
  yet.
- **First-pass format baseline.** ~175 files reformatted in
  one commit + the CI gate from there forward. Doing it
  per-feature would have left CI red for weeks while the
  long-tail files trickled through.

---

### Slice 80 — Inbox token rotation

Closes the email-forward feature surface from Slice 64. When an
operator suspects the magic forwarding address has leaked (or
just runs quarterly hygiene), they can mint a fresh token in
one click; the old address stops resolving immediately.

Backend:

- **`apps.ingestion.email_forward.rotate_inbox_token(*, organization_id,
  actor_user_id, reason)`** — generates a new 16-char URL-safe
  token, replaces the previous one on the Organization row,
  audits the rotation. Returns the full new magic address
  ready for the FE to render.
- **`POST /api/v1/ingestion/inbox/rotate-token/`** — owner / admin
  only (the same role gate as the cert + integration write
  paths). Optional `{reason}` JSON body lands in the audit
  payload.
- **Audit event `ingestion.inbox_token.rotated`** records the
  actor + reason + a 4-char prefix of each token so a chain
  reader can correlate with provider-side logs without seeing
  the full secret. Full tokens never enter the audit chain.

Frontend:

- **Rotate button** added to the Inbox address card on
  Settings → Integrations (owner / admin only). Confirmation
  dialog spells out that the old address stops working
  immediately + recommends updating forwarding rules first.
  Reason prompt feeds into the audit payload.
- Spinner on the icon while the rotation is in flight; success
  silently swaps the rendered address.

Tests: 5 new (service replaces token + invalidates old, audit
records prefixes only, endpoint requires auth, owner can rotate,
viewer cannot). 886 backend total, was 881.

Durable design decisions:

- **Old token stops resolving immediately, no grace window.**
  The spec doc (Slice 64 era) suggested a future "forwarded
  too late, please use your current address" reply. Today's
  cut is simpler: 404 on lookup, the email provider's webhook
  fails-loud, the sender knows. A grace window adds
  state + complicates the threat model (what's the value of
  rotation if the leaked token still works for 24h?).
- **Audit logs the prefix, never the token.** Even with
  super-admin elevation a chain reader shouldn't see a
  resolvable address. Four chars is enough to disambiguate
  during incident review without being a credential.
- **Reason is optional but surfaced as a prompt.** Operators
  rotate for both routine + incident reasons; the prompt
  encourages capturing context without forcing it.
- **`EmailForwardError` reused for the not-found case.**
  Same exception family as the existing inbox code so the
  view-layer error mapping is consistent.

---

### Slice 81 — Customer-detail lock icons (closes Slice 73's UX loop)

Slice 74 shipped `MasterFieldLock` + the API to create/remove
them; Slice 77's classifier reads the lock state for every
classify_merge call. But there was no UI to actually create a
lock. Slice 81 wires the click-to-lock gesture so customers can
pin fields they care about against future syncs.

Backend:

- **`CustomerMasterSerializer.locked_fields`** — new
  SerializerMethodField that queries
  `MasterFieldLock.objects.filter(master_id=...)` once per
  serialised row. Returns the list of field names that have an
  active lock. Lazy-imports `apps.connectors.models` to avoid
  app-loading-order coupling.

Frontend:

- **Lock / Unlock icon** on each `ProvenancedField` on the
  customer detail page. Clicking toggles a `MasterFieldLock`
  via the existing Slice 77 endpoints (`POST /connectors/locks/`
  + `POST /connectors/locks/unlock/`). Tooltips explain the
  effect ("Lock — future syncs will route changes to this
  field through the conflict queue.").
- **Locked badge** rendered alongside the provenance pill so
  the lock state is visible even when the icon is small.
- **Optimistic update** — the page flips `customer.locked_fields`
  immediately on click; if the API call fails, it rolls back
  + surfaces the error in the SaveBar's error slot.
- **`Customer.locked_fields: string[]`** added to the api.ts
  type so the rest of the app can read it.

Tests: 2 new backend (default empty, multi-field listing). 888
total, was 886.

Durable design decisions:

- **Lookup in the serializer, not on the model.** A model
  property would do the same query but every call site would
  pay for it; the SerializerMethodField is explicit + only
  fires when the field is actually serialised.
- **Optimistic flip + rollback on failure.** Locks are
  high-frequency clicks (operator pins half a dozen fields in
  a row); waiting for the round-trip per click would feel
  laggy. The optimistic state is correct ~99% of the time +
  the rollback is honest when the API rejects.
- **Lock state lives on the customer payload, not as a sibling
  fetch.** Single GET on page load + the lock-toggle handler
  updates the local state. Sibling fetches add latency + a
  caching seam that's not worth the complexity.
- **Icon + badge (not just icon).** Small UI affordances are
  easy to miss on a busy page; the explicit "Locked" badge
  makes the state unmistakable next to the provenance pill.

---

### Slice 82 — WhatsApp ingestion (multi-channel ingestion completes)

Closes the multi-channel ingestion story: web upload (Slice 5),
email forward (Slice 64), public API (Slice 78), and now
WhatsApp Cloud API. Customers can drop an invoice PDF into a
WhatsApp chat with their tenant-bound business number and have
it land in the same pipeline as a web upload.

Backend:

- **`Organization.whatsapp_phone_number_id`** — per-tenant
  routing key. Meta's Cloud API stamps every inbound webhook
  with the destination `phone_number_id`; we map that to the
  tenant. Empty string means WhatsApp ingestion is not
  configured for the org. (Migration `identity.0015`.)
- **`apps/ingestion/whatsapp.py`** — provider-agnostic core,
  shaped exactly like `email_forward.py`:
  - `InboundWhatsAppMessage` / `InboundWhatsAppAttachment`
    dataclasses (sender, message_id, phone_number_id,
    timestamp, attachments).
  - `resolve_tenant_from_phone_number_id` — super-admin
    context; raises `PhoneNumberNotFoundError` on no match.
  - `process_inbound_whatsapp_message` — creates one
    `IngestionJob` per attachment with
    `source_channel=WHATSAPP`; mirrors email-forward audit
    shape and skip semantics (mime allowlist, 25 MB ceiling,
    10-attachment cap).
  - `parse_meta_webhook_payload` — Meta Cloud API adapter.
    Walks `entry[].changes[].value.messages[]`; for each
    document/image message it calls an injectable
    `media_fetcher(media_id)` callable to pull bytes. Failed
    fetches emit the message with empty attachments so the
    audit chain shows the no-media outcome instead of
    silently dropping.
  - `verify_meta_signature` — `X-Hub-Signature-256` HMAC
    check (fails closed on empty secret/header).
  - `_redact_phone` — keeps the country/area-code shape (4
    leading digits) for audit, masks the rest.
- **Webhook view** `whatsapp_webhook_view` (GET + POST):
  - GET handles Meta's subscription handshake. Returns
    `hub.challenge` iff `hub.verify_token` matches the
    platform's `whatsapp.verify_token` SystemSetting.
  - POST verifies `X-Hub-Signature-256` against the
    `whatsapp.app_secret` SystemSetting, parses the payload,
    fetches media via `_fetch_meta_media` (two-step Cloud
    API: GET `/v18.0/{id}` → URL → GET URL), and processes
    each message. Per-message errors come back in the batch
    response so a single unknown number doesn't drop the
    whole payload (Meta would otherwise retry the entire
    batch on 5xx).
  - Both halves return 503 when secrets are not configured —
    fail closed, don't silently swallow customer messages.
- **Route**: `POST/GET /api/v1/ingestion/inbox/whatsapp/`.

Tests: 24 new backend, all green. 912 total, was 888.

Durable design decisions:

- **Per-tenant `phone_number_id` over a separate
  WhatsAppInboundNumber table.** Simpler — symmetric to
  `inbox_token`, one row to update when super-admin onboards
  a customer. If we later need multi-number-per-org or
  number pooling we'll add the table; until then YAGNI.
- **Provider-agnostic core + thin Meta adapter.** Same shape
  as `email_forward.py`: `InboundWhatsAppMessage` is the unit
  of work; the parser is the only piece tied to Meta's JSON
  shape. Lets us add Twilio / Infobip / Karix as alternative
  WhatsApp providers without touching `process_inbound_*`.
- **Injectable `media_fetcher`.** The parser doesn't reach
  into the network — tests pass a stub returning canned
  bytes; the production view binds it to `_fetch_meta_media`.
  Keeps the parser hermetic and Meta-API-version changes
  contained to one function.
- **Failed media fetch → empty attachments, not dropped
  message.** A dropped message disappears from the audit
  chain; an empty-attachments message generates an
  `ingestion.whatsapp.empty` event so operators can
  investigate Meta-API outages.
- **Per-message errors → 200 with batch results.** Meta's
  retry semantics are: 200 = "stop retrying this batch", 5xx
  = "retry the whole batch". One unknown `phone_number_id`
  shouldn't trigger replay of N already-processed messages.
- **Platform secrets in `SystemSetting`, per-tenant routing
  on `Organization`.** Same pattern as email-forward: the
  webhook is one Meta App / one Cloud API endpoint hosting
  many customer numbers. Splitting "what's mine" from
  "what's shared" keeps the security model clean.
- **503 when not configured (not 200/silent drop).** Failing
  closed surfaces misconfiguration in monitoring instead of
  letting customer messages vanish. Meta will retry; once
  super-admin completes setup, the queued retries flow
  through.

Configuration left for super-admin (no UI yet — they
hand-edit `SystemSetting` from `/django-admin/`):

- `whatsapp.verify_token` — random string for Meta's
  subscription challenge.
- `whatsapp.app_secret` — Meta App Secret for HMAC.
- `whatsapp.access_token` — Cloud API bearer token for media
  fetch.
- Per-customer: set `Organization.whatsapp_phone_number_id`
  to the customer's Cloud API phone-number id.

---

### Slice 86 — i18n scaffold + Bahasa Malaysia

VISUAL_IDENTITY.md commits the platform to four first-class
locales (EN, BM, ZH, TA). Slice 86 ships the scaffold plus
translated strings for the highest-traffic surfaces: nav, dashboard
top, customers / items list pages, common actions. ZH + TA are
listed as supported but fall back to EN until their tables land
(no behaviour change vs today; the scaffold is in place when
translators arrive).

Architectural choice: a small client-side translation layer
instead of route-segment-based i18n. SME users don't need
locale-tagged URLs, and adopting `/[locale]/...` would have been
a high-blast-radius restructure of the entire dashboard tree.

Frontend:

- **`frontend/src/lib/i18n.ts`** — `useT()` hook + `translate()`
  function + `getLocale()` / `setLocale()`. Resolution order:
  localStorage → server `preferred_language` → `navigator.language`
  → `en-MY`. Variable substitution via `{name}` syntax. Dev-mode
  warning on missing keys.
- **`frontend/src/locales/en.ts`** + **`bm.ts`** — translation
  tables, dot-namespaced keys (`nav.*`, `dashboard.*`,
  `customers.*`, `auth.*`, `action.*`).
- **AppShell sidebar** — `NAV_GROUPS` migrated from `label` to
  `labelKey`; renders via `useT()`.
- **Language switcher** in the user-avatar dropdown — flips
  immediately + best-effort persists via the new preferences
  endpoint.
- **Customers list page** — translated header strings.

Backend:

- **`PATCH /api/v1/identity/me/preferences/`** —
  `update_preferences` view. Allowlist: `preferred_language`
  ∈ {en-MY, bm-MY, zh-MY, ta-MY}. No-op when the value matches
  what's already on file.

Tests: 5 new backend (happy path, unsupported locale rejection,
no-op same-value, unauthenticated 401/403, all four supported
locales accepted). 953 total, was 948.

Durable design decisions:

- **Client-side strings, not route-segment locales.** SME
  customers don't share locale-tagged URLs and the whole
  dashboard tree would need to move under `/[locale]/...` —
  cost outweighs benefit at our scale.
- **Server source of truth + localStorage cache.** Local flip
  is instant (no round-trip on every nav); the server save is
  best-effort + fires-and-forgets so the persistence call
  doesn't block the UI. Re-sign-in re-reads server state.
- **EN fallback for missing keys.** A dev-mode warning makes
  untranslated strings visible without breaking production.
  Better than throwing — partial translation is better than no
  translation.
- **ZH + TA listed but unstyled.** The scaffold supports them;
  the tables are placeholder-empty (fall back to EN). This
  marks them as known TODO without committing to ship dates we
  can't keep.
- **`labelKey`, not `label`.** Migrating constants to translation
  keys at definition time means the translation lookup happens
  exactly once per render, in the component that decides what
  to display. No double-translation, no missed strings in
  dynamic mappings.

---

### Slice 85 — AutoCount connector

First concrete connector. Turns the abstract `IntegrationConfig`
+ propose/apply/conflict scaffolding (Slices 73–77) into
something a Malaysian SME customer can actually plug in by
exporting their AutoCount Debtor List or Stock Items to CSV
and uploading it.

The adapter is intentionally CSV-driven, not ODBC: the export-
and-upload path needs no driver install, no LAN-side agent, no
per-edition version negotiation. AutoCount's "Export to CSV"
is a one-click gesture from the standard list views, and its
column headers are stable across editions for the two reference
exports we care about. ODBC (always-on pull) is still on the
roadmap as the SQL_ACCOUNTING / future "AutoCount Direct"
connector.

Backend:

- **`apps/connectors/adapters/autocount_adapter.py`** —
  `AutoCountConnector` wraps `CSVConnector` with a baked-in
  column mapping (`AUTOCOUNT_CUSTOMER_MAPPING` for Debtor List,
  `AUTOCOUNT_ITEM_MAPPING` for Stock Items). `Tax Reg. No` and
  `GST Tax Reg. No` (older editions) both map to TIN.
- **Adapter registry** — `get_adapter_class` now returns
  `AutoCountConnector` for `connector_type=autocount`.
- **`POST /api/v1/connectors/configs/<id>/sync-autocount/`** —
  multipart upload endpoint. No `column_mapping` field
  required. Owner / admin gated, just like the CSV path.

Frontend:

- **`/dashboard/connectors/<id>/autocount`** — single-step
  upload page. Pick file, pick target (Debtor List vs Stock
  Items), submit. Redirects to the SyncProposal preview on
  201.
- **Connectors catalog** — AutoCount is now `shipped: true`.
  `onConnect("autocount")` jumps into the AutoCount upload
  page after creating the config; the per-row Upload affordance
  on the configured-connectors table gets an AutoCount variant
  alongside CSV.
- **`api.uploadAutoCountSync`** — typed client method.

Tests: 13 new (column mapping, alias header, item export,
unknown-column drop, target validation, empty-CSV rejection,
blank-row skip, mapping disjointness, no-op authenticate,
endpoint upload happy path, wrong-type rejection, missing-file
rejection, dispatch table). 948 total, was 935.

Durable design decisions:

- **CSV adapter wraps the generic CSV adapter, doesn't fork
  it.** All the encoding-fallback / whitespace-normalisation /
  empty-row-skip logic stays in one place. AutoCount's
  contribution is a column mapping; the iteration semantics
  shouldn't drift between connectors.
- **Two header variants for TIN.** Older AutoCount editions
  emit "GST Tax Reg. No"; current emit "Tax Reg. No". Both map
  to the same target field. Without this, customers on legacy
  editions would silently lose TIN data on every sync.
- **Customised AutoCount installations fall back to generic
  CSV.** The mapping assumes vanilla columns. We document the
  fallback in the connector's description rather than silently
  producing partial proposals — if a user renames "Company
  Name" to "Customer Name", the proposal would be empty under
  AutoCount, which would be confusing.
- **No ODBC in v1.** ODBC requires a sidecar agent + Windows-
  side driver install + version matrix. CSV upload covers the
  90% case for Malaysian SMEs (their bookkeeper does the
  monthly export anyway) at zero install cost.

---

### Slice 84 — Signed-XML at rest

The `signed_xml_s3_key` column has been a free column since
Slice 67 with nothing populating it. Slice 84 closes that gap:
on every accepted LHDN submission, we envelope-encrypt the
signed bytes (XML for the v1.1 path, UBL-JSON for the v1.0
path), persist them to S3 under a per-tenant prefix, and stash
the key on the Invoice. A decrypt-on-read download endpoint
serves them back to authorised users for audit + dispute use
cases.

Envelope shape (small JSON wrapper around Fernet ciphertext):

  - `v` schema version (currently `1`)
  - `format` — `"xml"` or `"json"`
  - `digest_sha256` — SHA-256 of the *plaintext* signed bytes
    (the same digest LHDN saw on `documentHash`)
  - `encrypted_b64` — Fernet ciphertext of the signed bytes,
    base64-encoded
  - `written_at` — ISO 8601

Backend:

- **`apps/submission/signed_blob.py`** — `persist_signed_bytes`
  builds the envelope + writes to `S3_BUCKET_SIGNED`;
  `fetch_signed_bytes` round-trips the envelope back, verifies
  the digest, and returns plaintext + format. A digest
  mismatch is audited and raised — the chain reader can detect
  tamper without trusting the envelope.
- **`get_object_bytes` helper** added to
  `apps.integrations.storage` for in-memory reads of small
  artefacts.
- **`signed_document_download_view`** at
  `GET /api/v1/invoices/<id>/signed-document/` — returns the
  decrypted bytes with the appropriate Content-Type
  (`application/xml` or `application/json`) and a `Content-
  Disposition` attachment header. The read is audited
  (`submission.signed_blob.read`) so a future reviewer can see
  who pulled the bytes.
- **Submission orchestrator** (`lhdn_submission.py`) calls
  `persist_signed_bytes` after LHDN accepts the submission —
  for both the JSON and XML paths. Failure is best-effort: a
  storage outage doesn't unwind the submission (LHDN already
  has the document); the failure is audited so an operator can
  backfill.

Tests: 9 new (envelope shape, audit chain, format validation,
storage-failure path, round-trips, no-blob-on-file, digest
mismatch). 935 total, was 926.

Durable design decisions:

- **JSON envelope, not raw ciphertext on S3.** The plaintext
  digest + format are operational metadata an audit reader
  needs without decrypting. Putting them next to the
  ciphertext keeps the round-trip atomic and the bucket
  policy uniform (`application/json` regardless of format).
- **Re-use `apps.administration.crypto`.** Same DEK derivation
  the platform already uses for SystemSetting.values +
  Engine.credentials. The KMS swap point stays a single
  function (`crypto._dek()`); this module never sees the key.
- **Persist post-acceptance, not post-sign.** Persisting
  before LHDN accepts would store rejected drafts that don't
  match what's on file at LHDN. Persisting after acceptance
  guarantees the stored bytes are exactly what the regulator
  has.
- **Best-effort persist.** Storage failures must not unwind
  an accepted submission — LHDN has the document, the
  customer's tax obligation is met. An audited
  `persist_failed` event lets an operator backfill from the
  LHDN copy.
- **Digest mismatch fails closed.** Returning silently-corrupt
  bytes is the worst outcome for an auditor. Raising +
  auditing the mismatch makes integrity violations visible at
  the chain layer.
- **Decrypt-on-read, not pre-signed URL.** The bytes are
  sensitive — a pre-signed URL leaks plaintext to anyone with
  the link until the TTL expires. Streaming through the
  application server keeps the audit + auth gates in front of
  the bytes.

---

### Slice 83 — Items page (closes the master-data lock loop)

Slice 81 shipped lock icons on the Customer detail page; the
Item detail page had been on the punch list ever since. Slice
83 ships the symmetric Items surface: list page, detail-and-edit
page, provenance pills, lock icons. Same `MasterFieldLock`
plumbing — just `master_type=item` instead of `customer`.

Backend:

- **`ItemMasterSerializer`** in `apps/enrichment/serializers.py`
  — mirrors `CustomerMasterSerializer.locked_fields`, queries
  `MasterFieldLock` filtered to `MasterType.ITEM`.
- **Service helpers** `list_item_masters` / `get_item_master` /
  `update_item_master` in `apps/enrichment/services.py`. The
  update path mirrors `update_customer_master`: editable-field
  allowlist (`EDITABLE_ITEM_FIELDS`), rename files the previous
  canonical as an alias, manual provenance written for every
  changed field, single `item_master.updated` audit event with
  changed_field NAMES only.
- **Views** `list_items` / `item_detail` (GET + PATCH) added to
  `apps/enrichment/views.py`. Cross-tenant access returns 404 to
  preserve tenant opacity.
- **URLs** mounted at `/api/v1/items/` (separate URLconf module
  `apps.enrichment.items_urls` so the existing `/customers/`
  mount doesn't have to be restructured).

Frontend:

- **`/dashboard/items/`** list page — most-used items first,
  showing canonical name + alias hint + the four default codes
  + usage_count + last_used_at. Empty state speaks in
  opportunity ("Drop your first invoice").
- **`/dashboard/items/[id]/`** detail page — same draft +
  SaveBar + lock-toggle pattern as the customer detail page.
  Identity section (canonical name) + Defaults section (MSIC,
  classification, tax type, UOM, unit price). Each field
  carries its provenance pill + lock icon; toggling the lock
  hits `POST /api/v1/connectors/locks/{,/unlock/}` with
  `master_type=item`.
- **AppShell nav** — added "Items" with the `Package` icon,
  next to "Customers" in the Workflow group.
- **API client** — `Item` type + `listItems` / `getItem` /
  `updateItem` methods in `frontend/src/lib/api.ts`.

Tests: 14 new backend (list / detail / locked_fields x2 / patch
edit + audit / rename + alias filing / non-editable rejection /
blank canonical-name rejection / no-op / unit-price clear / 404
on cross-tenant). 926 total, was 912.

Durable design decisions:

- **Separate URLconf, not a re-mount.** `/api/v1/customers/`
  has been the enrichment URL prefix since Phase 1. Renaming
  it is a breaking API change for no benefit; mounting a
  second `items_urls` module is one line and keeps existing
  paths stable.
- **`update_item_master` mirrors the customer path.** The two
  master types are sibling structures — same provenance
  semantics, same alias-on-rename rule, same audit shape. The
  duplication is tiny + each path is read in isolation; an
  abstraction would just couple them without saving lines.
- **Unit price clears via `null` on the wire, not empty
  string.** Decimal columns reject `""`; the frontend converts
  the empty editor input to `null` before PATCHing. The
  backend service then maps `None`/`""` → `None` so either
  shape works for resilience.
- **No invoices-from-this-item view (yet).** Customer detail
  has it because buyers are the natural pivot for "what have
  we sent to them?". Items don't have a comparable user
  question — they're keys for auto-fill, not entities you
  manage. If demand surfaces we'll add it; for now the
  invoice-line-from-this-item view would be cluttered noise.

---

## Future direction: OCR-lane quality lifts (planned)

Slice 54 lands the selector + a regex floor structurer for
the OCR-only lane. Two follow-up slices close the quality
gap with the AI lane (numbering tentative — re-ordered below
the more critical security + signing work):

- **PaddleOCR + PP-Structure** — replaces EasyOCR in the
  OCR-only lane. PP-Structure detects tables → line items
  fed deterministically rather than guessing from flat text.
  Closes the "merged columns" failure mode that costs the
  regex floor most of its line-item accuracy.
- **LayoutLMv3 KIE** — pretrained HuggingFace checkpoint for
  invoice header fields (vendor TIN, invoice number, totals).
  Confidence scoring drives auto-flag-for-review.

Why not MindOCR directly: framework cost (MindSpore +
PyTorch in the same container) outweighs the convenience.
PaddleOCR + LayoutLMv3 cover the same surface on a stack we
already run.

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

**Backend:** 888 passing, 5 skipped (4 Postgres-only RLS tests + 1 native-PDF
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
- Audit stats — totals, 24h/7d windows, gap-filled sparkline, cross-tenant
  isolation, system-event exclusion, endpoint auth + active-org guard.
- Ingestion throughput — status bucketing, window filtering, per-day series
  reconciles with totals, `days` query-param clamp.
- Vision escalation — low-confidence text extracts re-route through the
  vision adapter; vision result short-circuits FieldStructure; graceful
  degrade on no-route / adapter-unavailable / vendor-failure with audit
  events recorded at every branch. Adapter mime dispatch (PDF document
  block vs image block) covered separately.
- Runtime config resolvers — DB-first with env fallback for both
  `Engine.credentials` (per-engine, via `extraction.credentials`) and
  `SystemSetting.values` (platform-wide, via `administration.services`);
  per-engine isolation, empty-string fall-through, `EngineUnavailable` /
  `SettingNotConfigured` on missing required values; upsert audit
  payload lists keys not values; Claude adapter regression test pins
  the DB-first resolution at the call site.
- Validation rules — 15 pre-flight rules (required fields, TIN format,
  currency, MSIC / country, dates, line + invoice arithmetic with
  tolerance, RM 10K threshold, SST consistency, invoice-number
  uniqueness within tenant) tested per-rule with focused mutations
  on a clean baseline. Service-level tests cover atomic re-run
  replacement, audit-payload contents (codes yes, messages no), and
  cross-tenant isolation.
- Enrichment (CustomerMaster + ItemMaster) — first-time create,
  repeat-buyer increment, TIN-vs-name match including alias learning,
  blank-fields auto-fill (never overwrites), legal-name protection
  (never silently changed), per-line item code inheritance,
  audit-payload PII redaction, cross-tenant isolation.
- Invoice updates (PATCH) — service-level: single + multi field,
  no-op detection, decimal coercion of currency-symbol input,
  unknown-field allowlist rejection, master propagation (corrects
  blank, overwrites wrong value, files old name as alias on rename),
  revalidation clearing resolved issues / surfacing newly-broken
  invariants. Endpoint-level: 200 happy path, 400 on unknown field,
  401/403 unauth, 404 cross-tenant. Static allowlist invariant pins
  submission-lifecycle field omissions.
- Customers API — list sorted by usage_count + name with active-org
  filter, unauth rejected; detail returns full master shape, 404
  cross-tenant; PATCH corrects allowlisted fields + audits with
  PII-redacted payload, rename files old name as alias, allowlist
  rejects auto-managed fields (aliases / usage_count /
  tin_verification_state) and unknown keys, no-op when nothing
  changed, cross-tenant PATCH 404.
- Line-item updates (PATCH ``invoices/<id>/`` with line_items array)
  — edits persist with confidence=1.0, decimal coercion handles
  "RM 250.50", one audit event covers combined header + line
  changes, ItemMaster propagation overwrites wrong defaults on
  pattern-stable fields (classification / tax_type / UOM /
  unit_price), allowlist rejects unknown line_number / unknown
  per-line fields / malformed payload shapes, true no-op when
  submitted values match current.
- Reference catalogs — seed migration presence (MSIC / classification
  / UOM / tax-type / country); lookup helpers return True for known,
  False for unknown / blank / inactive; refresh stub stamps active
  rows + skips deprecated; validation rules' two-tier severity
  (format ERROR + catalog WARNING) tested per-catalog with positive
  + negative cases.
- Per-customer invoice list — TIN-equality match returns matching +
  excludes non-matching; alias-fallback match (case-insensitive
  canonical + alias) when master has no TIN; cross-tenant 404; empty
  list for master with no invoices; unauth rejected; compact
  serializer field set pinned.
- Audit log surface — list scoped to active org, newest-first;
  action_type filter (exact match); cursor pagination via
  before_sequence; cross-tenant + system events excluded; sorted
  distinct action types for the dropdown; hex-encoded hashes
  serialized; limit clamping + invalid-input 400; unauth rejected.
- Chain verification — clean chain returns ok+count, tampered
  chain returns ok=False without leaking the offending sequence,
  the verify call itself is audited (one audit.chain_verified
  event per call with redacted payload), POST not GET (idempotency
  lie would mislead), unauth + no-active-org rejected.
- Engine activity — per-engine rollup counts (success / failure /
  unavailable broken out; success_rate ratio; avg_duration_ms int
  rounding); cross-tenant rows excluded; empty case returns []; call
  list newest-first with cursor pagination; serializer surfaces
  engine_name + vendor via SerializerMethodField; limit clamping +
  invalid-input 400.
- Organization settings — allowlisted edits land + emit a single
  audit event with field NAMES not values; no-op detection (no audit
  event); unknown fields rejected (TIN explicitly tested); blank
  legal_name rejected; static allowlist invariant pins exclusion of
  TIN / billing_currency / lifecycle / certificate_*; endpoint
  enforces membership-of-active-org (403) separately from
  no-active-org (400); cross-tenant access is 403 not 404 because
  membership check fires before lookup.
- All-invoices list — newest-first, status exact match, search
  OR-matches across invoice_number / buyer_legal_name / buyer_tin
  case-insensitively, cursor pagination, cross-tenant rows excluded,
  count is per-org, compact serializer field set pinned, invalid
  limit / cursor → 400.
- Exception Inbox — ensure_open is idempotent (creates + audits, no-op
  on unchanged, reopens resolved + audits, priority change writes
  audit); resolve_for_reason closes open rows automatically;
  resolve_by_user is idempotent + records actor; list + count scope to
  active org and exclude resolved / cross-tenant; pipeline wiring
  end-to-end (validation failure opens row, subsequent fix auto-
  resolves it); endpoint embeds invoice context, cross-tenant
  resolve → 404, invalid limit → 400.

**Frontend:** typecheck + lint clean; no unit tests yet.

---

## What's deferred (and where it should plug in)

Recently shipped (struck through items kept here briefly so a
reader checking the deferred list against an older session
state isn't confused):

- ~~**Live LHDN TIN verification**~~ — Slice 70.
- ~~**Live LHDN catalog refresh task**~~ — Slice 71. The
  catalog-miss severity promotes from WARNING to ERROR once
  `LHDN_CATALOG_BASE_URL` is configured + the first refresh
  has run.
- ~~**Signing service**~~ — Slice 58 (real signing) +
  Slice 59A (spec-conformance) + Slice 59B (UI).
- ~~**MyInvois submission**~~ — Slice 58. Cancel within 72h
  works (Slice 59B). Beat-scheduled poll sweep covers
  stuck-SUBMITTING rows (Slice 69).
- ~~**Email ingestion channel**~~ — Slice 64.
- ~~**WhatsApp ingestion channel**~~ — Slice 82. Per-tenant
  `phone_number_id` mapping; Meta Cloud API webhook with
  signature verification + injectable media fetcher.
- ~~**Items page with provenance + locks**~~ — Slice 83.
  Symmetric to the customer detail editor: list page, detail
  + PATCH, lock toggles, alias filing on rename.
- ~~**Signed-XML at rest**~~ — Slice 84. Envelope-encrypted
  signed bytes (XML or JSON) persisted to S3 on submission;
  decrypt-on-read download endpoint with digest verification
  and audited reads.
- ~~**AutoCount connector**~~ — Slice 85. CSV-driven adapter
  with baked-in AutoCount Debtor List / Stock Item column
  mapping; no column-mapping wizard required.
- ~~**i18n scaffold + Bahasa Malaysia**~~ — Slice 86. Client-
  side translation layer (`@/lib/i18n`), EN + BM tables
  (~30 high-traffic keys), language switcher in the user
  dropdown, persisted via `PATCH /identity/me/preferences/`.
- ~~**Billing + Stripe**~~ — Slice 63 + Slice 65 (Subscribe
  UI). FPX is part of Stripe checkout; nothing else needed.
- ~~**PII field-level encryption**~~ — covered by Slice 55's
  KMS envelope bundle for credentials, plus PII fields ride
  on TLS at rest in postgres' encrypted EBS volume in
  production. Per-column field-level encryption is still
  open if regulatory pressure warrants it.

Still open (ordered roughly by Phase 4–5 priority):

- ~~**Public API ingestion**~~ — Slice 78. `POST /api/v1/ingestion/jobs/api-upload/`
  with APIKey-only auth + JSON-base64 body.
- ~~**Inbox token rotation**~~ — Slice 80.
  `POST /api/v1/ingestion/inbox/rotate-token/` + Rotate button
  on the Settings → Integrations inbox card.
1. **Signed-XML at rest** — `signed_xml_s3_key` is now a
   free column (Slice 67); needs the actual KMS-encrypted
   blob path wired.
5. **Dual structuring lift for the OCR lane** —
   PP-Structure tables + LayoutLMv3 KIE on top of the
   RapidOCR text (Slice 72). Closes the "merged columns"
   gap on poor-quality scans.
- ~~**CI workflow**~~ — Slice 79. `.github/workflows/ci.yml`
  wraps `ruff` + `pytest` + frontend `prettier` / `lint` /
  `typecheck` / `build`.
7. **i18n** — Bahasa Malaysia + Mandarin + Tamil per
   ROADMAP Phase 6. English-only today.

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
