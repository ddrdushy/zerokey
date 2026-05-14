# PORTAL PLAN — Symprio as intermediary, ERP-pulled submission, monthly consolidation

> The plan for ZeroKey's next major capability set: turning the product from
> "drop a PDF, sign with your own cert, submit one invoice at a time" into
> "your ERP creates an invoice, we pull it, sign it with Symprio's
> intermediary certificate, and submit to LHDN automatically — with a
> monthly consolidation view your accountant can actually use."
>
> This document captures the strategic decisions, the open questions and
> their chosen defaults, the phased implementation, and the success
> criteria. Every phase below is meant to be picked up cold by an engineer
> (or by Claude Code) and executed without re-asking the founder for
> direction. When the executed reality diverges from this doc, the doc is
> updated in the same change — drift starts when nobody bothers.

## Why this matters

ZeroKey's current shape is **active**: a user signs in, drops a PDF, reviews
the extraction, clicks submit. That shape is fine for the SME owner who
sends two invoices a month. It does not scale to the accountant servicing
twenty SMEs, or to the operations manager whose ERP issues a hundred
invoices a week.

The accountants we want to win — the buyers Invoici-style products are
already chasing — think in terms of "my Xero / SQL Account orgs that need
to be LHDN-compliant". They want a system where invoices flow out of the
ERP into LHDN with as little manual touch as possible, and where the
monthly close gives them a single screen that says "this month is done".

This plan moves ZeroKey toward that shape without giving up the upload-a-PDF
path for customers who genuinely need it.

## Four strategic decisions

The founder confirmed the following on 14 May 2026. They are the
load-bearing assumptions for everything below; if any one of them
changes, this doc has to be rewritten before code is written.

### 1. Symprio Sdn Bhd is the LHDN intermediary

ZeroKey customers do **not** bring their own LHDN-issued digital
certificate. Symprio registers with LHDN as a software intermediary and
signs every customer's invoice on the customer's behalf. The TIN on the
signed MyInvois XML remains the customer's; the signing certificate is
Symprio's.

This removes the single largest onboarding friction in Malaysia's
e-invoicing transition — the "wait days for LHDN to issue your cert"
problem — and matches what Xero, AutoCount and others do for their own
customers.

It also concentrates risk and liability at Symprio: if our cert is
compromised, every signed invoice is suspect. The mitigations are
non-negotiable (see "Cross-cutting concerns" below).

### 2. No Xero connector at launch

We do not build a Xero integration. Our customers run **Malaysian
accounting software**: SQL Account, AutoCount, Sage UBS. Those connectors
already exist in skeleton form; we extend them, in that priority order,
to pull invoices.

If a Xero-using customer asks later, we add it. Until then, scope cap.

### 3. Two equally-first-class ingestion paths: ERP-pulled and manual upload

ZeroKey supports two entry points for invoices, and **both are
first-class**. A meaningful slice of Malaysian SMEs do not run a
formal ERP — they invoice from Excel, Word, or by hand. We do not
treat those customers as a fallback case.

**Path A — ERP pull.** The ERP creates the invoice. ZeroKey's
connector polls the ERP on a schedule (target: ≤ 15 minutes from ERP
commit to ZeroKey ingestion). For each new invoice / CN / DN:

- **Auto-submit ON for the org**: pass the pre-flight validation +
  extraction-confidence gate, then submit to LHDN immediately. The
  customer sees the resulting UUID + status.
- **Auto-submit OFF for the org**: the document lands in a "Not
  Submitted" queue. The customer reviews and clicks Submit (or the
  scheduled batch picks it up).

**Path B — Manual upload.** The customer drags a PDF, image,
spreadsheet, or forwards an email/WhatsApp. ZeroKey extracts the
fields, the customer reviews and approves, the submission is signed
and sent. This is the same auto-submit pipeline as Path A: if the
org has auto-submit ON and the extracted document passes validation +
confidence gates, it submits without a click.

Both paths converge on the same `IngestionJob → Invoice → Submission`
flow inside the platform. The `Invoice.source` field captures which
path produced it (`connector_sql_account`, `connector_autocount`,
`upload`, `email`, `whatsapp`, `api`) — useful for billing,
analytics, and routing — but downstream code never branches on it.

What this means for the portal UX: the **monthly bucket** lists every
document for the month regardless of path. The **eInvoices** tab shows
the same. The **per-org dashboard / inbox** surfaces the "drop a file"
affordance prominently for manual-first customers, and the "ERP pull
status" prominently for connector-first customers. Both groups see
the same monthly close.

### 4. Monthly consolidation surface — Invoice / CN / DN

A view that groups everything created in a calendar month: invoices,
credit notes, debit notes. Per month: status (Overdue / In Progress /
Complete), counts, totals, drill-in to the document list.

This is primarily a **UX rollup** — the accountant's monthly mental
model. LHDN consolidated B2C submission (the regulatory concept) is a
narrower feature that lives **inside** the invoice list for that month;
it is not the surface itself.

## Open questions resolved

### a) "Consolidation" — UI rollup vs LHDN consolidated submission

Both, with a clean distinction:

- **Monthly consolidation page** — pure UI. Lists every document
  created in the calendar month: Invoice / CN / DN. Status pills reflect
  individual document state (Submitted / Pending / Rejected /
  Cancelled). One screen per month. This is what the accountant
  navigates by.
- **LHDN consolidated B2C submission** — the actual MyInvois
  consolidated invoice document. Applies **only to B2C invoices**
  (consumer sales below the LHDN reporting threshold, where the supplier
  consolidates one month's worth into a single bundled document). CN
  and DN do not consolidate — they reference a specific prior invoice
  and submit individually. The "Consolidated" tab on the monthly page
  surfaces the B2C-eligible invoices and offers the bundled submission.

Customers who never see B2C transactions never see the consolidated-
submission affordance; it does not clutter their flow.

### b) Auto-submit guardrails

Auto-submit is fail-closed. An invoice only goes to LHDN automatically
when **all** of the following are true:

1. The org has `auto_submit_default = True` set in Settings.
2. The pre-flight validation passes (no LHDN rule violations detected
   locally — TIN format, MSIC code, totals, mandatory fields).
3. The extraction confidence on every mandatory field is ≥ the
   configured threshold (default: 0.92). Anything below the threshold
   drops to the manual queue regardless of the org-level toggle.
4. The customer record (the buyer) does not have a manual override
   forcing review (`Customer.auto_submit_override = "review"`).

A customer record may also override **on** (`auto_submit_override =
"always"`), useful for trusted recurring buyers when the org-level
default is off.

When auto-submit is blocked for any of reasons 2–4 above, the document
lands in the "Not Submitted" queue with a clear reason on the row
("Extraction confidence below threshold", "Buyer requires review",
"Validation: supplier_tin.format"). The customer is never left guessing
why it didn't go.

## Phased implementation

Five engineering phases plus a dashboard refresh. Each phase is sized to
ship independently; later phases assume earlier ones are merged.

### Phase 1 — Intermediary signing mode (≈ 1 week eng) — **SHIPPED 2026-05-14 (c6289c4)**

Foundation. Adds a per-organization signing mode and routes every
existing submission through the new mode-aware signing service.

**Backend**

- `Organization.signing_mode` — enum `self_signed | intermediary`.
  Default `intermediary` for new orgs created after this phase ships.
- `Organization.intermediary_consent_at` — timestamp the customer
  accepted the "Symprio signs on my behalf" terms. Required before any
  intermediary submission goes out.
- Platform-level **Symprio intermediary certificate** stored in the
  KMS-encrypted certificate blob path, but at a singleton location
  outside any tenant scope. Same encryption envelope as customer certs;
  decryption only by the signing worker.
- `apps.submission.signing` rewritten to dispatch on `org.signing_mode`.
  Self-signed orgs continue to use their uploaded certificate; the new
  default path loads Symprio's intermediary cert.
- Audit events: every intermediary submission emits
  `submission.signed_as_intermediary` with the org id, invoice id, cert
  serial, and the timestamp. Symprio's compliance team can pull this
  feed any time.

**Frontend**

- Settings → Compliance gets a "Signing mode" panel. Existing
  self-signed customers see their cert details (unchanged). New orgs
  default to intermediary mode and show a consent checkbox + the
  Symprio LHDN intermediary registration number.

**Out of scope for this phase**

- Migrating existing customers from `self_signed` to `intermediary`.
  That is a customer-by-customer conversation, not a flag flip.

**Done when**

- A newly-registered org can submit an invoice with no certificate
  upload of its own. The submission lands at LHDN as validated.
- An existing customer with a self-signed cert continues to submit
  unchanged.
- Every intermediary submission shows up in the audit log with the
  expected event type.

### Phase 2 — Connector invoice import (revised after survey)

The original Phase 2 plan assumed a live ODBC / API connection that
ZeroKey could poll. A survey of the existing connector framework on
2026-05-14 turned up a different reality: the SQL Account, AutoCount
and Sage UBS adapters are all **CSV-upload-based** — they wrap a
generic ``CSVConnector`` and expect the customer to export from their
ERP and upload the CSV. There is no live connection today and none
of the three ERPs lend themselves to a cloud-side poll (Firebird /
DBISAM / MSSQL files behind customer-network NAT).

That changes the shape of Phase 2 into a v1 → v2 split:

**Phase 2 v1 — CSV-driven invoice import** (Path B). Extend the
existing customer-master / item-catalog CSV path to cover sales
invoices, credit notes, and debit notes. The customer drops a weekly
sales-invoice CSV export from their ERP; we batch-create one
``IngestionJob`` per row and run them through the rest of the
pipeline (validation → auto-submit → LHDN). Same data shape as the
live-poll endpoint will eventually use; only the trigger differs.

**Phase 2 v2 — Live poll** (Path A, follow-up after v1 lands and we
have real customers asking for it). Requires either an on-prem
sync agent or a reverse-tunnel into the customer's network to reach
their ERP database. Material engineering effort (4-6 weeks),
material deployment change (we now run code on the customer's
network), and best held until we have validated CSV-import demand.

The remainder of this section describes Phase 2 v1 — what's actually
being built now. Phase 2 v2 inherits the data model and the
downstream pipeline; only the upstream trigger changes.

#### Phase 2a — CSV parser foundation (≈ 1-2 days)

- ``apps.connectors.document_records.ConnectorDocumentRecord``
  dataclass: structured representation of one ERP-issued document.
  Shape covers invoice / credit note / debit note via a
  ``document_type`` field; fields cover external_ref, issue_date,
  supplier + buyer parties, line items, totals, currency.
- ``apps.connectors.adapters.base.BaseConnector.fetch_documents()``
  abstract method (default: yield empty). Concrete adapters that
  support invoice import override it.
- ``apps.connectors.csv_invoices.parse_sql_account_sales_invoice``
  — pure function: ``bytes -> Iterable[ConnectorDocumentRecord]``.
  Column mapping lives next to it. Unit-tested in isolation.
- ``ConnectorPullCursor`` model in ``apps.connectors.models`` — one
  row per (org, connector_type, document_type, external_ref) so a
  re-uploaded CSV doesn't create duplicate IngestionJobs. Tenant-
  scoped; RLS keeps cursors invisible across orgs.
- New endpoint ``POST /api/v1/connectors/<id>/preview-invoices/``:
  accepts a CSV body, returns ``{rows_parsed, would_create,
  duplicates, errors}`` for the customer to confirm before
  committing. No database writes from this endpoint.

#### Phase 2b — Structured Invoice creation (≈ 2 days)

- New service ``apps.connectors.services.import_documents(
  organization_id, records, connector_type, source_filename)``
  — for each ``ConnectorDocumentRecord``:
    1. Check the cursor; skip if (external_ref, document_type)
       already imported for this org + connector.
    2. Create an ``IngestionJob`` with
       ``source_channel=DATABASE_CONNECTOR``,
       ``source_identifier=<connector_type>:<external_ref>``,
       and the CSV row stored as the source blob.
    3. Create the ``Invoice`` directly from the structured record —
       bypassing OCR / extraction since the data is already
       structured. ``extraction_confidence`` is set to ``1.0``;
       the IngestionJob transitions ``RECEIVED → VALIDATING``
       (skipping CLASSIFYING / EXTRACTING / ENRICHING).
    4. Record the cursor row.
- Convert the preview endpoint into a real ``POST
  /api/v1/connectors/<id>/import-invoices/`` that does the writes.
- Audit event ``ingestion.connector_import`` per CSV batch +
  ``ingestion.connector_import.row`` per row.

#### Phase 2c — Remaining connectors (≈ 2 days)

- AutoCount sales-invoice CSV mapping + adapter override.
- Sage UBS sales-invoice CSV mapping + adapter override.
- One column-mapping function per vendor; shared
  ``parse_csv_with_mapping`` helper.

#### Phase 2d — UI (≈ 2 days)

- Per-connector ``/dashboard/connectors/<id>/`` gains an "Upload
  invoices CSV" section alongside the existing customer + items
  upload affordances.
- Two-step flow: drop CSV → preview shows rows / duplicates /
  errors → confirm to commit.
- Last-import timestamp + summary surfaced on the connector card.

**Done when**

- A customer with the SQL Account connector configured can upload
  their weekly sales-invoice CSV, see a preview, confirm, and have
  every row land as a populated Invoice ready for the auto-submit
  pipeline.
- A re-upload of the same CSV creates zero duplicates.
- Identical flow works for AutoCount and Sage UBS using their own
  CSV export shapes.
- The IngestionJob audit trail clearly identifies "this Invoice
  came from connector X, row Y, original CSV at <s3-key>".

**Deferred to Phase 2 v2** (live poll, weeks not now)

- Celery beat task polling on a 15-minute cadence.
- ConnectorPullCursor as a high-water mark on (issued_at, id)
  rather than a per-document-ref dedup table.
- On-prem sync agent / reverse-tunnel deployment model.

### Phase 3 — Auto-submit toggle and queue (≈ 1 week eng)

Wires the auto-submit decision into the inbox-to-LHDN flow.

**Backend**

- `Organization.auto_submit_default` — boolean, default `false`.
- `Organization.auto_submit_confidence_threshold` — float, default
  `0.92`.
- `Customer.auto_submit_override` — enum `none | always | review`.
  `none` follows the org default; `always` forces auto-submit;
  `review` forces manual.
- New `Invoice.auto_submit_blocked_reason` — short string captured
  when an auto-submit candidate fails one of the gates (validation /
  confidence / customer override). Surfaced on the "Not Submitted" row.
- `apps.submission.services.handle_pulled_invoice(invoice_id)` —
  applies the gates and either dispatches to the existing submission
  pipeline or transitions to `NOT_SUBMITTED`.

**Frontend**

- Settings → Submission gets the toggle + threshold + per-customer
  override editor.
- The invoices list adds a clearly-visible status pill for
  "Not Submitted" rows and a per-row Submit action.

**Done when**

- A new ERP-pulled invoice for an org with auto-submit ON, passing
  validation + confidence, is at LHDN within seconds.
- A failing-confidence invoice for the same org lands in
  Not Submitted with the right reason.
- Flipping the toggle off pauses all future auto-submissions.

### Phase 4 — Monthly consolidation surface (≈ 2 weeks eng)

The UX layer the accountant sees first when they sign in.

**Frontend**

- New top-level page: `/portal` (or replaces `/dashboard`, see below).
  Lists every org the signed-in user is a member of. Per-org row shows
  ERP connection status, MyInvois registration status (TIN + BRN), and
  an "Open" button into the per-org tabs.
- Per-org tab structure:
  - **Registration** — confirms the LHDN intermediary linkage, shows
    the Peppol identifier, surfaces the BRN and TIN.
  - **Monthly Consolidation** — monthly bucket list with status
    pills. Drill-in shows all docs (Inv / CN / DN) created that month.
  - **eInvoices** — flat list of all documents with date filter,
    type filter (Inv / CN / DN / Self-bill), status filter. Per-row
    Submit + View-in-ERP.
  - **Settings** — auto-submit toggle, confidence threshold, customer
    overrides, signing mode.

**Backend**

- `apps.submission.services.monthly_bucket(organization_id, year_month)`
  — returns counts + totals by document type and submission status for
  the page rollup.
- `apps.identity.services.user_org_portal_summary(user_id)` — one
  query returning everything the portal landing needs (org name, ERP
  health, MyInvois status, last activity).

**Done when**

- An accountant managing three orgs sees all three in the portal and
  can drill into each.
- The monthly view for a fully-submitted month shows "Complete".
- The monthly view for a month with three unsubmitted invoices shows
  "Needs action" with a count.

### Phase 5 — LHDN consolidated B2C submission (≈ 1 week eng)

The actual regulatory consolidation feature, gating on the existing
`consolidated_b2c` feature flag.

**Backend**

- `apps.submission.services.build_consolidated_b2c(organization_id,
  year_month)` — picks every B2C invoice in the month that hasn't been
  individually submitted to LHDN, builds the consolidated MyInvois
  document, signs it (intermediary or self-signed per the org), submits
  to LHDN.
- Bookkeeping: the individual B2C invoices stay in the database with
  status `CONSOLIDATED` referencing the consolidated submission's UUID.
- Beat task: on the first business day of each month, build and submit
  last month's consolidated B2C document for every org with the flag
  enabled and `consolidated_b2c_auto_submit = True`.

**Frontend**

- The Monthly Consolidation page gains a "Consolidated B2C" section per
  month when applicable, with the bundled document's UUID + status.

**Done when**

- An org with the flag on, the auto-submit setting on, and >0 B2C
  invoices in a month gets a single bundled submission to LHDN on the
  1st of the following month.
- Per-invoice CN and DN continue to submit individually.

### Dashboard refresh

The phases above land an accountant-first surface at `/portal` and
inside the per-org tabs. The existing dashboard is rebuilt — not
deleted — to make both ingestion paths first-class.

**The new per-org landing page** (replacing today's `/dashboard`)
shows both, prominently:

- **Drop an invoice** — large, top-of-page drop zone for manual upload.
  Customers without an ERP land here and need nothing else. This is
  not buried — it is the primary affordance for the manual path.
- **From your ERP** — adjacent panel showing connector status, last
  pull, and the most recent ERP-pulled documents waiting on review.
  Hidden when no connector is configured.
- **Needs your attention** — combined queue across both paths:
  documents waiting on review, validation failures, LHDN rejections.
- **Recent activity** — the unified document timeline.

Customers with an ERP connector see the "From your ERP" panel
filled in. Customers without one see only the drop-zone path. Neither
group has to dig through tabs to do their actual job.

The `/portal` page is the multi-org accountant view above this — it
lists every org the user can access, and clicking "Open" goes to the
per-org landing described here.

## Cross-cutting concerns

These aren't phase-bounded; every phase contributes.

### Intermediary liability and the audit story

When Symprio signs on a customer's behalf, Symprio is on the hook for
the signed declaration. Mitigations:

- The signing service emits a tamper-evident audit event for every
  intermediary submission, including: org id, invoice id (and content
  hash), Symprio cert serial, submitting actor, timestamp. The audit
  chain ties them together so nobody can rewrite history.
- Customer terms (separate legal track) explicitly authorise Symprio
  as the signing party. The `intermediary_consent_at` timestamp on
  Organization is the in-product record of that consent.
- The Symprio intermediary cert lives in KMS-encrypted form, decrypted
  only by the signing worker. Even our own engineering staff cannot
  extract the private key.
- Rotation procedure documented in `OPERATIONS.md` (todo): we expect
  to rotate the intermediary cert annually.

### Validation must be tight before auto-submit lands

Today our validation runs but tolerates ambiguity (the customer sees
warnings and decides). Auto-submit is intolerant — anything that would
be a warning for a human becomes a hard block for the machine. Phase 2's
validation pass needs to be deliberately stricter than the manual flow,
or we generate LHDN rejections that the customer notices three days
later when they can no longer cancel.

### ERP polling fairness and rate limits

SQL Account, AutoCount and Sage UBS aren't designed for high-frequency
polling. We poll at 15-minute cadence per connector with exponential
back-off on errors. The connector framework caps concurrent pulls
across the platform to avoid hammering any single customer's accounting
server. SystemSetting controls the global rate cap.

### Backwards compatibility for current customers

Existing customers using the upload-a-PDF flow with their own cert keep
working. They are `signing_mode = self_signed` and their flow is
unchanged. The intermediary path is the new default for new
registrations; conversion of existing customers happens through a
support-led conversation, not a silent flag flip.

## What "done" looks like at the end

The 8-week build window closes with:

- A new customer signs up with just BRN + TIN, accepts the intermediary
  terms in the same flow, and is ready to submit invoices in under five
  minutes. No certificate dance.
- **Customers with an ERP**: SQL Account (at minimum) issues an invoice
  and within 15 minutes it is in ZeroKey. If the customer has
  auto-submit on, it is at LHDN within another 5 minutes.
- **Customers without an ERP**: drop a PDF or forward an email and the
  same pipeline runs. Auto-submit ON sends it to LHDN as soon as it
  passes validation + confidence; auto-submit OFF lands it in the
  Not Submitted queue for review.
- The customer's accountant logs in and sees a portal listing every
  org they manage. Each org shows monthly buckets. The current month
  shows "In Progress", last month shows "Complete", and any older
  unfinished month shows "Overdue" with a count.
- The customer can flip auto-submit off for a specific high-value
  buyer ("review my Petronas invoices manually before submission") and
  it just works.
- The consolidated B2C feature is on for retail customers and produces
  one MyInvois document per month, automatically.

## How this document evolves

When a phase ships, mark it in the heading and add a short line
referencing the merge commit. When the implementation diverges from
the plan (it will), update the relevant section — do not let the doc
drift from reality.

When a new strategic call lands — a fifth founder decision, a new
connector, an LHDN spec change — add it under "Four strategic
decisions" (rename to match), and ripple through the phases.

When this entire capability set is shipped and stable, this document
moves to `docs/archive/` and the operational truth lives in
`ARCHITECTURE.md` + per-area runbooks.

## Cross-references

- `PRODUCT_VISION.md` — why ZeroKey exists, who we serve.
- `LHDN_INTEGRATION.md` — the regulatory surface this builds on.
- `BUSINESS_MODEL.md` — pricing implications (intermediary mode probably
  becomes a Starter-tier-and-up entitlement).
- `SECURITY.md` — the key management and KMS story.
- `OPERATIONS.md` — pull cadence, rate limits, incident response.

When you start a phase, read the relevant cross-references before
writing code.
