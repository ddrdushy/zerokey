"""Tests for Stripe checkout + webhook handling (Slice 63)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from apps.administration.services import upsert_system_setting
from apps.billing.models import Plan, Subscription
from apps.billing import checkout, stripe_client
from apps.identity.models import (
    Organization,
    OrganizationMembership,
    Role,
    User,
)


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def stripe_configured(seeded) -> None:
    upsert_system_setting(
        namespace="stripe",
        values={
            "secret_key": "sk_test_12345",
            "publishable_key": "pk_test_12345",
            "webhook_secret": "whsec_test_secret",
            "default_currency": "MYR",
        },
    )


@pytest.fixture
def org_owner(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme Sdn Bhd",
        tin="C1234567890",
        contact_email="dushy@acme.example",
    )
    user = User.objects.create_user(
        email="dushy@acme.example", password="long-enough-password"
    )
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


@pytest.fixture
def plan(seeded) -> Plan:
    """Use a unique slug not in the seed migration so test runs don't collide."""
    return Plan.objects.create(
        slug="test-stripe-fixture",
        version=1,
        name="Test Stripe Plan",
        tier=Plan.Tier.TEAM,
        monthly_price_cents=39000,
        annual_price_cents=390000,
        billing_currency="MYR",
        stripe_price_id_monthly="price_team_monthly_test",
        stripe_price_id_annual="price_team_annual_test",
    )


def _mock_response(status_code: int, body: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = MagicMock(return_value=body or {})
    return resp


# =============================================================================
# Webhook signature verification
# =============================================================================


@pytest.mark.django_db
class TestWebhookSignature:
    def _signed_payload(
        self, body: bytes, secret: str, *, ts: int | None = None
    ) -> str:
        ts = ts or int(time.time())
        signed = f"{ts}.".encode() + body
        sig = hmac.new(
            secret.encode("utf-8"), signed, hashlib.sha256
        ).hexdigest()
        return f"t={ts},v1={sig}"

    def test_verifies_correct_signature(self, stripe_configured) -> None:
        body = b'{"id":"evt_1","type":"customer.subscription.updated"}'
        header = self._signed_payload(body, "whsec_test_secret")
        event = stripe_client.verify_webhook_signature(
            payload=body, signature_header=header
        )
        assert event["id"] == "evt_1"

    def test_rejects_bad_signature(self, stripe_configured) -> None:
        body = b'{"id":"evt_1"}'
        header = self._signed_payload(body, "whsec_WRONG")
        with pytest.raises(
            stripe_client.StripeWebhookError, match="did not verify"
        ):
            stripe_client.verify_webhook_signature(
                payload=body, signature_header=header
            )

    def test_rejects_stale_timestamp(self, stripe_configured) -> None:
        body = b"{}"
        # 10 minutes old → outside 5-minute window.
        ts = int(time.time()) - 600
        header = self._signed_payload(body, "whsec_test_secret", ts=ts)
        with pytest.raises(
            stripe_client.StripeWebhookError, match="too old"
        ):
            stripe_client.verify_webhook_signature(
                payload=body, signature_header=header
            )

    def test_rejects_missing_header(self, stripe_configured) -> None:
        with pytest.raises(stripe_client.StripeWebhookError, match="Missing"):
            stripe_client.verify_webhook_signature(
                payload=b"{}", signature_header=""
            )

    def test_rejects_when_no_webhook_secret_configured(self, seeded) -> None:
        # Configure stripe but without the webhook secret.
        upsert_system_setting(
            namespace="stripe",
            values={
                "secret_key": "sk_test_12345",
                "webhook_secret": "",
            },
        )
        with pytest.raises(
            stripe_client.StripeWebhookError, match="webhook_secret"
        ):
            stripe_client.verify_webhook_signature(
                payload=b"{}", signature_header="t=1,v1=abc"
            )


# =============================================================================
# Checkout flow
# =============================================================================


@pytest.mark.django_db
class TestStartCheckout:
    def test_creates_customer_then_session(
        self, stripe_configured, org_owner, plan
    ) -> None:
        org, _ = org_owner
        with patch(
            "apps.billing.stripe_client.httpx.post",
            side_effect=[
                _mock_response(200, {"id": "cus_test_001"}),
                _mock_response(
                    200,
                    {
                        "id": "cs_test_001",
                        "url": "https://checkout.stripe.com/c/pay/cs_test_001",
                    },
                ),
            ],
        ) as posted:
            result = checkout.start_checkout(
                organization_id=org.id,
                plan_id=plan.id,
                billing_cycle="monthly",
                success_url="https://app/success",
                cancel_url="https://app/cancel",
            )
        assert result["checkout_url"].startswith("https://checkout.stripe.com")
        assert result["session_id"] == "cs_test_001"
        assert result["stripe_customer_id"] == "cus_test_001"
        # Two API calls: customer create + session create.
        assert posted.call_count == 2
        # Audit captured.
        from apps.audit.models import AuditEvent

        ev = AuditEvent.objects.filter(
            action_type="billing.checkout.started"
        ).first()
        assert ev is not None

    def test_rejects_invalid_billing_cycle(
        self, stripe_configured, org_owner, plan
    ) -> None:
        org, _ = org_owner
        with pytest.raises(checkout.CheckoutError, match="billing_cycle"):
            checkout.start_checkout(
                organization_id=org.id,
                plan_id=plan.id,
                billing_cycle="weekly",
                success_url="https://app/s",
                cancel_url="https://app/c",
            )

    def test_rejects_plan_without_stripe_price(
        self, stripe_configured, org_owner
    ) -> None:
        plan_no_price = Plan.objects.create(
            slug="test-stripe-noprice",
            version=1,
            name="Custom",
            tier=Plan.Tier.ENTERPRISE,
            stripe_price_id_monthly="",
            stripe_price_id_annual="",
        )
        org, _ = org_owner
        with pytest.raises(checkout.CheckoutError, match="Stripe price"):
            checkout.start_checkout(
                organization_id=org.id,
                plan_id=plan_no_price.id,
                billing_cycle="monthly",
                success_url="https://app/s",
                cancel_url="https://app/c",
            )

    def test_reuses_existing_stripe_customer_id(
        self, stripe_configured, org_owner, plan
    ) -> None:
        org, _ = org_owner
        # Pretend a prior subscription captured a customer ID.
        Subscription.objects.create(
            organization=org,
            plan=plan,
            stripe_customer_id="cus_existing_001",
        )
        with patch(
            "apps.billing.stripe_client.httpx.post",
            return_value=_mock_response(
                200,
                {
                    "id": "cs_test_002",
                    "url": "https://checkout.stripe.com/c/pay/cs_test_002",
                },
            ),
        ) as posted:
            result = checkout.start_checkout(
                organization_id=org.id,
                plan_id=plan.id,
                billing_cycle="annual",
                success_url="https://app/s",
                cancel_url="https://app/c",
            )
        assert result["stripe_customer_id"] == "cus_existing_001"
        # Only one API call this time (no customer create needed).
        assert posted.call_count == 1


# =============================================================================
# Webhook event handlers
# =============================================================================


@pytest.mark.django_db
class TestWebhookHandlers:
    def test_checkout_completed_creates_subscription(
        self, stripe_configured, org_owner, plan
    ) -> None:
        org, _ = org_owner
        event = {
            "id": "evt_co_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_x",
                    "subscription": "sub_x",
                    "metadata": {
                        "organization_id": str(org.id),
                        "plan_id": str(plan.id),
                        "billing_cycle": "monthly",
                    },
                }
            },
        }
        result = checkout.handle_webhook(event=event)
        assert result["handled"] is True
        sub = Subscription.objects.get(stripe_subscription_id="sub_x")
        assert sub.status == Subscription.Status.ACTIVE
        assert sub.stripe_customer_id == "cus_x"
        org.refresh_from_db()
        assert org.subscription_state == Organization.SubscriptionState.ACTIVE

    def test_subscription_updated_reconciles_status(
        self, stripe_configured, org_owner, plan
    ) -> None:
        org, _ = org_owner
        sub = Subscription.objects.create(
            organization=org,
            plan=plan,
            stripe_subscription_id="sub_y",
            stripe_customer_id="cus_y",
            status=Subscription.Status.ACTIVE,
        )
        event = {
            "id": "evt_su_1",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_y",
                    "status": "past_due",
                    "current_period_start": int(time.time()),
                    "current_period_end": int(time.time()) + 86400,
                    "cancel_at_period_end": False,
                }
            },
        }
        result = checkout.handle_webhook(event=event)
        assert result["handled"] is True
        sub.refresh_from_db()
        assert sub.status == Subscription.Status.PAST_DUE
        org.refresh_from_db()
        assert (
            org.subscription_state == Organization.SubscriptionState.PAST_DUE
        )

    def test_subscription_deleted_marks_cancelled(
        self, stripe_configured, org_owner, plan
    ) -> None:
        org, _ = org_owner
        sub = Subscription.objects.create(
            organization=org,
            plan=plan,
            stripe_subscription_id="sub_z",
            status=Subscription.Status.ACTIVE,
        )
        event = {
            "id": "evt_sd_1",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_z"}},
        }
        result = checkout.handle_webhook(event=event)
        assert result["handled"] is True
        sub.refresh_from_db()
        assert sub.status == Subscription.Status.CANCELLED
        assert sub.cancelled_at is not None

    def test_payment_failed_marks_past_due(
        self, stripe_configured, org_owner, plan
    ) -> None:
        org, _ = org_owner
        sub = Subscription.objects.create(
            organization=org,
            plan=plan,
            stripe_subscription_id="sub_pf",
            status=Subscription.Status.ACTIVE,
        )
        event = {
            "id": "evt_pf_1",
            "type": "invoice.payment_failed",
            "data": {"object": {"subscription": "sub_pf"}},
        }
        result = checkout.handle_webhook(event=event)
        assert result["handled"] is True
        sub.refresh_from_db()
        assert sub.status == Subscription.Status.PAST_DUE

    def test_unsupported_event_type_silently_acks(
        self, stripe_configured
    ) -> None:
        result = checkout.handle_webhook(
            event={"id": "evt_x", "type": "some.other.event", "data": {}}
        )
        assert result["handled"] is False


# =============================================================================
# Webhook endpoint
# =============================================================================


@pytest.mark.django_db
class TestWebhookEndpoint:
    def test_endpoint_400_on_bad_signature(self, stripe_configured) -> None:
        from django.test import Client

        response = Client().post(
            "/api/v1/billing/stripe-webhook/",
            data=b'{"id":"evt_x"}',
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=abc",
        )
        assert response.status_code == 400

    def test_endpoint_200_on_valid_signature(
        self, stripe_configured, org_owner, plan
    ) -> None:
        from django.test import Client

        org, _ = org_owner
        body = json.dumps(
            {
                "id": "evt_co_2",
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "customer": "cus_a",
                        "subscription": "sub_a",
                        "metadata": {
                            "organization_id": str(org.id),
                            "plan_id": str(plan.id),
                            "billing_cycle": "monthly",
                        },
                    }
                },
            }
        ).encode("utf-8")
        ts = int(time.time())
        sig = hmac.new(
            b"whsec_test_secret",
            f"{ts}.".encode() + body,
            hashlib.sha256,
        ).hexdigest()
        response = Client().post(
            "/api/v1/billing/stripe-webhook/",
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
        )
        assert response.status_code == 200
        sub = Subscription.objects.get(stripe_subscription_id="sub_a")
        assert sub.status == Subscription.Status.ACTIVE
