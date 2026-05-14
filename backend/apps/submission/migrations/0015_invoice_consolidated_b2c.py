"""Phase 5 of PORTAL_PLAN.md — consolidated B2C link + status.

Two additions to Invoice:

  - ``consolidated_in_invoice_id`` (nullable UUID, indexed). When set,
    this row is a constituent rolled into a parent consolidated
    submission. Only the parent submits to LHDN; the constituents
    remain in the database as the audit-side detail of what was
    folded in.

  - ``Status.CONSOLIDATED`` enum value — the status the constituents
    sit at after being rolled up. Distinct from VALIDATED (the
    constituent itself was never validated by LHDN) and from
    NOT_SUBMITTED (intentional, not held back). On the invoice list
    the constituents get their own pill so the operator can tell
    "this one is settled, just not individually."

No schema change for the enum itself — CharField accepts the new
choice. No data migration needed for the column: existing rows are
not part of any consolidation, so null is the right default.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("submission", "0014_invoice_auto_submit"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="consolidated_in_invoice_id",
            field=models.UUIDField(null=True, blank=True, db_index=True),
        ),
    ]
