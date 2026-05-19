"""Licensing models — License + LicenseHeartbeat.

Per DESKTOP_PIVOT_PLAN.md Phase 1. The cloud's role is reduced to
issuing and validating licenses; the desktop app holds the invoice
data and asks the cloud only "is my license still good?".

Key design choices:

- One License binds to exactly one LHDN TIN (one Malaysian organisation).
  A customer with three companies buys three licenses. The TIN is the
  natural unique key — duplicate-license-per-TIN is rejected at issue
  time.
- The full license key is only ever shown ONCE at issuance. The
  database stores ``key_hash`` (SHA-256 of the key). If the customer
  loses the key, super admin regenerates (which revokes the old key
  and issues a new one under the same License id).
- Machine binding happens at first ``validate``. We store the
  fingerprint hash; subsequent validates from a different fingerprint
  are rejected (the customer must transfer the install via super admin
  or a self-serve once-per-90-days flow we'll wire in Phase 6).
- LicenseHeartbeat is append-only — it's a fraud-detection trail, not
  a transactional log. We don't index it heavily; super admin queries
  it per-license, never globally.

The License is NOT a TenantScopedModel. It belongs to the licensing
context, which is platform-wide (operated by Symprio). RLS doesn't
apply.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.identity.models import TimestampedModel


class License(TimestampedModel):
    """A purchased license bound to one organisation TIN.

    One License = one desktop activation slot, with rights described
    by ``plan``. Status transitions:

      ``ACTIVE`` → ``SUSPENDED`` (payment problem, recoverable)
      ``ACTIVE`` → ``REVOKED``   (operator action, terminal)
      ``ACTIVE`` → ``EXPIRED``   (auto, when ``expires_at`` passes)
      ``SUSPENDED`` → ``ACTIVE`` (payment resolved)
      ``EXPIRED`` → ``ACTIVE``   (renewal — bumps ``expires_at``)

    The desktop sees these as part of its entitlement; ``REVOKED`` and
    ``EXPIRED`` drop the app to read-only on next heartbeat.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"

    class Plan(models.TextChoices):
        STARTER = "starter", "Starter"
        PROFESSIONAL = "professional", "Professional"
        ENTERPRISE = "enterprise", "Enterprise"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Who bought it. Re-used as the contact for renewal emails and the
    # account that can self-serve a fingerprint transfer.
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_licenses",
    )

    # What it covers. legal_name is for the receipt and the License
    # Issuer UI; tin is the load-bearing identifier (LHDN scopes
    # everything by TIN).
    organization_legal_name = models.CharField(max_length=255)
    organization_tin = models.CharField(max_length=64, unique=True, db_index=True)

    plan = models.CharField(max_length=32, choices=Plan.choices, default=Plan.STARTER)

    # SHA-256 hex of the issued key. The plaintext key is shown once
    # by the issuer and never persisted. Lookup is by hash.
    key_hash = models.CharField(max_length=64, unique=True, db_index=True)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )

    issued_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)

    # Machine binding — set on first successful validate. Re-validating
    # from a different fingerprint is rejected with a clear error so
    # the customer can request a transfer.
    bound_fingerprint_hash = models.CharField(max_length=64, blank=True, default="")
    bound_at = models.DateTimeField(null=True, blank=True)

    # Heartbeat bookkeeping — duplicated from LicenseHeartbeat for fast
    # "how long since last seen" queries on the inventory page.
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_ip = models.GenericIPAddressField(null=True, blank=True)
    last_desktop_version = models.CharField(max_length=32, blank=True, default="")

    # Revocation metadata. Reason is operator-facing; the desktop only
    # sees the status flip.
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "licenses"
        ordering = ["-issued_at"]
        indexes = [
            models.Index(fields=["status", "expires_at"]),
            models.Index(fields=["owner_user", "status"]),
        ]

    def __str__(self) -> str:
        return f"License<{self.organization_legal_name} / {self.organization_tin}>"

    @property
    def is_effective(self) -> bool:
        """True if a fresh entitlement should be issued.

        Captures the three "alive" conditions: status must be ACTIVE,
        the calendar window must be open, and (if bound) the next
        validate must come from the bound fingerprint. The fingerprint
        check is enforced in the validate path, not here.
        """
        if self.status != self.Status.ACTIVE:
            return False
        return self.expires_at > timezone.now()


class LicenseHeartbeat(TimestampedModel):
    """Append-only validation log.

    Every ``validate`` and every ``heartbeat`` call writes one row.
    Used by the super admin "License detail" page to debug "is the
    customer's desktop actually phoning home?" and by future fraud
    analysis ("the same key hit us from 14 different IPs in 5
    countries").
    """

    class EventType(models.TextChoices):
        VALIDATE = "validate", "Validate"
        HEARTBEAT = "heartbeat", "Heartbeat"

    class Result(models.TextChoices):
        OK = "ok", "OK"
        FINGERPRINT_MISMATCH = "fingerprint_mismatch", "Fingerprint mismatch"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"
        SUSPENDED = "suspended", "Suspended"
        UNKNOWN_KEY = "unknown_key", "Unknown key"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    license = models.ForeignKey(
        License,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="heartbeats",
    )
    event_type = models.CharField(max_length=16, choices=EventType.choices)
    result = models.CharField(max_length=32, choices=Result.choices)
    at = models.DateTimeField(default=timezone.now, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    desktop_version = models.CharField(max_length=32, blank=True, default="")
    # First-validate sends a fingerprint we record; later heartbeats just
    # echo the entitlement, so this is sometimes empty.
    machine_fingerprint_hash = models.CharField(max_length=64, blank=True, default="")
    # The entitlement id we minted in response (UUID). Lets us correlate
    # a desktop install's stored entitlement back to the issuance event.
    entitlement_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "license_heartbeats"
        ordering = ["-at"]
