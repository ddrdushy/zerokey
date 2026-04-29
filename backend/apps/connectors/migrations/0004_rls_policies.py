"""Enable RLS on the new sync-proposal / lock / conflict tables.

Same per-table CREATE POLICY pattern as the rest of the codebase;
Postgres-gated via RunPython + connection.vendor, no-op on SQLite
for the test backend.
"""

from __future__ import annotations

from django.db import migrations

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

TENANT_TABLES: tuple[str, ...] = (
    "connectors_sync_proposal",
    "connectors_master_field_lock",
    "connectors_master_field_conflict",
)


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
        ("connectors", "0003_proposal_conflict_lock"),
    ]

    operations = [
        migrations.RunPython(apply_rls, reverse_rls),
    ]
