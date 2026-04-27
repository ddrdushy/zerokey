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

    preferred_language = models.CharField(max_length=10, default="en-MY")
    preferred_timezone = models.CharField(max_length=64, default="Asia/Kuala_Lumpur")

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

    # Certificate state — keys live in S3 (envelope-encrypted) + KMS, not here.
    certificate_uploaded = models.BooleanField(default=False)
    certificate_expiry_date = models.DateField(null=True, blank=True)
    certificate_kms_key_alias = models.CharField(max_length=128, blank=True)

    logo_url = models.URLField(blank=True)
    language_preference = models.CharField(max_length=10, default="en-MY")
    timezone = models.CharField(max_length=64, default="Asia/Kuala_Lumpur")

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
