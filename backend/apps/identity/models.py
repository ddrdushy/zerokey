"""Identity domain models — Users, Organizations, Memberships, Roles, Permissions.

Per DATA_MODEL.md and ARCHITECTURE.md:
  - Organization is the tenant boundary. Its UUID is the ``tenant_id`` referenced
    by every tenant-scoped table's RLS policy.
  - Users authenticate as themselves; their access to an Organization is mediated
    by an OrganizationMembership row carrying the role.
  - Roles are system-defined in v1 (Owner / Admin / Approver / Submitter / Viewer);
    Permissions are fine-grained capability codes attached to Roles.
  - Cross-context model imports are forbidden (CLAUDE.md). Other contexts that
    need to know about identity call ``apps.identity.services``.

Field-level encryption for PII (email, phone, address) is documented in
DATA_MODEL.md and SECURITY.md but is not wired in this Phase 1 slice — the
encryption key management lands when KMS is provisioned in Phase 6. Until then
we store these as plain text in dev.
"""

from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from .managers import UserManager


class TimestampedModel(models.Model):
    """Mixin: ``created_at`` / ``updated_at`` on every domain row."""

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantScopedModel(TimestampedModel):
    """Base class for any row that belongs to exactly one Organization.

    The ``organization`` FK is the column an RLS policy filters on. Subclasses
    do not need to redeclare it. The matching policy is created in the RLS
    migration that runs after the table is created.
    """

    organization = models.ForeignKey(
        "identity.Organization",
        on_delete=models.CASCADE,
        related_name="+",
        db_index=True,
    )

    class Meta:
        abstract = True


class User(AbstractBaseUser, PermissionsMixin):
    """Authenticated person.

    A User may belong to multiple Organizations via OrganizationMemberships
    (e.g. an accountant servicing several SME clients). The User row itself is
    not tenant-scoped — it predates any organization assignment and is reachable
    by the user across all of their memberships.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)

    two_factor_enabled = models.BooleanField(default=False)
    # TOTP secret (encrypted at rest via apps.administration.crypto).
    # Empty until the user enrolls; populated during enrollment but
    # ``two_factor_enabled`` only flips True once the user confirms a
    # code matches.
    totp_secret_encrypted = models.TextField(blank=True, default="")
    # HMAC-SHA-256 hex digests of one-time recovery codes. Plaintext
    # codes are surfaced once at confirm + never re-shown.
    totp_recovery_hashes = models.JSONField(blank=True, default=list)

    preferred_language = models.CharField(max_length=10, default="en-MY")
    preferred_timezone = models.CharField(max_length=64, default="Asia/Kuala_Lumpur")

    # Slice 92 — onboarding checklist dismissal. The dashboard surfaces
    # a "get started" checklist for new owners (cert upload, inbox
    # forward, invite teammates, first upload). Once the user dismisses
    # it they don't see it again, regardless of whether every item was
    # completed. Per-user (not per-org) so a second member of the same
    # org sees their own first-time experience.
    onboarding_dismissed_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    # ZeroKey internal staff (super-admin console access). Logged whenever they
    # touch customer data; see super-admin context in SECURITY.md.
    is_zerokey_staff = models.BooleanField(default=False)

    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "identity_user"
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self) -> str:
        return self.email


class Organization(TimestampedModel):
    """Tenant. Every customer-scoped row in the system links back here.

    The PK doubles as the ``tenant_id`` set on the database session by the
    request middleware so that PostgreSQL Row-Level Security policies filter
    every query.
    """

    class TrialState(models.TextChoices):
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        USED_UP = "used_up", "Used up"

    class SubscriptionState(models.TextChoices):
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        SUSPENDED = "suspended", "Suspended"
        CANCELLED = "cancelled", "Cancelled"

    class ExtractionMode(models.TextChoices):
        # Vision-LLM lane (Claude / Gemini / Ollama-vision) reads the
        # document and structures it directly. Highest accuracy, per-doc
        # cost. Default for new organizations.
        AI_VISION = "ai_vision", "AI extraction"
        # OCR-only lane (pdfplumber → EasyOCR → regex/LayoutLMv3 floor).
        # No per-doc cost; lower accuracy on handwriting / low-quality
        # scans. Best for cost-sensitive customers with clean PDFs.
        OCR_ONLY = "ocr_only", "OCR only"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    legal_name = models.CharField(max_length=255)
    tin = models.CharField(max_length=32, unique=True)
    sst_number = models.CharField(max_length=32, blank=True)

    # PII — plain text in dev, encrypted column in production (Phase 6 swap).
    registered_address = models.TextField(blank=True)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=32, blank=True)

    billing_currency = models.CharField(max_length=3, default="MYR")

    trial_state = models.CharField(
        max_length=16, choices=TrialState.choices, default=TrialState.ACTIVE
    )
    subscription_state = models.CharField(
        max_length=16, choices=SubscriptionState.choices, default=SubscriptionState.TRIALING
    )

    # Certificate state — for production the keys live in S3 (envelope-
    # encrypted) + KMS. For dev today we store an auto-generated
    # self-signed cert + private key inline (encrypted at rest via
    # Slice 55 helpers) so the signing pipeline runs end-to-end without
    # a real LHDN-issued certificate. ``certificate_kind`` distinguishes:
    #   - "self_signed_dev": auto-generated by the platform; fine for
    #     LHDN sandbox + integration testing, NOT valid for production.
    #   - "uploaded": customer uploaded their LHDN-issued cert.
    certificate_uploaded = models.BooleanField(default=False)
    certificate_expiry_date = models.DateField(null=True, blank=True)
    certificate_kms_key_alias = models.CharField(max_length=128, blank=True)
    certificate_kind = models.CharField(max_length=32, blank=True, default="")
    # Inline encrypted blobs. Only populated for self-signed dev certs;
    # production swaps to KMS-stored S3 blobs (alias above).
    certificate_pem = models.TextField(blank=True, default="")
    certificate_private_key_pem_encrypted = models.TextField(blank=True, default="")
    certificate_subject_common_name = models.CharField(max_length=255, blank=True, default="")
    certificate_serial_hex = models.CharField(max_length=64, blank=True, default="")

    logo_url = models.URLField(blank=True)
    language_preference = models.CharField(max_length=10, default="en-MY")
    timezone = models.CharField(max_length=64, default="Asia/Kuala_Lumpur")

    # Per-tenant inbox token (Slice 64) — the slug embedded in the
    # magic email-forward address ``invoices+<token>@inbox.zerokey…``.
    # Generated on first email-forward request; rotatable from
    # Settings (rotation invalidates the old token immediately).
    # 16-char URL-safe slug; unique per organization.
    inbox_token = models.CharField(max_length=32, blank=True, default="", db_index=True)

    # Per-tenant approval workflow (Slice 87). Tier-gated at the
    # service layer (Growth+ for ``always``, Scale+ for
    # ``threshold``). Default is ``none`` — single-step submit
    # (the user who creates an invoice is also the one who
    # submits it). Mirrors ``Domain 7 — Workflow and approvals``
    # in PRODUCT_REQUIREMENTS.md.
    class ApprovalPolicy(models.TextChoices):
        NONE = "none", "No approval"
        ALWAYS = "always", "Always requires approval"
        THRESHOLD = "threshold", "Requires approval over threshold"

    approval_policy = models.CharField(
        max_length=16,
        choices=ApprovalPolicy.choices,
        default=ApprovalPolicy.NONE,
    )
    # MYR amount above which approval is required when policy = threshold.
    # Invoices in foreign currencies use grand_total directly; FX
    # normalisation is a future tightening.
    approval_threshold_amount = models.DecimalField(
        max_digits=19, decimal_places=2, null=True, blank=True
    )

    # Per-tenant WhatsApp Business phone-number id (Slice 82). This is
    # Meta Cloud API's ``phone_number_id`` (the integer-as-string id
    # under ``entry[].changes[].value.metadata.phone_number_id`` on
    # the inbound webhook). Super-admin assigns this when onboarding
    # a customer to the WhatsApp ingestion channel — it routes
    # incoming media messages on that number to this org. Empty
    # string means WhatsApp ingestion is not configured for the org.
    whatsapp_phone_number_id = models.CharField(
        max_length=64, blank=True, default="", db_index=True
    )

    # Per-tenant extraction lane (Slice 54). Default is the AI lane —
    # accuracy first, customer can opt down to the cost-saver. The
    # extraction pipeline reads this at run_extraction() and branches
    # before vision escalation + structurer selection.
    extraction_mode = models.CharField(
        max_length=16,
        choices=ExtractionMode.choices,
        default=ExtractionMode.AI_VISION,
    )

    class Meta:
        db_table = "identity_organization"
        ordering = ["legal_name"]

    def __str__(self) -> str:
        return self.legal_name


class Role(TimestampedModel):
    """System-defined role. Phase 1 ships the five v1 roles as seed data."""

    class SystemRole(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        APPROVER = "approver", "Approver"
        SUBMITTER = "submitter", "Submitter"
        VIEWER = "viewer", "Viewer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=32, unique=True)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=True)

    permissions = models.ManyToManyField("identity.Permission", related_name="roles", blank=True)

    class Meta:
        db_table = "identity_role"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Permission(TimestampedModel):
    """Fine-grained capability code. Examples: ``invoice.create``, ``audit.export``."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "identity_permission"
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class OrganizationMembership(TenantScopedModel):
    """User ↔ Organization link with a role.

    Tenant-scoped (via the inherited ``organization`` FK) — RLS filters
    rows so that a user querying their memberships from inside a tenant
    context sees only the membership rows of that organization.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("identity.User", on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey("identity.Role", on_delete=models.PROTECT, related_name="+")
    invited_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    is_active = models.BooleanField(default=True)
    joined_date = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "identity_membership"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization"],
                name="uniq_user_per_organization",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "user"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} @ {self.organization.legal_name} ({self.role.name})"


class OrganizationIntegration(TenantScopedModel):
    """Per-tenant external-integration credentials (Slice 57).

    One row per ``(organization, integration_key)``. Holds two credential
    blobs (sandbox + production), a cursor saying which one is currently
    active, and the last-test outcomes per environment.

    Why two slots and an active-environment toggle rather than one set
    that gets overwritten:

      - LHDN MyInvois has separate sandbox + production endpoints + each
        gets its own client_id / client_secret. Operators want to keep
        sandbox creds wired up after going live so they can A/B test
        against the sandbox without rotating keys.
      - The toggle is a clean "go-live" gesture: one click flips the
        org from sandbox to production with a single audited change.

    Credential values are encrypted at rest via
    ``apps.administration.crypto`` (Slice 55). The schema registry in
    ``apps.identity.integrations`` declares which keys are credentials
    (kind="credential") so the read surface returns presence-only
    booleans for those, plaintext for non-secret config (URLs, IDs).
    """

    class Environment(models.TextChoices):
        SANDBOX = "sandbox", "Sandbox / Dev"
        PRODUCTION = "production", "Production"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Stable identifier matching a key in the INTEGRATION_SCHEMAS
    # registry. Today: "lhdn_myinvois". One row per integration per
    # tenant — the unique constraint enforces that.
    integration_key = models.CharField(max_length=64)

    # Per-environment credential JSON blobs. Strings are encrypted at
    # rest; non-string values (timeouts, booleans) pass through plain.
    sandbox_credentials = models.JSONField(default=dict, blank=True)
    production_credentials = models.JSONField(default=dict, blank=True)

    active_environment = models.CharField(
        max_length=16,
        choices=Environment.choices,
        default=Environment.SANDBOX,
    )

    # Last-test outcome per environment. Surfaced in the UI as
    # "Last tested 5 min ago — succeeded" / "Failed: invalid_grant".
    last_test_sandbox_at = models.DateTimeField(null=True, blank=True)
    last_test_sandbox_ok = models.BooleanField(null=True, blank=True)
    last_test_sandbox_detail = models.CharField(max_length=512, blank=True)

    last_test_production_at = models.DateTimeField(null=True, blank=True)
    last_test_production_ok = models.BooleanField(null=True, blank=True)
    last_test_production_detail = models.CharField(max_length=512, blank=True)

    created_by_user_id = models.UUIDField(null=True, blank=True)
    updated_by_user_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "identity_organization_integration"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "integration_key"],
                name="uniq_org_integration_key",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "integration_key"]),
        ]

    def __str__(self) -> str:
        return f"{self.integration_key}@{self.organization_id} ({self.active_environment})"


class MembershipInvitation(TenantScopedModel):
    """Pending invite for a future OrganizationMembership (Slice 56).

    The owner / admin sends an invite to an email address; the recipient
    clicks the link, signs in (or signs up if they're new), and the
    accept handler creates the OrganizationMembership row. Until then
    this row tracks the pending state — visible in Settings → Members
    so admins can see open invites + revoke if needed.

    Token security:
      - Plaintext token shown once at create time (in the email link).
      - Only the SHA-256 ``token_hash`` persists. Same write-only
        contract as APIKey + WebhookEndpoint.
      - 32-byte random; URL-safe base64.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    email = models.EmailField()
    role = models.ForeignKey("identity.Role", on_delete=models.PROTECT, related_name="+")
    invited_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    # SHA-256 of the plaintext token. The plaintext is embedded in the
    # invite-link URL the user clicks; we never persist it.
    token_hash = models.CharField(max_length=128, db_index=True)

    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by_user_id = models.UUIDField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by_user_id = models.UUIDField(null=True, blank=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    class Meta:
        db_table = "identity_membership_invitation"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["email", "status"]),
        ]

    def __str__(self) -> str:
        return f"Invite {self.email} → {self.organization_id} ({self.status})"


class NotificationPreference(TenantScopedModel):
    """Per-user, per-tenant notification preferences.

    Controls which events the user wants to be notified about, and on
    which channels. Tenant-scoped because preferences may differ when
    one user belongs to multiple orgs (e.g. they're an owner at Acme
    so they get inbox alerts, but a viewer at Beta so they don't).
    Surfaced from Settings → Notifications.

    Per-event toggles use a JSONField rather than a column-per-event
    so adding a new event type doesn't require a migration. The list
    of recognised event keys lives in code (``EVENT_KEYS`` in the
    services module) — anything outside that allowlist on save is
    rejected.

    The Slice 28 in-app bell already aggregates state without a
    Notification table — this row stores the *preferences* layer the
    bell + the future email/push channels read.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        "identity.User",
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )

    # Per-event channel preferences:
    #   {"<event_key>": {"in_app": bool, "email": bool}}
    # Empty dict = "use the platform defaults" (everything on).
    preferences = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "identity_notification_preference"
        ordering = ["organization", "user"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization"],
                name="uniq_notif_pref_per_user_org",
            ),
        ]

    def __str__(self) -> str:
        return f"NotifPrefs({self.user_id} @ {self.organization_id})"


class APIKey(TenantScopedModel):
    """A long-lived bearer credential scoped to one organization.

    Per SECURITY.md "API key authentication" + DATA_MODEL.md the
    platform exposes an HTTP API for programmatic access. Customers
    create keys from Settings → API keys; the plaintext is shown
    ONCE at creation and never persisted.

    Storage: only ``key_hash`` (SHA-256 of the plaintext) is stored.
    Auth lookups go by ``key_prefix`` (first 8 chars of the
    plaintext) then verify the hash. The prefix is what the UI shows
    so the customer can identify which key is which without ever
    seeing the plaintext again.

    Revocation: deactivation flips ``is_active=False`` rather than
    deleting, so audit-log queries by ``actor_id`` (the APIKey id)
    continue to resolve. ``revoked_at`` records when.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Customer-chosen short label so the UI lists "ci-pipeline" +
    # "zapier" rather than two opaque UUIDs. Not unique.
    label = models.CharField(max_length=64)

    # First 12 chars of the plaintext, e.g. "zk_live_AbCd". Indexed
    # because auth lookup is by prefix → hash compare. Not a
    # credential on its own; the full plaintext is required for auth.
    key_prefix = models.CharField(max_length=16, db_index=True)

    # SHA-256 hex of the full plaintext. 64 chars. Plaintext never
    # leaves this row in serialised form.
    key_hash = models.CharField(max_length=128)

    # Audit + customer UI "created by" column. Soft FK by uuid — a
    # deactivated user's keys aren't cascade-deleted; revoke them.
    created_by_user_id = models.UUIDField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by_user_id = models.UUIDField(null=True, blank=True)

    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "identity_api_key"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["key_prefix"]),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.key_prefix}…)"
