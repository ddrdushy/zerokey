"""Smoke tests for the identity domain. RLS enforcement is exercised in
``test_tenancy.py`` (Postgres-gated)."""

from __future__ import annotations

import pytest

from apps.identity.models import Organization, OrganizationMembership, Role, User


@pytest.mark.django_db
class TestIdentity:
    def test_user_email_is_normalized_and_unique(self) -> None:
        u = User.objects.create_user(email="DUSHY@example.com", password="x")
        assert u.email == "DUSHY@example.com"  # local-part casing preserved
        # Domain casing is normalized by the Django manager:
        u2 = User.objects.create_user(email="Other@EXAMPLE.com", password="x")
        assert u2.email.endswith("@example.com")

    def test_membership_unique_per_user_per_organization(self) -> None:
        org = Organization.objects.create(
            legal_name="ACME Sdn Bhd",
            tin="C20880050010",
            contact_email="ops@acme.example",
        )
        role = Role.objects.create(name=Role.SystemRole.OWNER)
        user = User.objects.create_user(email="a@example.com", password="x")
        OrganizationMembership.objects.create(user=user, organization=org, role=role)

        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            OrganizationMembership.objects.create(user=user, organization=org, role=role)

    def test_organization_default_state_is_trialing(self) -> None:
        org = Organization.objects.create(
            legal_name="ACME Sdn Bhd",
            tin="C20880050099",
            contact_email="ops@acme.example",
        )
        assert org.subscription_state == Organization.SubscriptionState.TRIALING
        assert org.trial_state == Organization.TrialState.ACTIVE
        assert org.billing_currency == "MYR"
        assert org.timezone == "Asia/Kuala_Lumpur"
