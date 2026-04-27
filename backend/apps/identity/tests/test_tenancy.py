"""Cross-tenant isolation tests.

These exercise the actual RLS policies and therefore only run on PostgreSQL.
On the SQLite-in-memory test database the test is skipped; the chain integrity
and canonical-serialization tests run there instead.

To run against Postgres locally:

    DJANGO_SETTINGS_MODULE=zerokey.settings.dev uv run pytest apps/identity/tests/test_tenancy.py
"""

from __future__ import annotations

import pytest
from django.db import connection

from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.identity.tenancy import clear_tenant, set_tenant, super_admin_context

postgres_only = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="RLS policies are PostgreSQL-only; rerun under dev settings to exercise.",
)


@postgres_only
@pytest.mark.django_db
class TestTenantIsolation:
    @pytest.fixture
    def two_tenants(self) -> tuple[Organization, Organization, Role]:
        role, _ = Role.objects.get_or_create(name=Role.SystemRole.OWNER)
        a = Organization.objects.create(
            legal_name="Tenant A", tin="C10000000001", contact_email="a@example"
        )
        b = Organization.objects.create(
            legal_name="Tenant B", tin="C10000000002", contact_email="b@example"
        )
        u_a = User.objects.create_user(email="a@example.com", password="x")
        u_b = User.objects.create_user(email="b@example.com", password="x")
        OrganizationMembership.objects.create(user=u_a, organization=a, role=role)
        OrganizationMembership.objects.create(user=u_b, organization=b, role=role)
        return a, b, role

    def test_tenant_a_does_not_see_tenant_b_memberships(
        self, two_tenants: tuple[Organization, Organization, Role]
    ) -> None:
        a, _b, _ = two_tenants
        set_tenant(a.id)
        try:
            visible = list(OrganizationMembership.objects.values_list("organization_id", flat=True))
            assert all(org_id == a.id for org_id in visible)
            assert any(True for _ in visible)
        finally:
            clear_tenant()

    def test_no_tenant_set_returns_zero_rows(
        self, two_tenants: tuple[Organization, Organization, Role]
    ) -> None:
        clear_tenant()  # belt: no tenant context active
        assert OrganizationMembership.objects.count() == 0

    def test_super_admin_context_sees_all_tenants(
        self, two_tenants: tuple[Organization, Organization, Role]
    ) -> None:
        with super_admin_context(reason="cross-tenant verification job"):
            assert OrganizationMembership.objects.count() == 2
