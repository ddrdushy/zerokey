"""Audit table protections.

The audit log is special: even tenant queries are read-only against it, and
no application code path is permitted to modify or delete a row.

This migration:

  - Enables RLS on ``audit_event`` so tenant queries see only their own events.
  - Creates a SELECT-only policy. The app role is granted SELECT and INSERT but
    explicitly REVOKED UPDATE and DELETE — an attacker who reaches the database
    cannot rewrite history without becoming superuser.
  - Allows super-admin context to read across tenants for verification jobs.

Postgres-only (RLS / role grants are Postgres features). On SQLite the
migration is a no-op; tests that exercise these protections gate on
``connection.vendor == 'postgresql'``.
"""

from __future__ import annotations

import os

from django.db import migrations

ENABLE_RLS_SQL = """
ALTER TABLE audit_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_event FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS audit_tenant_read ON audit_event;
CREATE POLICY audit_tenant_read ON audit_event
    FOR SELECT
    USING (
        organization_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        OR organization_id IS NULL  -- system events
        OR current_setting('app.is_super_admin', true) = 'on'
    );

DROP POLICY IF EXISTS audit_insert ON audit_event;
CREATE POLICY audit_insert ON audit_event
    FOR INSERT
    WITH CHECK (true);
"""

REVOKE_WRITES_SQL = """
REVOKE UPDATE, DELETE ON audit_event FROM PUBLIC;
REVOKE UPDATE, DELETE ON audit_event FROM {app_role};
"""

DISABLE_RLS_SQL = """
DROP POLICY IF EXISTS audit_tenant_read ON audit_event;
DROP POLICY IF EXISTS audit_insert ON audit_event;
ALTER TABLE audit_event DISABLE ROW LEVEL SECURITY;
"""


def _app_role() -> str:
    # Same env var the application uses to connect, so privilege ops match the
    # actual runtime role. Defaults match infra/postgres-init.
    return os.environ.get("POSTGRES_APP_USER", "zerokey_app")


def apply_audit_protections(apps, schema_editor):  # noqa: ARG001
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(ENABLE_RLS_SQL)
    schema_editor.execute(REVOKE_WRITES_SQL.format(app_role=_app_role()))


def reverse_audit_protections(apps, schema_editor):  # noqa: ARG001
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(DISABLE_RLS_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        ("identity", "0002_rls_policies"),
    ]

    operations = [
        migrations.RunPython(apply_audit_protections, reverse_audit_protections),
    ]
