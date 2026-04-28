"""Tests for the billing surface (Slice 48)."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.billing.models import Plan, Subscription, UsageEvent
from apps.billing.services import (
    bootstrap_trial_subscription,
    current_period_usage,
    get_active_subscription,
    record_usage_event,
)
from apps.identity.models import Organization, OrganizationMembership, Role, User


@pytest.fixture
def seeded_roles(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def seeded_plans(db) -> None:
    """Seed migration is data-driven; tests reseed via the same data."""
    plans = [
        ("trial", 1, "Trial", "trial", 0, 50),
        ("solo", 1, "Solo", "solo", 4900, 100),
        ("team", 1, "Team", "team", 14900, 500),
    ]
    for slug, version, name, tier, price, included in plans:
        Plan.objects.update_or_create(
            slug=slug,
            version=version,
            defaults={
                "name": name,
                "tier": tier,
                "monthly_price_cents": price,
                "annual_price_cents": price * 10,
                "billing_currency": "MYR",
                "included_invoices_per_month": included,
                "is_active": True,
                "is_public": slug != "trial",
            },
        )


@pytest.fixture
def org_user(seeded_roles, seeded_plans) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme", tin="C10000000001", contact_email="o@a"
    )
    user = User.objects.create_user(email="o@a.test", password="x")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


def _client(org_user) -> Client:
    org, user = org_user
    client = Client()
    client.force_login(user)
    session = client.session
    session["organization_id"] = str(org.id)
    session.save()
    return client


@pytest.mark.django_db
class TestPublicPlans:
    def test_anonymous_can_list_plans(self, seeded_plans) -> None:
        response = Client().get("/api/v1/billing/plans/")
        assert response.status_code == 200
        results = response.json()["results"]
        slugs = {p["slug"] for p in results}
        # "trial" is is_public=False; "solo" + "team" are visible.
        assert "solo" in slugs
        assert "team" in slugs
        assert "trial" not in slugs


@pytest.mark.django_db
class TestBootstrapTrial:
    def test_creates_trial_subscription(self, org_user) -> None:
        org, _ = org_user
        sub = bootstrap_trial_subscription(organization_id=org.id)
        assert sub is not None
        assert sub.status == Subscription.Status.TRIALING
        assert sub.plan.slug == "trial"
        assert sub.trial_started_at is not None
        assert sub.trial_ends_at is not None

    def test_idempotent(self, org_user) -> None:
        org, _ = org_user
        first = bootstrap_trial_subscription(organization_id=org.id)
        second = bootstrap_trial_subscription(organization_id=org.id)
        assert first.id == second.id


@pytest.mark.django_db
class TestBillingOverview:
    def test_unauthenticated_rejected(self) -> None:
        response = Client().get("/api/v1/billing/overview/")
        assert response.status_code in (401, 403)

    def test_authenticated_returns_subscription_and_usage(
        self, org_user
    ) -> None:
        org, _ = org_user
        bootstrap_trial_subscription(organization_id=org.id)
        client = _client(org_user)
        response = client.get("/api/v1/billing/overview/")
        assert response.status_code == 200
        body = response.json()
        assert body["subscription"]["status"] == "trialing"
        assert body["subscription"]["plan"]["slug"] == "trial"
        assert body["usage"]["event_type"] == "invoice_processed"
        assert body["usage"]["count"] == 0
        assert "available_plans" in body

    def test_no_subscription_returns_null_subscription(self, org_user) -> None:
        client = _client(org_user)
        response = client.get("/api/v1/billing/overview/")
        assert response.status_code == 200
        assert response.json()["subscription"] is None


@pytest.mark.django_db
class TestUsageEvents:
    def test_record_event_snapshots_subscription(self, org_user) -> None:
        org, _ = org_user
        bootstrap_trial_subscription(organization_id=org.id)
        event = record_usage_event(
            organization_id=org.id,
            event_type=UsageEvent.EventType.INVOICE_PROCESSED,
            related_entity_type="Invoice",
            related_entity_id="abc-123",
        )
        assert event.plan_slug == "trial"
        assert event.plan_version == 1
        assert event.subscription_id is not None
        assert event.related_entity_id == "abc-123"

    def test_current_period_usage_counts(self, org_user) -> None:
        org, _ = org_user
        bootstrap_trial_subscription(organization_id=org.id)
        for _ in range(3):
            record_usage_event(
                organization_id=org.id,
                event_type=UsageEvent.EventType.INVOICE_PROCESSED,
            )
        usage = current_period_usage(organization_id=org.id)
        assert usage["count"] == 3
        # Trial includes 50; 3 < 50 → no overage.
        assert usage["limit"] == 50
        assert usage["overage_count"] == 0

    def test_overage_count_when_over_limit(
        self, org_user, seeded_plans
    ) -> None:
        org, _ = org_user
        # Move tenant to a 100-included plan and rack up 105 events.
        solo = Plan.objects.get(slug="solo", version=1)
        Subscription.objects.create(
            organization_id=org.id,
            plan=solo,
            status=Subscription.Status.ACTIVE,
        )
        for _ in range(105):
            record_usage_event(
                organization_id=org.id,
                event_type=UsageEvent.EventType.INVOICE_PROCESSED,
            )
        usage = current_period_usage(organization_id=org.id)
        assert usage["count"] == 105
        assert usage["limit"] == 100
        assert usage["overage_count"] == 5


@pytest.mark.django_db
class TestRegistrationBootstrapsTrial:
    def test_register_creates_trial_subscription(
        self, seeded_roles, seeded_plans
    ) -> None:
        from apps.identity.services import register_owner

        result = register_owner(
            email="newuser@test.example",
            password="long-enough-password",
            organization_legal_name="NewCo",
            organization_tin="C99999999999",
            contact_email="newuser@test.example",
        )
        sub = get_active_subscription(organization_id=result.organization.id)
        assert sub is not None
        assert sub["status"] == "trialing"
        assert sub["plan"]["slug"] == "trial"
