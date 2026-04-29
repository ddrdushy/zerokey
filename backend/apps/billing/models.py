"""Billing domain models.

Per DATA_MODEL.md §"Billing domain entities" + BUSINESS_MODEL.md the
platform charges per-tenant subscriptions with optional usage-based
overages. The data model lands first so the rest of the platform (the
customer Settings → Billing tab, the admin tenant detail, the
upcoming Stripe wiring) can read from these tables before the actual
Stripe integration ships.

Plans are platform-wide (every tenant chooses from the same catalog,
seeded by the migration). Subscription / PaymentMethod / UsageEvent
are tenant-scoped under the standard RLS pattern.

This slice is pre-Stripe — the columns the Stripe wiring will need
(``stripe_customer_id``, ``stripe_subscription_id``, etc.) exist now
so future writes don't need a migration. Today they're populated
manually via the admin or stay empty for trial tenants.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

from apps.identity.models import TenantScopedModel, TimestampedModel


class Plan(TimestampedModel):
    """A versioned subscription plan in the platform's catalog.

    Platform-wide (NOT tenant-scoped). The seed migration ships the
    launch plans; future plan changes ship as new rows (versioned by
    ``slug`` + ``version``) so historical Subscriptions still resolve
    to the plan they were on at the time.

    Pricing is per ``billing_currency`` — Malaysian SMEs almost
    always use MYR, but the schema allows USD/SGD for foreign
    customers landing in v2.
    """

    class Tier(models.TextChoices):
        TRIAL = "trial", "Trial"
        SOLO = "solo", "Solo"
        TEAM = "team", "Team"
        GROWTH = "growth", "Growth"
        ENTERPRISE = "enterprise", "Enterprise"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ``slug`` is the operator-readable identifier; ``version`` makes
    # each plan immutable after publish (we ship v1 of "team", then
    # publish v2 alongside it instead of editing v1 in-place).
    slug = models.SlugField(max_length=64)
    version = models.IntegerField(default=1)

    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)

    tier = models.CharField(max_length=16, choices=Tier.choices, db_index=True)

    # Per-cycle price. Stored as integer cents to avoid float arithmetic
    # bugs around currency. Display layer formats; backend never math's
    # on floats.
    monthly_price_cents = models.IntegerField(default=0)
    annual_price_cents = models.IntegerField(default=0)
    billing_currency = models.CharField(max_length=8, default="MYR")

    # Per-cycle limits. Soft caps — overages billed at
    # ``per_overage_cents``. Zero in either column means "no limit".
    included_invoices_per_month = models.IntegerField(default=0)
    per_overage_cents = models.IntegerField(default=0)
    included_users = models.IntegerField(default=0)
    included_api_keys = models.IntegerField(default=0)

    # Feature flags carried as JSON for plan-feature gating
    # ("webhooks: true", "sso: false"). Read-only at runtime; the
    # source of truth is the seed migration + future plan-edit UI.
    features = models.JSONField(default=dict, blank=True)

    # Stripe Price IDs — created in the Stripe dashboard or via
    # API once per plan version. Two IDs per plan (monthly + annual)
    # because Stripe represents recurring intervals as separate
    # Price objects under the same Product. Leave blank for plans
    # that aren't sold via Stripe (e.g. enterprise contracts).
    stripe_price_id_monthly = models.CharField(max_length=128, blank=True)
    stripe_price_id_annual = models.CharField(max_length=128, blank=True)

    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(
        default=True,
        help_text=(
            "Visible on the public pricing page. Internal-only plans "
            "(legacy grandfathered, custom enterprise) set this False."
        ),
    )

    class Meta:
        db_table = "billing_plan"
        ordering = ["tier", "slug", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["slug", "version"],
                name="uniq_plan_slug_version",
            ),
        ]
        indexes = [
            models.Index(fields=["is_active", "is_public"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} (v{self.version})"


class Subscription(TenantScopedModel):
    """One organization's subscription to a plan.

    Distinct from ``Organization.subscription_state`` (which is the
    high-level lifecycle state) — this carries the plan + price +
    Stripe identifiers + cycle dates. ``Organization.subscription_state``
    is denormalised from ``Subscription.status`` for UI / list-page
    speed.

    One row per (organization, status=active) — historical rows stay
    around with status=cancelled / replaced for the audit story.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        TRIALING = "trialing", "Trialing"
        PAST_DUE = "past_due", "Past due"
        CANCELLED = "cancelled", "Cancelled"
        # When a customer upgrades/downgrades we mark the old row
        # ``replaced`` rather than deleting; the audit log can
        # reconstruct what they were on at any historical date.
        REPLACED = "replaced", "Replaced"

    class BillingCycle(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        ANNUAL = "annual", "Annual"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT, related_name="subscriptions"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.TRIALING, db_index=True
    )
    billing_cycle = models.CharField(
        max_length=16, choices=BillingCycle.choices, default=BillingCycle.MONTHLY
    )

    # Cycle dates. ``current_period_end`` drives "your subscription
    # renews on…" copy in the UI and the cron-checked downgrade if a
    # payment fails.
    current_period_start = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField(null=True, blank=True)

    # Trial window. Set on creation; cleared when the trial converts
    # to a paid plan.
    trial_started_at = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)

    # Cancellation window. Customers can cancel "at period end" —
    # ``cancel_at_period_end`` flags that intent without ending the
    # subscription immediately. ``cancelled_at`` is the actual end.
    cancel_at_period_end = models.BooleanField(default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    # Stripe identifiers. Populated by the future Stripe wiring; today
    # blank for tenants on trial.
    stripe_customer_id = models.CharField(max_length=64, blank=True, db_index=True)
    stripe_subscription_id = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        db_table = "billing_subscription"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["status", "current_period_end"]),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id} → {self.plan.name} ({self.status})"


class PaymentMethod(TenantScopedModel):
    """A saved payment method (Stripe card / FPX bank).

    Storage rule: only the last-four + brand + Stripe payment method
    id is persisted. The PAN never leaves Stripe; we hold a token + a
    display string. Per SECURITY.md PCI scope is minimised by design.
    """

    class Kind(models.TextChoices):
        CARD = "card", "Card"
        FPX = "fpx", "FPX (Online banking)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    kind = models.CharField(max_length=16, choices=Kind.choices)
    is_default = models.BooleanField(default=False)

    # Display fields — what the customer sees in the UI. PAN is NEVER
    # stored even partially beyond last_four.
    brand = models.CharField(max_length=32, blank=True)  # "Visa", "Maybank2u"
    last_four = models.CharField(max_length=4, blank=True)
    exp_month = models.IntegerField(null=True, blank=True)
    exp_year = models.IntegerField(null=True, blank=True)

    # Stripe identifier (pm_xxx for cards, ba_xxx for bank accounts).
    # Required for charges; the Stripe wiring populates it.
    stripe_payment_method_id = models.CharField(
        max_length=64, blank=True, db_index=True
    )

    is_active = models.BooleanField(default=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "billing_payment_method"
        ordering = ["-is_default", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.kind} {self.brand} •••• {self.last_four}"
            if self.last_four
            else f"{self.kind} (unconfigured)"
        )


class UsageEvent(TenantScopedModel):
    """One usage event that may roll up into the next bill.

    Today the only metered event type is ``invoice_processed`` (counts
    per ``Subscription.current_period_*``). Future event types (e.g.
    ``api_call``, ``vision_engine_call``) drop in by adding to
    ``EventType``.

    Append-only at the application layer (no UPDATE / DELETE in
    services). The aggregator reads ranges by
    ``(organization, event_type, occurred_at)``.
    """

    class EventType(models.TextChoices):
        INVOICE_PROCESSED = "invoice_processed", "Invoice processed"
        API_CALL = "api_call", "API call"
        VISION_ENGINE_CALL = "vision_engine_call", "Vision engine call"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    event_type = models.CharField(
        max_length=32, choices=EventType.choices, db_index=True
    )
    quantity = models.IntegerField(default=1)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    # Soft FK. The thing the event is about (e.g. an Invoice id for
    # invoice_processed). String so cross-context refs stay decoupled.
    related_entity_type = models.CharField(max_length=64, blank=True)
    related_entity_id = models.CharField(max_length=128, blank=True)

    # Snapshot of plan + cycle at the moment the event happened — so
    # a future plan change doesn't retroactively re-bill.
    subscription_id = models.UUIDField(null=True, blank=True, db_index=True)
    plan_slug = models.CharField(max_length=64, blank=True)
    plan_version = models.IntegerField(default=0)

    class Meta:
        db_table = "billing_usage_event"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["organization", "event_type", "-occurred_at"]),
            models.Index(fields=["subscription_id", "-occurred_at"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.event_type} x{self.quantity} on {self.organization_id} "
            f"@ {self.occurred_at.isoformat()}"
        )
