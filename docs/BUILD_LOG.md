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

- **Editable line items.** Tables with editable cells are fiddly
  UI work; header-only edits ship the bulk of the value. Line-item
  editing is the next-but-one slice on this surface.
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

- **Per-customer invoice list.** "Show me every invoice from this
  buyer" is the obvious next drill-down. Cheap once the invoice
  list endpoint supports a ``buyer_tin`` filter.
- **Search + filter** on the list. List is ordered by usage so the
  top-of-list is what the user usually wants; search waits until
  list size makes it worthwhile.
- **Item master surface.** Same shape, different table. Lower
  immediate value than customers; ships when the line-item
  editing slice lands and surfaces the masters as a side effect.
- **Bulk re-enrich** (apply current master to historical invoices
  whose fields don't match). Useful operator surface, premature.

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

**Backend:** 185 passing, 5 skipped (4 Postgres-only RLS tests + 1 native-PDF
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

**Frontend:** typecheck + lint clean; no unit tests yet.

---

## What's deferred (and where it should plug in)

Ordered roughly by Phase 2/3 priority:

1. **Live LHDN TIN verification** — the format rule passes "looks like a
   TIN"; the API confirms the TIN actually exists. Updates
   `CustomerMaster.tin_verification_state` (Slice 14). Wires through
   the LHDN `SystemSetting` credentials (Slice 10).
2. **MSIC / classification / UOM catalog matching** — format rules
   exist; full catalog matching needs cached LHDN catalogs (separate
   slice that fetches + refreshes monthly).
3. **Signing service** — placeholder Celery task on the dedicated
   `signing` queue exists. KMS-backed envelope encryption + Ed25519
   signature over `chain_hash` lands when KMS is provisioned.
4. **MyInvois submission** — placeholder Celery task exists. Real LHDN
   API client + UUID/QR retrieval + cancellation within 72-hour window.
5. **Email / WhatsApp / API ingestion channels** — only `web_upload` is
   wired. Web-upload is the most visible path; the others share the
   `IngestionJob` model and just need their adapters.
6. **Billing + Stripe + FPX** — `apps.billing` is empty; the plan/tier
   catalog from BUSINESS_MODEL.md isn't seeded.
7. **PII field-level encryption** — `Organization.contact_email`,
   `contact_phone`, `registered_address` are plain text in dev. Same
   KMS dependency as the runtime-config encryption (Slice 10).
8. **Frontend sub-routes that show "soon" in the sidebar** — Inbox,
   Invoices, Audit log, Engine activity, Settings. (Customers
   shipped in Slice 16.)
9. **CI workflow** — intentionally postponed. `.github/workflows/ci.yml`
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
