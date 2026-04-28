"""RLS on tenant-scoped billing tables (Subscription / PaymentMethod / UsageEvent).

Plan is platform-wide and intentionally has NO RLS — every tenant
reads the same catalog under their regular tenant context.
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
    "billing_subscription",
    "billing_payment_method",
    "billing_usage_event",
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
        ("billing", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(apply_rls, reverse_rls),
    ]
