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

**Backend:** 378 passing, 5 skipped (4 Postgres-only RLS tests + 1 native-PDF
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

Ordered roughly by Phase 2/3 priority:

1. **Live LHDN TIN verification** — the format rule passes "looks like a
   TIN"; the API confirms the TIN actually exists. Updates
   `CustomerMaster.tin_verification_state` (Slice 14). Wires through
   the LHDN `SystemSetting` credentials (Slice 10).
2. **Live LHDN catalog refresh task** — the local catalogs (Slice 18)
   ship as a representative seed; the production refresh task hits
   LHDN's published endpoints monthly and upserts. Once it ships,
   the catalog-miss severity in the validation rules promotes from
   WARNING to ERROR.
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
8. ~~**Frontend sub-routes that show "soon" in the sidebar.**~~ All
   shipped: Customers (Slice 16) → Audit log (Slice 20) → Engine
   activity (Slice 22) → Organization settings (Slice 23) →
   Invoices (Slice 24) → Inbox (Slice 25). The sidebar is now
   entirely real surfaces.
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
