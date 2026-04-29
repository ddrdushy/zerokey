### Slice 15 — Reference-data connectors (read-only, human-in-the-loop)

`apps.integrations` finally does work — the bounded context that's been
sitting empty since Phase 1, defined in [ARCHITECTURE.md](ARCHITECTURE.md)
but never populated. Closes the cold-start gap behind `CustomerMaster` /
`ItemMaster` from Slice 14: today every new tenant has empty masters on
day one, so the first weeks of usage are review-heavy by construction.
This slice pre-populates the masters from systems the customer already
maintains.

The defining principle of this slice — and the reason it's structured
the way it is — is **merge policy proposes; human disposes**. A connector
sync is never a thing that silently writes to the master. Every sync is
a two-phase operation: a `SyncProposal` is built first, the user reviews
the diff, and only on approval is the merge applied. Auto-resolve is
reserved for the truly unambiguous cases (empty field gets populated,
identical value is a no-op, same-source update overwrites itself).
Everything else routes to a conflict queue and waits for a human.

Strategic mapping:

- The "every correction makes the system smarter" promise in
  [PRODUCT_VISION.md](PRODUCT_VISION.md) gets a head-start instead of a
  cold-start, *and* the corrections users make in the conflict queue
  feed the same learning loop.
- The switching-cost moat in [BUSINESS_MODEL.md](BUSINESS_MODEL.md)
  compresses from "after 30 days of use" to "after first sync".
- The `unverified` honesty pattern visible in the customer-master UI
  ("Live LHDN verification lands in a follow-up slice") extends to
  per-field provenance — synced data is never silently authoritative,
  and the user always sees what's about to change before it changes.
- The "propose, don't impose" disposition is consistent with
  [UX_PRINCIPLES.md](UX_PRINCIPLES.md) and the honesty rule in
  [docs/README.md](README.md).

What lands:

- **`apps.integrations.connectors.base.BaseConnector`** — abstract
  interface: `authenticate()`, `fetch_customers()`, `fetch_items()`,
  `health_check()`. Each implementation returns normalized dicts
  matching `CustomerMaster` / `ItemMaster` field names; the connector
  layer never writes to the DB directly.
- **`CSVConnector`** — first concrete implementation. Accepts a CSV
  upload via `/api/v1/integrations/csv/import/`, with a column-mapping
  step in the UI. Always works, zero auth, ships first.
- **`SQLAccountingConnector`** + **`AutoCountConnector`** — Malaysian
  SME footprint. Both are ODBC/SQL Server underneath, so they share a
  `_LegacyAccountingBase` mixin for connection management.
- **`XeroConnector`** + **`QuickBooksConnector`** — OAuth2, REST.
  Single shared `_OAuth2Base` mixin for token refresh.
- **`ShopifyConnector`** + **`WooCommerceConnector`** — B2C-heavy
  customer lists; mostly TIN-less rows where address + phone + name
  variants do the work for alias matching.

- **`IntegrationConfig`** model — one row per (Organization, connector
  type). Holds `connector_type` (enum), `credentials` (KMS-encrypted
  JSON), `sync_cadence` (manual / hourly / daily), `auto_apply` (bool,
  default `False`, only settable after a successful manual sync),
  `last_sync_at`, `last_sync_status`, `last_sync_error`, soft-delete
  flag. RLS policy matches the rest of the codebase.

- **`SyncProposal`** — the durable record of a sync run before it's
  applied. Holds the integration_config_id, the actor who triggered
  it, `proposed_at`, `applied_at` (nullable), `applied_by` (nullable),
  `reverted_at` (nullable), `reverted_by` (nullable),
  `expires_at` (proposed_at + 14 days), and a `diff` JSON blob:
  ```json
  {
    "customers": {
      "would_add": [...full records...],
      "would_update": [{"existing_id": "...", "changes": {...}}],
      "conflicts": [{"existing_id": "...", "field": "tin", ...}],
      "skipped_locked": [...],
      "skipped_verified": [...]
    },
    "items": { ... same shape ... }
  }
  ```
  The diff is reversible: an `apply_sync_proposal` writes deterministic
  changes that `revert_sync_proposal` can undo within the 14-day window
  by walking the diff in reverse.

- **`MasterFieldConflict`** — field-level conflicts that the merge
  classifier chose not to resolve unilaterally. Holds the master
  record reference (CustomerMaster or ItemMaster, via generic FK), the
  field name, the existing value + provenance, the incoming value +
  provenance + source, the `sync_proposal_id`, and a `resolution`
  field that's `null` until a user acts (then one of:
  `keep_existing`, `take_incoming`, `keep_both_as_aliases`,
  `enter_custom_value`). Conflicts are resolved one at a time in v1.

- **`MasterFieldLock`** — a per-field pin. When set, future syncs that
  would change the field always route to the conflict queue, never
  auto-resolve. Holds master record reference, field name, locked_by,
  locked_at, and an optional reason. Locks are visible as a small lock
  icon on the field in the UI.

- **`MasterFieldProvenance`** — per-field provenance, stored as a JSON
  column `field_provenance` on `CustomerMaster` and `ItemMaster`:
  ```json
  {
    "tin": {
      "source": "synced_autocount",
      "source_record_id": "DEBT-00482",
      "synced_at": "2026-04-29T07:14:00Z",
      "verification_state": "unverified_external_source",
      "applied_via_proposal_id": "...",
      "approved_by": "user_uuid"
    },
    "msic_code": {
      "source": "extracted",
      "invoice_id": "9c8b...",
      "extracted_at": "2026-04-12T03:22:00Z",
      "verification_state": "unverified"
    }
  }
  ```
  Per-record provenance was rejected — different fields legitimately
  come from different sources, and an audit response needs that
  granularity. JSON column over a separate `ProvenanceEntry` table
  because every read of `CustomerMaster` would otherwise need a join,
  and the field set is small enough that JSON is fine.

- **Merge classification.** `apps.enrichment.classify_merge(existing,
  incoming, source)` returns one of: `auto_populate`, `noop`,
  `auto_overwrite`, `conflict`, `skipped_locked`, `skipped_verified`.
  The full matrix:

  | existing state                          | incoming               | result               |
  | --------------------------------------- | ---------------------- | -------------------- |
  | empty                                   | any                    | `auto_populate`      |
  | identical to incoming                   | any                    | `noop`               |
  | `synced_X`                              | `synced_X` (same)      | `auto_overwrite`     |
  | `synced_X`                              | `synced_Y` (different) | `conflict`           |
  | `extracted`                             | any external           | `conflict`           |
  | `manual`                                | any external           | `conflict`           |
  | `verified_lhdn`                         | any                    | `skipped_verified`   |
  | locked (`MasterFieldLock` present)      | any                    | `skipped_locked`     |

  Every cell of this matrix has a named test case.

- **Sync orchestration, two-phase.**
  `apps.integrations.tasks.sync_connector(integration_config_id)`
  always runs the propose phase: pulls source data, classifies every
  field, writes a `SyncProposal`, emits one
  `integration.sync_proposed` audit event with the full counts.
  Then it checks `IntegrationConfig.auto_apply`:
  - If `auto_apply=False` (default): stop. The UI shows a "Review
    sync proposal" surface; nothing writes until the user approves.
  - If `auto_apply=True` AND `len(conflicts) == 0`: chain into
    `apply_sync_proposal` automatically. Even with auto-apply on,
    a single conflict halts the whole run for review — the audit
    story stays clean because every applied change is either
    auto-resolvable or explicitly approved.
- **`apply_sync_proposal(proposal_id, user_id, exclusions=[])`** —
  writes the auto-resolvable changes and the `would_update` records
  the user didn't exclude. Per-field provenance is updated with
  `applied_via_proposal_id` and `approved_by`. Emits
  `integration.sync_applied`. Then triggers the re-match pass.
- **`revert_sync_proposal(proposal_id, user_id, reason)`** — within
  the 14-day window, walks the diff in reverse and restores prior
  state, including provenance. Emits `integration.sync_reverted`.
  After 14 days, the proposal record is retained for audit but the
  revert path is closed.
- **`resolve_field_conflict(conflict_id, resolution, user_id,
  custom_value=None)`** — applies the user's choice, updates
  provenance to mark the field as `manually_resolved` with the
  decision recorded, emits `master_record.conflict_resolved`. If the
  conflict was created by a `SyncProposal` that is still pending
  apply, resolving the conflict updates the proposal in place; if the
  proposal has already been applied (the conflict was deferred), the
  field updates immediately.

- **Re-match pass.** After every successful **apply** (not propose),
  `apps.enrichment.rematch_pending_invoices(organization_id)` walks
  every `Invoice` in `ready_for_review` for the org and re-runs
  customer/item match. Lifted matches write
  `invoice.master_match_lifted_by_sync` to the audit chain with the
  connector and the before/after confidence. The user-visible payoff
  — the review queue shrinking — happens at the moment of apply, not
  at the moment of propose, so cause and effect are clear.

- **UI surfaces** (frontend, in this slice):
  - `Settings → Integrations` — list of connectors with health,
    last-sync, auto-apply toggle (disabled until first manual apply),
    "Sync now" button.
  - **Sync preview screen** — opens after a propose run completes.
    Three-tab layout: *Will add* (new records, accept-all checkbox),
    *Will update* (per-record diff with per-field accept/exclude),
    *Conflicts* (count + link into the conflict queue). Bottom row:
    "Apply approved changes", "Cancel proposal", "Save for later".
  - **Conflict queue** (`Inbox → Conflicts` lane, separate from the
    invoice review queue). Each row: field name, existing value with
    provenance pill, incoming value with provenance pill, three
    buttons — *Keep existing*, *Take incoming*, *Keep both as
    aliases* — plus an *Enter custom value* affordance. Each click
    closes the row and writes one audit event.
  - **Customers / Items pages** — provenance pill on each field
    (`from AutoCount`, `learned from invoice`, `entered manually`,
    `verified by LHDN`, `manually resolved`). Lock icon next to each
    field; clicking it toggles `MasterFieldLock`.
  - **Inbox** — when re-match lifts an invoice from `needs_review`
    to `ready_for_submission` after an apply, surface inline:
    *"Resolved automatically — buyer matched from AutoCount sync."*
  - **"Undo last sync"** affordance on the integration's settings
    page, visible only while the proposal is within the 14-day
    window. Confirmation dialog shows what will be reverted.

Field mapping (for `CustomerMaster`):

| ZeroKey field          | SQL Accounting       | AutoCount            | Xero                       | QuickBooks         | Shopify / Woo        |
| ---------------------- | -------------------- | -------------------- | -------------------------- | ------------------ | -------------------- |
| `canonical_name`       | `DebtorName`         | `CustomerName`       | `Name`                     | `DisplayName`      | `company` or person  |
| `tin`                  | `TaxID` / custom     | `TaxRegNo`           | `TaxNumber`                | `TaxIdentifier`    | custom field         |
| `registration_number`  | `CoNo`               | `BRNo`               | `CompanyNumber`            | custom field       | custom field         |
| `msic_code`            | —                    | —                    | —                          | —                  | —                    |
| `sst_number`           | `SSTNo`              | `GSTRegNo`           | —                          | —                  | —                    |
| `address`              | `Address1..4` concat | address block        | `Addresses[0].AddressLine` | `BillAddr`         | `default_address`    |
| `phone`                | `Phone1`             | `Phone`              | `Phones[].PhoneNumber`     | `PrimaryPhone`     | `phone`              |
| `country_code`         | `Country`            | `Country`            | `CountryCode`              | `Country`          | `country_code`       |
| `aliases[]`            | historical names     | historical names     | historical names           | historical names   | historical names     |

MSIC stays empty after sync and is filled by extraction (Slice 14
path) or by manual edit. Required only at LHDN submission time;
validation (Phase 3) surfaces the gap then, not at customer-master
create time.

Order of sources, in build order:

1. **`CSVConnector`** — ship first. Zero auth, universal escape
   hatch, easiest test fixture for the propose / apply / conflict
   flows.
2. **`SQLAccountingConnector`** + **`AutoCountConnector`** — the
   Malaysian SME accounting majority. ODBC drivers in the backend
   image, credentials KMS-encrypted.
3. **`XeroConnector`** + **`QuickBooksConnector`** — OAuth2 flow,
   tokens refreshed by the connector base.
4. **`ShopifyConnector`** + **`WooCommerceConnector`** — B2C
   tenants. Validates the alias-only match path because most rows
   are TIN-less.

Audit events introduced by this slice:

- `integration.sync_proposed` — counts of would_add, would_update,
  conflicts, skipped_locked, skipped_verified.
- `integration.sync_applied` — actor, exclusions, totals applied.
- `integration.sync_reverted` — actor, reason, totals reverted.
- `master_record.field_locked` / `master_record.field_unlocked` —
  actor, field, reason.
- `master_record.conflict_resolved` — actor, field, choice,
  custom_value if any.
- `invoice.master_match_lifted_by_sync` — already specified in
  Slice 14 follow-on; emitted here from the re-match pass.

Tests:

- Unit tests per connector: field-mapping correctness against
  fixture payloads from each source's docs / sandbox.
- The full classification matrix (every cell) — named test cases.
- `MasterFieldLock` always routes to conflict, even when the source
  is the same one that originally populated the field.
- Apply path: provenance updates correctly; re-match runs.
- Revert path: provenance and value restored; re-match runs again
  if any lifts had happened.
- Revert window: a proposal older than 14 days returns a clean
  `RevertWindowExpired` error.
- Auto-apply with zero conflicts: chain happens automatically.
- Auto-apply with one conflict: full proposal halts, no auto-apply.
- Conflict resolution: each resolution choice writes the right
  provenance state and the right audit event.
- Re-match pass test: an invoice in `ready_for_review` whose buyer
  is unresolvable; CSV upload + apply lifts the invoice; assert
  audit event written.
- RLS: org A can't read, propose into, apply, revert, lock, or
  resolve conflicts on org B.

Durable design decisions:

- **Two-phase sync from the first commit.** Propose, then apply.
  Even on auto-apply, the propose record is durable and the apply
  is a separate audited event. There is no path in the code where
  a sync writes to the master without a `SyncProposal` row first.
- **Auto-apply is opt-in, per-connector, never the default.** The
  toggle is disabled until the first manual apply has succeeded.
  Even with auto-apply on, a single conflict halts the run for
  review.
- **Locks are stronger than provenance trust ranks.** A locked
  field always routes to the conflict queue, regardless of source.
  This is the path by which a user makes a correction stick against
  a noisy source.
- **Per-field provenance, not per-record.** Different fields come
  from different sources; the field is the right granularity. JSON
  column on the master record, not a separate provenance table.
- **External sources are never authoritative.** A synced TIN is
  `unverified_external_source` until LHDN verification (separate
  follow-up slice). Three verification states — `unverified`,
  `unverified_external_source`, `verified_lhdn` — three pills, plus
  `manually_resolved` for fields the user touched in the conflict
  queue.
- **Read-only, one direction, this slice only.** ZeroKey does not
  write back to source systems. Two-way sync is a P2 decision with
  its own design problems (conflict resolution, deletion semantics,
  who wins when both sides edited) and is not in scope.
- **Aliases are accumulative.** If three sources spell SkyRim three
  ways, all three become aliases. `canonical_name` is set on first
  sync and only the user changes it.
- **Re-match runs on apply only.** Not on propose, not on revert
  alone (revert triggers a re-match because lifts may need to
  reverse, but the re-match logic itself is idempotent).
- **Reversibility window is 14 days.** Long enough to catch a bad
  export the next business cycle; short enough that the diff blob
  doesn't accumulate forever. After 14 days the proposal is
  retained for audit but the revert path is closed.
- **No invoice ingestion through these connectors.** Reference
  data only. Invoices arrive through the existing channels
  (drop-zone, email forward, API). Mixing the two would muddy the
  connector model and create competing ingestion paths.
- **The conflict queue is its own inbox lane, not mixed with the
  invoice review queue.** Different cognitive task, different
  resolution actions. Mixing them dilutes both.

What's explicitly deferred:

- Two-way sync (P2, separate slice).
- Real-time / webhook-driven sync (this slice is schedule +
  on-demand pull only).
- **Bulk conflict resolution** ("take all incoming for source X",
  "keep all existing where conflict is on TIN"). v1 resolves one
  conflict at a time. Bulk is a P2 once we see actual conflict
  patterns.
- Shopee / Lazada / TikTok Shop connectors — marketplace OAuth +
  per-marketplace schema work; valuable but not in this slice.
- LHDN TIN verification of synced records — depends on LHDN API
  integration slice; until then synced TINs stay
  `unverified_external_source`.
- Chrome extension single-record capture — different mechanism
  (one record at a time, scraped from a webpage), worth its own
  slice.
- A `ProductMaster` ↔ source mapping for warehouse/inventory
  systems — the current `ItemMaster` model is invoice-line-shaped,
  not SKU-shaped, and this slice does not change that.
- Default-MSIC-by-industry heuristic — flagged for ROADMAP but
  separate slice; would integrate with whichever LHDN-validated
  industry classification the verification slice produces.
- Admin override of provenance state without going through the
  conflict-queue UI — read-only display in this slice; admin
  override is a follow-up.
- Per-source preference rules ("when AutoCount and Xero disagree,
  prefer AutoCount") — every conflict goes to a human in v1.

---

## Brief for Claude Code

When you start the session that builds this slice, load these docs in
addition to `START_HERE.md` and `PRODUCT_VISION.md`:

- `ARCHITECTURE.md` — for the `apps.integrations` bounded-context
  expectations.
- `DATA_MODEL.md` — for `CustomerMaster` / `ItemMaster` current shape.
- `INTEGRATION_CATALOG.md` — for any prior decisions about source
  systems; if it's silent on these specific connectors, this slice
  becomes its first concrete entry and the doc is updated in the
  same PR.
- `AUDIT_LOG_SPEC.md` — for the new event types listed above.
- `UX_PRINCIPLES.md` — for the propose-don't-impose disposition; the
  sync preview and conflict queue UI must be consistent with it.
- The most recent `BUILD_LOG.md` slice (Slice 14) — for the
  `CustomerMaster` / `ItemMaster` shape and the additive-merge
  principle this slice extends.

Build order inside the slice (HITL pieces are foundational, not
follow-up):

1. `IntegrationConfig` model + migration + RLS policy.
2. `field_provenance` JSON column added to `CustomerMaster` and
   `ItemMaster` via migration; backfill script sets every existing
   field to `source: "extracted"` or `source: "manual"` based on
   whether the row has any linked invoice.
3. `SyncProposal`, `MasterFieldConflict`, `MasterFieldLock` models
   + migrations + RLS.
4. `BaseConnector` interface + `CSVConnector` implementation.
5. `classify_merge` service with the full matrix; named tests for
   every cell.
6. `propose_sync` service that walks fetched records, classifies
   each field, writes a `SyncProposal` and any `MasterFieldConflict`
   rows, emits `integration.sync_proposed`.
7. `apply_sync_proposal` and `revert_sync_proposal` services with
   the 14-day window enforcement.
8. `resolve_field_conflict` service.
9. `rematch_pending_invoices` service; wired to fire on apply and
   on revert, not on propose.
10. `sync_connector` Celery task that runs propose-only by default,
    chains into apply only when `auto_apply=True` and conflicts is
    empty.
11. UI: Settings → Integrations page, Sync preview screen,
    Conflicts queue lane, provenance pills + lock icons on
    Customers/Items, "Undo last sync" affordance.
12. Other connectors in order: SQLAccounting, AutoCount, Xero,
    QuickBooks, Shopify, WooCommerce.

Each step ships with tests before the next step starts. Migrations
are reversible. The slice is mergeable in pieces — steps 1–9 are
the backbone and can land before any specific connector beyond CSV.
The HITL UI in step 11 is required before any non-CSV connector
ships, because non-CSV sources can produce conflicts the user has
no surface to resolve without it.
