"""Atomic gap-free sequence counter for audit events.

The original advisory-lock + ``MAX(sequence) + 1`` approach had a subtle race
under threaded WSGI: under multi-threaded request handling, two record_event
calls could race between the lock acquisition and the SELECT, ending up with
the same sequence and one of them failing the unique constraint.

Postgres serializes concurrent UPDATEs on the same row through MVCC; using an
atomic ``UPDATE … RETURNING`` on a single-row counter is race-free and lives
inside the caller's transaction so a rollback un-increments the counter
naturally — preserving the gap-free guarantee.

Postgres-only: SQLite tests run single-threaded and use ``MAX + 1``.
"""

from __future__ import annotations

from django.db import migrations

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS audit_sequence (
    id   INTEGER PRIMARY KEY,
    value BIGINT NOT NULL
);
"""

DROP_SQL = "DROP TABLE IF EXISTS audit_sequence;"


def apply(apps, schema_editor):  # noqa: ARG001
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(CREATE_SQL)


def reverse(apps, schema_editor):  # noqa: ARG001
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(DROP_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0002_append_only_rls"),
    ]

    operations = [
        migrations.RunPython(apply, reverse),
    ]
