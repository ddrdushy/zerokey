"""Enable Row-Level Security on tenant-scoped identity tables.

Per ARCHITECTURE.md and SECURITY.md, multi-tenancy is enforced at the database
layer through PostgreSQL Row-Level Security. The contract:

  - Every tenant-scoped table has RLS enabled.
  - A policy filters rows where ``organization_id`` matches
    ``current_setting('app.current_tenant_id')``.
  - Super-admin context bypasses via ``current_setting('app.is_super_admin') = 'on'``.
  - The application connects as a non-superuser role so policies actually apply.

This migration is Postgres-only. On SQLite (used for fast unit tests) it becomes
a no-op; tests that exercise RLS are gated on ``connection.vendor == 'postgresql'``.
"""

from __future__ import annotations

from django.db import migrations

# Tables this migration covers. New tenant-scoped tables in other apps emit the
# same RLS DDL in their own migrations.
TENANT_TABLES: tuple[str, ...] = ("identity_membership",)

ENABLE_RLS_TEMPLATE = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON {table};
CREATE POLICY tenant_isolation ON {table}
    USING (
        organization_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        OR current_setting('app.is_super_admin', true) = 'on'
    )
    WITH CHECK (
        organization_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        OR current_setting('app.is_super_admin', true) = 'on'
    );
"""

DISABLE_RLS_TEMPLATE = """
DROP POLICY IF EXISTS tenant_isolation ON {table};
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""


def apply_rls(apps, schema_editor):  # noqa: ARG001
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TENANT_TABLES:
        schema_editor.execute(ENABLE_RLS_TEMPLATE.format(table=table))


def reverse_rls(apps, schema_editor):  # noqa: ARG001
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TENANT_TABLES:
        schema_editor.execute(DISABLE_RLS_TEMPLATE.format(table=table))


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(apply_rls, reverse_rls),
    ]
