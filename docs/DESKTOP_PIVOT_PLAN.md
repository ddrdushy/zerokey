# DESKTOP PIVOT PLAN — ZeroKey moves to a desktop application

> The plan for the next major architectural change: ZeroKey stops being a
> multi-tenant SaaS that hosts customer invoice data, and becomes a
> **desktop application** that the customer installs on their own machine.
> Invoice data never leaves the customer's PC. Our cloud shrinks to two
> jobs: **issuing and validating licenses** and **(optionally) signing
> invoices as the LHDN intermediary** for customers who pick that mode.
>
> This document is the load-bearing reference for the pivot. Phases are
> meant to be picked up cold by an engineer (or by Claude Code) and
> executed without re-asking the founder for direction. When code diverges
> from this doc, the doc gets updated in the same change.

## Why this is a pivot, not an iteration

The PORTAL_PLAN era shipped ZeroKey as a SaaS: customers signed in to our
cloud, uploaded invoices, and we held everything from raw PDFs to signed
LHDN bytes. That model has two problems for the Malaysian SME audience we
serve:

1. **Trust friction.** SME owners — especially the ones still on
   AutoCount / SQL Account / Sage UBS — are not comfortable putting their
   sales ledger in someone else's cloud. The objection is not
   irrational; it's a real sales-cycle blocker.
2. **Pricing friction.** A subscription is harder to close than a one-time
   software license + annual renewal, which is how every accounting tool
   in this market is sold. Customers expect to *own* the software.

The desktop pivot solves both. Invoice data lives on the customer's
machine. They pay for an annual license per organisation (one license per
LHDN TIN). The cloud sees license keys and (if they opt in) signing
requests — never the raw invoice store.

We keep most of the engineering from the SaaS era: the ingestion
pipeline, the validation rules, the LHDN submission client, the
consolidated-B2C builder, the certificate handling. They move from the
cloud Django service into a Django sidecar bundled inside the Electron
app, talking to a local SQLite database instead of a multi-tenant Postgres.

## Locked architectural decisions

The founder confirmed the following on **2026-05-19**. These are the
load-bearing assumptions; if any one of them changes, this doc is
rewritten before code.

### 1. Electron shell, reuse the React UI, Python sidecar

The desktop app is **Electron**. The existing Next.js / React frontend is
reused — we strip the routes that don't apply on desktop (marketing,
multi-tenant portal) and add a license-activation screen. The Django
backend ships as a **Python sidecar** bundled via PyInstaller; the
Electron main process spawns it at startup and the UI talks to
`http://127.0.0.1:<random-port>`.

Why Electron over Tauri: the Malaysian SME audience is overwhelmingly
Windows, and the install-size delta (≈10 MB Tauri vs ≈120 MB Electron)
does not matter when the alternative is AutoCount's ≈500 MB installer.
Electron's auto-update story (electron-updater) and the team's existing
JS expertise win.

### 2. Both signing modes — customer chooses per-org

We keep `Organization.signing_mode` from PORTAL_PLAN Phase 1.

- **`intermediary` mode**: the desktop POSTs the unsigned MyInvois JSON
  to our cloud signing API (authenticated by the license bearer token).
  The cloud signs with Symprio's intermediary cert and returns the
  signed bytes. The cloud does **not** retain the payload after signing.
  The desktop then submits the signed document to LHDN directly.
- **`self_signed` mode**: the customer uploaded their LHDN cert. The
  desktop signs locally; the cert blob lives in the OS keychain
  (Windows DPAPI / macOS Keychain / Linux libsecret), never on disk in
  the clear.

A small business that wants zero LHDN paperwork picks intermediary. A
larger business that already has its own LHDN cert and a "no third-party
signing" policy picks self_signed. Per-org toggle stays.

### 3. Local-only invoice data, cloud only for licensing (+ optional signing)

Invoice records, line items, ingestion jobs, audit chain — all in a local
**SQLite** database in the user's app data directory. Encrypted at rest
via SQLCipher.

The cloud has **no** record of any invoice. The cloud has:

- **Customers** (the legal entity that bought a license)
- **Licenses** (one per org / LHDN TIN, with plan + expiry + status)
- **License heartbeats** (validation pings, retained for billing /
  fraud detection only)
- **Signing requests** (transient — payload signed and discarded, only
  the audit metadata kept: license_id, document_hash, signed_at)
- **Super admin / platform admin** (the existing back office)

The accountant-portal we built in PORTAL_PLAN Phase 4 **does not** ship
in the desktop v1. The accountant either installs the desktop app on
each client's machine (or remote-desktops in). We may add a "remote
accountant access" feature in v2 — out of scope here.

### 4. Per-org annual license, 30-day offline grace, read-only after

One license = one organisation (one LHDN TIN). Issued by the cloud on
purchase; delivered as a license key + signed entitlement.

- **At install**: the user enters the license key. Desktop calls
  `POST /licenses/validate`, gets back a signed entitlement blob valid
  for 30 days. Cached locally.
- **Daily**: the Electron main process sends a heartbeat. The
  entitlement refreshes (sliding 30-day window). If the heartbeat fails
  (no internet, server down), the cached entitlement keeps the app
  fully functional until its 30-day expiry.
- **After expiry**: the app drops to **read-only** mode — the user can
  open and view existing invoices, but cannot ingest new ones, sign, or
  submit. A persistent banner prompts to renew.
- **Revoked license**: heartbeat returns `status: revoked`; app
  immediately drops to read-only on the next heartbeat, regardless of
  cached entitlement.

The entitlement is signed with an Ed25519 keypair held by the licensing
service. The desktop ships the public key embedded in the binary,
verifying every entitlement before trusting it.

## What ships, what's archived, what's deleted

### Ships on the desktop

- Invoice ingestion (PDF, image, Excel, manual entry)
- All CSV connectors (SQL Account, AutoCount, Sage UBS — both reference
  data and document pulls)
- Extraction, validation, mapping
- LHDN submission, polling, cancellation
- CN / DN / RN issuance
- Monthly consolidation view (per-org, since each install hosts the
  org's data)
- Consolidated B2C builder
- Auto-submit toggle and confidence-threshold gate
- Per-org signing-mode toggle (intermediary / self_signed)
- Audit log (local chain, verified on read)
- Settings, certificate upload (self_signed mode)

### Stays on the cloud (web)

- Marketing site (`zerokey.symprio.com`)
- Super admin / platform admin (`/admin`)
- **New**: licensing service (`/api/v1/licenses/*`)
- **New**: intermediary signing service (`/api/v1/sign/*`) — gated by
  org's signing_mode + valid license
- **New**: desktop download portal (license-gated signed S3 URLs)
- Customer self-service: view your licenses, regenerate license key,
  download latest desktop installer

### Archived (not deleted)

- The SaaS-era tenant portal (`/dashboard/*`), accountant portal
  (`/portal/*`) and their routes. Keep the source for reference and in
  case we revive a hosted offering; mark deprecated and remove from
  marketing nav.

### Deleted from cloud (moved to desktop)

- Invoice / IngestionJob / ParseResult / ValidationResult / Approval
  models and their RLS policies
- Submission, parse, validate, connectors apps (move, don't copy — the
  cloud no longer needs them)
- Tenant Celery beat jobs (auto-submit scheduler, etc.)

## Phases

Six phases. Each ends with the desktop binary closer to shippable. Each
phase has its own acceptance criteria and ships independently.

### Phase 1 — Carve the cloud down to licensing + super admin

**Scope.** Slim the cloud Django service. Move tenant-facing apps out of
the cloud's URL tree (don't delete the source yet; we'll re-home it in
Phase 3). Add the licensing app.

- New Django app: `apps/licensing/`
  - `License` model: `id`, `customer_id` (FK to a slim Customer model
    representing the buyer), `organization_legal_name`,
    `organization_tin`, `plan` (`STARTER`/`PROFESSIONAL`/`ENTERPRISE`),
    `key` (random URL-safe 32 chars, displayed once), `key_hash` (the
    only thing stored long-term), `status`
    (`ACTIVE`/`SUSPENDED`/`REVOKED`/`EXPIRED`), `issued_at`,
    `expires_at`, `last_heartbeat_at`, `last_heartbeat_ip`.
  - `LicenseHeartbeat` model: append-only log of validations
    (`license_id`, `at`, `ip`, `desktop_version`, `entitlement_id`).
  - Endpoints: `POST /api/v1/licenses/validate` (license key + machine
    fingerprint → signed entitlement); `POST /api/v1/licenses/heartbeat`
    (entitlement bearer → refreshed entitlement); `POST /api/v1/licenses/revoke`
    (super admin only).
  - Entitlement format: signed JWT-like blob (Ed25519, JWS compact),
    claims: `license_id`, `org_tin`, `plan`, `features` (slugs),
    `signing_mode_allowed` (which modes this plan permits),
    `issued_at`, `expires_at` (30 days out).
- Super admin extensions:
  - License Issuer page: pick a customer, fill org details + plan,
    create license. Show the key **once** (it's hashed after).
  - License Inventory: searchable table of all licenses, status
    filters, revoke action (uses the modal pattern).
- Mark the SaaS dashboard / portal routes as deprecated:
  hide from the marketing nav, leave the source in place. Add a banner
  to `/dashboard` and `/portal` saying "ZeroKey is now a desktop app —
  download the installer".

**Acceptance.**
- Super admin can create a license, see the key once, copy it.
- `POST /licenses/validate` with that key returns a verifiable signed
  entitlement.
- Heartbeat refreshes the entitlement and bumps `last_heartbeat_at`.
- Revoke flips status; next heartbeat returns `revoked`.
- The cloud's existing tenant-facing endpoints still work (we have not
  removed them yet; that happens in Phase 3 once the desktop owns them).

### Phase 2 — Desktop scaffolding (Electron + Python sidecar)

**Scope.** Build the empty Electron shell and prove the sidecar pattern.

- New top-level directory: `desktop/`
  - `desktop/electron/` — Electron main + preload, packaged with
    electron-builder. Targets: Windows NSIS installer first, Mac DMG
    second (defer Mac to v1.1 if it slows us down).
  - `desktop/renderer/` — the React UI. Start by importing the existing
    `frontend/src/components/*` packages and trimming the routes.
    Activation screen: a single card asking for the license key, calls
    cloud `/licenses/validate`, stores entitlement in OS keychain
    (keytar), then routes to the main app.
  - `desktop/sidecar/` — the Python sidecar. PyInstaller-bundled Django
    project that subsets the existing backend (apps to be moved in
    Phase 3). For now: serves a `/healthz` and a `/version` endpoint so
    we can prove the IPC works.
- Electron main process responsibilities:
  - On startup: find a free localhost port, spawn the sidecar binary
    with `--port <p>`, wait for `/healthz`, then load the renderer
    pointing at `http://127.0.0.1:<p>`.
  - On shutdown: send SIGTERM to the sidecar.
  - Daily heartbeat: cron-like timer that calls cloud
    `/licenses/heartbeat` with the cached entitlement; refreshes
    keychain on success; logs failures.

**Acceptance.**
- `npm run dev` in `desktop/` opens an Electron window with the
  activation screen.
- Entering a valid license key (issued in Phase 1) activates the app
  and routes to a placeholder "Hello, [org]" screen.
- Closing the window stops the sidecar cleanly (no orphan Python
  process).
- A Windows installer builds via `npm run build:win` and installs on a
  clean Win11 VM.

### Phase 3 — Move tenant features into the desktop sidecar

**Scope.** Move ingestion / submission / connectors / etc. from cloud
Django into `desktop/sidecar/`. Adapt for SQLite and single-tenant.

- Move (don't copy) these apps from `backend/apps/` to
  `desktop/sidecar/apps/`: `submission`, `parse`, `validate`, `connectors`,
  `ingestion`, `notifications`, the parts of `identity` that handle
  organizations + members (drop the multi-tenant signup / SSO bits).
- Database adaptations:
  - SQLite backend, SQLCipher encryption. Encryption key derived from
    a per-install random secret stored in the OS keychain.
  - Drop the RLS policies — single-tenant per install, RLS is dead
    code. `tenant_context` becomes a no-op shim that just sets a
    thread-local for code paths that still reference it.
  - Migrations: bundled in the sidecar, run on first start.
- Cloud signing client (for `signing_mode='intermediary'`):
  - `apps/submission/certificates.py` keeps `ensure_certificate()` but
    the intermediary branch calls cloud `/api/v1/sign/document` with
    the unsigned payload + entitlement bearer. Response is the signed
    bytes; LoadedCertificate is constructed with those bytes and a
    "remote" marker. We never see the intermediary private key on the
    desktop.
  - Add `IntermediarySigningClient` with retry + offline detection:
    if offline and signing_mode is intermediary, queue the doc as
    "waiting_to_sign" and surface a banner.
- Certificate handling for `signing_mode='self_signed'`:
  - Customer uploads their LHDN-issued cert in the desktop Settings
    UI. The cert blob is encrypted with an OS-keychain-held key and
    stored in the SQLite DB (encrypted-at-rest twice — defence in
    depth).
  - No KMS, no S3 — those were cloud constructs.
- LHDN submission: continues to happen from the desktop. The desktop
  has internet access for licensing anyway; the LHDN call goes
  desktop → MyInvois API directly.

**Acceptance.**
- A fresh desktop install can ingest a PDF, extract, validate, submit
  to LHDN sandbox (with a sandbox license), poll, and show the UUID.
- Both signing modes work end-to-end against the sandbox.
- The cloud Django service no longer has `submission`, `parse`,
  `validate`, `connectors`, `ingestion` apps in `INSTALLED_APPS`.
- The monthly consolidation view and consolidated-B2C builder work
  on the desktop, scoped to the one org this install owns.

### Phase 4 — License enforcement, offline grace, read-only mode

**Scope.** Wire the licensing checks into the desktop's feature gates.

- Entitlement verification on every backend call:
  - DRF middleware in the sidecar that loads the cached entitlement on
    startup, verifies its Ed25519 signature, and pins it to the
    request.
  - Endpoints that mutate state (`POST` to submission, signing, etc.)
    require `entitlement.status == 'active'`; otherwise 403 with a
    clear error.
  - Read endpoints work even with an expired entitlement → that's the
    read-only mode.
- Heartbeat scheduler in Electron main:
  - Run on app start, then every 24 h. On failure, retry with jittered
    backoff (1 m, 5 m, 30 m, then daily). Surface the last-success
    timestamp in a Settings → License panel.
- Offline-grace UI:
  - Banner at the top of the app when the entitlement is more than 7
    days from expiry and the last heartbeat failed.
  - Hard banner + read-only mode once expiry passes.
  - Renewal flow: the banner links to a deep URL on the cloud
    self-service page; after renewal, the next heartbeat unlocks the
    app automatically.
- Revocation:
  - The heartbeat response `{status: 'revoked', reason: '...'}`
    immediately drops the app to read-only and shows the reason in a
    modal. Cached entitlement is wiped.

**Acceptance.**
- Disconnecting the machine for 25 days keeps the app fully functional.
- Day 31 the app is read-only with a banner.
- Revoking the license from super admin and waiting one heartbeat
  cycle drops the live desktop session to read-only with the reason
  surfaced.
- Reading existing invoices still works in read-only mode; submitting
  / signing / ingesting is blocked.

### Phase 5 — Installer, code signing, auto-update

**Scope.** Make the desktop shippable.

- electron-builder config:
  - Windows: NSIS, EV code-signing cert (procurement is a real-world
    blocker — note in `docs/OPERATIONS.md`).
  - Mac: DMG, Apple developer cert + notarisation. Defer if blocked.
- Auto-update feed:
  - Releases published to S3 + CloudFront under
    `releases.zerokey.symprio.com/{platform}/{channel}/latest.yml`.
  - electron-updater pointed at that feed. Two channels: `stable` and
    `beta`.
  - Update download is itself license-gated: the updater fetches a
    short-lived signed S3 URL from the cloud (`/api/v1/desktop/release`)
    presenting its entitlement.
- Download portal on the cloud:
  - `/download` page on the marketing site: gated by login. Shows
    the latest installer URL (signed, 10 min validity) for each
    platform if the customer has at least one active license.
  - Unauthenticated visitors see "Buy a license" CTA.
- First-run experience:
  - Installer drops desktop shortcut + Start Menu entry.
  - First launch: activation screen → license key → success → empty
    state with "Import your first invoice" CTA.

**Acceptance.**
- Signed `ZeroKey-Setup-x.y.z.exe` installs on a clean Win11 VM
  without SmartScreen warnings (after the EV cert reputation builds).
- App detects a newer release, downloads it (license-gated), and
  applies on next restart.
- The cloud `/download` page only shows installers to authenticated
  customers with active licenses.

### Phase 6 — Cloud super admin extensions for licensing + telemetry

**Scope.** Finish the back-office tools so we can actually run the
licensing business.

- License Issuer (Phase 1 had the bare endpoint; this phase ships the
  full UI):
  - Customer picker (search by company name / contact email).
  - Plan picker, expiry date, TIN, organisation name.
  - "Issue" creates the license, generates the key, shows it once with
    a copy button + a `mailto:` link pre-populated with the buyer's
    email.
- License Inventory:
  - Searchable, filterable (status, plan, expiry window).
  - Per-row actions: view heartbeat history, revoke (modal with
    reason), regenerate key (revokes old, issues new under same id).
- Renewal automation:
  - 30 / 7 / 1 days before expiry: email the customer contact with a
    renewal link.
  - On renewal payment, license expiry is bumped 365 days.
- Telemetry (optional, opt-in per customer):
  - Desktop posts daily counts (invoices ingested / submitted /
    failed) to `/api/v1/telemetry`. Counts only — no invoice contents.
  - Super admin sees per-customer health for support
    triage.

**Acceptance.**
- Founder can issue, revoke, regenerate, and renew licenses from the
  super admin without touching the DB.
- Renewal emails fire on schedule.
- Telemetry (when opt-in) shows up in the customer's super admin row
  within 24 h.

## Out of scope (defer to v2)

- **Cross-org accountant portal.** The desktop version of this is
  fundamentally different (remote access, not centralised data) and
  needs its own design pass.
- **Multi-user on one install.** v1 is single OS user per install. If
  bookkeeper + owner both want access, they install on two machines
  and each owns their own license (or share via Windows Fast User
  Switching, which works but isn't supported).
- **Mac and Linux installers.** Windows-first. Mac if there's a paying
  customer asking; Linux when somebody asks twice.
- **Air-gapped activation.** All current customers have internet.
- **Real-time ERP polling.** Phase 2 of PORTAL_PLAN landed CSV import;
  live polling needs an on-prem agent and is a separate workstream.
- **Migration tooling from SaaS dashboard.** We have no production SaaS
  customers; nothing to migrate.

## Cross-cutting concerns

### License key security

- The full license key is shown **once** at issuance, then only the
  SHA-256 hash is stored. If the customer loses it, super admin
  regenerates (revokes old, issues new under the same license id).
- Entitlements are signed with Ed25519. Private key lives in the
  cloud-side KMS (the existing KMS we use for cert encryption) under a
  dedicated key alias `zk/licensing/ed25519`.
- The desktop ships the public key embedded in the binary. The public
  key is also published at `licensing.zerokey.symprio.com/public-key`
  for transparency.

### Machine fingerprint

The validate call includes a stable machine fingerprint (hash of MAC +
CPU id + Windows SID, salted by the license id). We bind one
entitlement to one fingerprint at activation time. Moving the install
to a new machine requires a "transfer" action in super admin (or
self-serve once per 90 days from the cloud account page) — protects
against casual license sharing without hostile-DRM theatre.

### Audit log on desktop

The chained audit log moves with the rest of the submission code. It
stays local. Per-event verification happens on read. We do **not** sync
the audit log to the cloud — the customer's invoice data privacy
guarantee depends on this.

### Backups

The desktop ships an export action that produces an encrypted backup
(SQLCipher dump) the user saves wherever they want — local NAS, S3,
external drive. Restore on a new install requires the same license key
+ the backup file. Cloud is not in the backup path.

### Updates and signing key rotation

The Ed25519 public key embedded in the desktop binary is **versioned**.
The cloud signs entitlements with the latest version; the desktop
accepts any version it knows. Rotation = ship a new desktop release
that knows the new key; once that release is >= 99% of installs, the
cloud rotates and old entitlements re-sign on next heartbeat.

## How this doc relates to the others

- **PORTAL_PLAN.md** is the predecessor. The signing-mode toggle, the
  CSV connectors, the auto-submit gate, the consolidated-B2C builder
  all carry forward. The accountant portal does not.
- **ARCHITECTURE.md** needs a top-level update once Phase 3 lands:
  the cloud no longer owns invoice data.
- **SECURITY.md** needs updates for: SQLCipher on desktop, OS keychain
  use, Ed25519 entitlements, signing-mode trust boundaries.
- **OPERATIONS.md** gains: EV cert procurement, release pipeline, the
  S3 release feed, the auto-update channel management.
- **BUSINESS_MODEL.md** is the biggest rewrite — subscription → annual
  license. That happens alongside Phase 1.

## Status

- **Phase 1**: in progress.
- Phases 2–6: pending.

Each phase is marked SHIPPED in this doc as it lands, with the commit
SHA next to it. Drift starts when nobody bothers; don't drift.
