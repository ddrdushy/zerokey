"""Tests for the Settings → Organization surface (Slice 23).

Covers the contract the customer's settings page relies on:
  - GET returns the active org's full detail.
  - PATCH applies allowlisted edits (legal_name / contact_email /
    address / phone / sst_number / language / timezone / logo_url).
  - PATCH rejects non-editable fields including TIN, billing currency,
    trial / subscription state, certificate_*. The TIN exclusion is
    structural — changing it would invalidate every signed invoice
    that referenced the prior value.
  - PATCH writes a single ``identity.organization.updated`` audit
    event whose payload lists changed field NAMES (no values: PII).
  - Empty legal_name rejected; no-op (submitting current values)
    writes no audit event.
  - A user without active membership in the active-org id gets 403.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.identity.services import (
    EDITABLE_ORGANIZATION_FIELDS,
    OrganizationUpdateError,
    update_organization,
)


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_user(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme Sdn Bhd",
        tin="C10000000001",
        contact_email="ops@acme.example",
        contact_phone="03-1234-0000",
        registered_address="Lot 1, Jalan Awal",
    )
    user = User.objects.create_user(
        email="o@acme.example", password="long-enough-password"
    )
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
class TestUpdateOrganizationService:
    def test_updates_allowlisted_fields(self, org_user) -> None:
        org, user = org_user
        update_organization(
            organization_id=org.id,
            updates={
                "legal_name": "Acme Renamed Sdn Bhd",
                "registered_address": "Lot 2, Jalan Baharu",
                "language_preference": "ms-MY",
            },
            actor_user_id=user.id,
        )
        org.refresh_from_db()
        assert org.legal_name == "Acme Renamed Sdn Bhd"
        assert org.registered_address == "Lot 2, Jalan Baharu"
        assert org.language_preference == "ms-MY"

    def test_no_op_when_nothing_changes(self, org_user) -> None:
        org, user = org_user
        update_organization(
            organization_id=org.id,
            updates={"legal_name": org.legal_name},
            actor_user_id=user.id,
        )
        # No identity.organization.updated audit event should have been written.
        assert (
            AuditEvent.objects.filter(action_type="identity.organization.updated").count()
            == 0
        )

    def test_audit_event_lists_field_names_no_values(self, org_user) -> None:
        org, user = org_user
        update_organization(
            organization_id=org.id,
            updates={
                "legal_name": "Renamed With Sensitive Buyer Pattern Sdn Bhd",
                "contact_phone": "secret-internal-number",
            },
            actor_user_id=user.id,
        )
        event = AuditEvent.objects.get(action_type="identity.organization.updated")
        assert sorted(event.payload["changed_fields"]) == [
            "contact_phone",
            "legal_name",
        ]
        # No value should leak.
        serialized = str(event.payload)
        assert "Sensitive Buyer Pattern" not in serialized
        assert "secret-internal-number" not in serialized

    def test_unknown_field_rejected(self, org_user) -> None:
        org, user = org_user
        with pytest.raises(OrganizationUpdateError, match="non-editable"):
            update_organization(
                organization_id=org.id,
                updates={"tin": "C99999999999"},
                actor_user_id=user.id,
            )

    def test_blank_legal_name_rejected(self, org_user) -> None:
        org, user = org_user
        with pytest.raises(OrganizationUpdateError, match="legal_name"):
            update_organization(
                organization_id=org.id,
                updates={"legal_name": "   "},
                actor_user_id=user.id,
            )


@pytest.mark.django_db
class TestEditableFieldAllowlist:
    def test_excludes_structural_fields(self) -> None:
        """TIN / billing currency / lifecycle / certificate fields must not be editable.

        Changing TIN would invalidate every signed invoice that
        referenced the old value; billing / lifecycle / certificate
        belong to other contexts (Stripe, signing service).
        """
        forbidden = {
            "tin",
            "billing_currency",
            "trial_state",
            "subscription_state",
            "certificate_uploaded",
            "certificate_expiry_date",
            "certificate_kms_key_alias",
        }
        assert forbidden.isdisjoint(EDITABLE_ORGANIZATION_FIELDS)


@pytest.mark.django_db
class TestOrganizationDetailEndpoint:
    def test_get_returns_active_org(self, authed) -> None:
        client, org, _ = authed
        response = client.get("/api/v1/identity/organization/")
        assert response.status_code == 200
        body = response.json()
        assert body["legal_name"] == org.legal_name
        assert body["tin"] == org.tin
        assert body["contact_email"] == org.contact_email
        # Read-only fields the UI shouldn't try to edit but should display.
        assert "subscription_state" in body
        assert "certificate_uploaded" in body

    def test_patch_updates_via_endpoint(self, authed) -> None:
        client, org, _ = authed
        response = client.patch(
            "/api/v1/identity/organization/",
            data={"contact_phone": "03-9999-9999"},
            content_type="application/json",
        )
        assert response.status_code == 200, response.content
        org.refresh_from_db()
        assert org.contact_phone == "03-9999-9999"

    def test_patch_unknown_field_400(self, authed) -> None:
        client, _, _ = authed
        response = client.patch(
            "/api/v1/identity/organization/",
            data={"tin": "C99999999999"},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "non-editable" in response.json()["detail"]

    def test_unauthenticated_rejected(self) -> None:
        response = Client().get("/api/v1/identity/organization/")
        assert response.status_code in (401, 403)

    def test_no_active_org_returns_400(self, seeded) -> None:
        from apps.identity.models import User as _User

        user = _User.objects.create_user(
            email="solo@example.com", password="long-enough-password"
        )
        client = Client()
        client.force_login(user)
        response = client.get("/api/v1/identity/organization/")
        assert response.status_code == 400

    def test_user_not_in_active_org_is_403(self, seeded) -> None:
        """Edge case: session has an org_id but the user has no membership in it."""
        org = Organization.objects.create(
            legal_name="Some Org",
            tin="C30000000001",
            contact_email="ops@some.example",
        )
        # User exists but is NOT a member of this org.
        user = User.objects.create_user(
            email="outsider@example.com", password="long-enough-password"
        )
        client = Client()
        client.force_login(user)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()

        response = client.get("/api/v1/identity/organization/")
        assert response.status_code == 403


@pytest.mark.django_db
class TestExtractionMode:
    """Slice 54: per-tenant extraction lane (ai_vision | ocr_only)."""

    def test_default_is_ai_vision(self, org_user) -> None:
        org, _ = org_user
        # Org freshly created — never set the field — default applies.
        assert org.extraction_mode == "ai_vision"

    def test_patch_sets_ocr_only(self, authed) -> None:
        client, org, _ = authed
        response = client.patch(
            "/api/v1/identity/organization/",
            data=json.dumps({"extraction_mode": "ocr_only"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        org.refresh_from_db()
        assert org.extraction_mode == "ocr_only"
        # Audit recorded with field-name only (PII-clean).
        from apps.audit.models import AuditEvent

        event = (
            AuditEvent.objects.filter(action_type="identity.organization.updated")
            .order_by("-sequence")
            .first()
        )
        assert event is not None
        assert "extraction_mode" in event.payload["changed_fields"]
        # Value MUST NOT appear in payload.
        assert "ocr_only" not in json.dumps(event.payload)

    def test_patch_invalid_value_400(self, authed) -> None:
        client, _, _ = authed
        response = client.patch(
            "/api/v1/identity/organization/",
            data=json.dumps({"extraction_mode": "magic_unicorn"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_extraction_mode_in_get_payload(self, authed) -> None:
        client, _, _ = authed
        response = client.get("/api/v1/identity/organization/")
        body = response.json()
        assert body["extraction_mode"] in {"ai_vision", "ocr_only"}
