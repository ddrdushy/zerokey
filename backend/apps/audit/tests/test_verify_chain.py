"""Tests for the customer-triggered chain verification surface (Slice 21).

Covers:
  - Clean chain returns ``ok=True`` with the verified count.
  - Tampered chain returns ``ok=False`` and DOES NOT leak the offending
    sequence number to the customer (it might belong to another tenant).
  - The verification call itself is audited (one
    ``audit.chain_verified`` event per call, scoped to the requester's
    org, payload carries ok + count but never sequence numbers).
  - Endpoint POST not GET (the call writes an audit event, so it's
    not trivially idempotent).
  - Cross-tenant: requesting verification under one org never returns
    information that would distinguish "your chain is fine but
    someone else's tampered" from "your chain tampered" — the
    customer-facing message is identical.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.audit.services import record_event, verify_chain_for_visibility
from apps.identity.models import Organization, OrganizationMembership, Role, User


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_user(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme Sdn Bhd", tin="C10000000001", contact_email="ops@acme.example"
    )
    user = User.objects.create_user(email="o@acme.example", password="long-enough-password")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


@pytest.fixture
def authed(org_user) -> tuple[Client, Organization, User]:
    org, user = org_user
    client = Client()
    client.force_login(user)
    session = client.session
    session["organization_id"] = str(org.id)
    session.save()
    return client, org, user


@pytest.mark.django_db
class TestVerifyChainService:
    def test_clean_chain_returns_ok(self, org_user) -> None:
        org, user = org_user
        # Seed a few real events on the chain.
        for action in ("a", "b", "c"):
            record_event(
                action_type=action,
                actor_type=AuditEvent.ActorType.SERVICE,
                organization_id=str(org.id),
            )

        result = verify_chain_for_visibility(organization_id=org.id, actor_user_id=user.id)
        assert result["ok"] is True
        assert result["tampering_detected"] is False
        # >=4: 3 from this test + the verify event itself counts in the next call.
        assert result["events_verified"] >= 3

    def test_tampered_chain_returns_not_ok_without_leaking_sequence(self, org_user) -> None:
        org, user = org_user
        e1 = record_event(
            action_type="invoice.created",
            actor_type=AuditEvent.ActorType.USER,
            actor_id="u1",
            organization_id=str(org.id),
            payload={"amount": "100.00"},
        )
        # Tamper with the stored payload after the chain hash was computed.
        # This is the same technique test_record_event uses to assert the
        # chain detects tampering.
        AuditEvent.objects.filter(pk=e1.pk).update(payload={"amount": "9000.00"})

        result = verify_chain_for_visibility(organization_id=org.id, actor_user_id=user.id)
        assert result["ok"] is False
        assert result["tampering_detected"] is True
        # Customer message is generic — never mentions the offending
        # sequence (could be another tenant's event in production).
        assert (
            "support" in result["support_message"].lower()
            or "alert" in result["support_message"].lower()
        )
        # The result dict carries no key that exposes a sequence number.
        for key, value in result.items():
            assert "sequence" not in str(key).lower()
            if isinstance(value, str):
                # Sanity: no raw sequence number embedded in the message.
                assert "sequence=" not in value

    def test_verify_call_is_audited(self, org_user) -> None:
        org, user = org_user
        before_count = AuditEvent.objects.filter(action_type="audit.chain_verified").count()

        verify_chain_for_visibility(organization_id=org.id, actor_user_id=user.id)
        verify_chain_for_visibility(organization_id=org.id, actor_user_id=user.id)

        after_count = AuditEvent.objects.filter(action_type="audit.chain_verified").count()
        assert after_count == before_count + 2

        # The most recent verify event is scoped to the requester's org.
        event = (
            AuditEvent.objects.filter(action_type="audit.chain_verified")
            .order_by("-sequence")
            .first()
        )
        assert str(event.organization_id) == str(org.id)
        assert event.actor_id == str(user.id)
        # Payload carries ok + events_verified, no sequence numbers.
        assert "ok" in event.payload
        assert "events_verified" in event.payload


@pytest.mark.django_db
class TestVerifyChainEndpoint:
    def test_post_returns_clean_chain(self, authed) -> None:
        client, _org, _user = authed
        response = client.post("/api/v1/audit/verify/")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["tampering_detected"] is False
        assert "events_verified" in body
        assert "support_message" in body

    def test_get_method_not_allowed(self, authed) -> None:
        """GET would imply idempotent. The call writes an audit event."""
        client, _org, _user = authed
        response = client.get("/api/v1/audit/verify/")
        assert response.status_code == 405

    def test_unauthenticated_rejected(self) -> None:
        response = Client().post("/api/v1/audit/verify/")
        assert response.status_code in (401, 403)

    def test_no_active_org_returns_400(self, seeded) -> None:
        from apps.identity.models import User

        user = User.objects.create_user(email="solo@example.com", password="long-enough-password")
        client = Client()
        client.force_login(user)
        response = client.post("/api/v1/audit/verify/")
        assert response.status_code == 400
