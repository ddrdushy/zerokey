"""RLS on the two tenant-scoped tables added in 0005.

FeatureFlag itself is platform-global (no RLS); FeatureFlagOverride
and OverageWaiver are per-tenant.
"""

from __future__ import annotations

from django.db import migrations

ENABLE = """
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

DISABLE = """
DROP POLICY IF EXISTS tenant_isolation ON {table};
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""

TABLES = ("billing_feature_flag_override", "billing_overage_waiver")


def apply_rls(apps, schema_editor):  # noqa: ARG001
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(ENABLE.format(table=table))


def reverse_rls(apps, schema_editor):  # noqa: ARG001
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(DISABLE.format(table=table))


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0006_seed_feature_flags"),
    ]
    operations = [
        migrations.RunPython(apply_rls, reverse_rls),
    ]
