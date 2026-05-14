"""Phase 3 of PORTAL_PLAN.md — per-customer auto-submit override.

Customers (buyers, not tenants) gain a tri-state override on the
auto-submit decision:

  - ``none`` (default): follow the org-level ``auto_submit_default``.
  - ``always``: force auto-submit for invoices to this buyer, even if
    the org default is off. Useful for trusted recurring B2B.
  - ``review``: force manual review for invoices to this buyer, even
    if the org default is on. Useful for high-value or audit-sensitive
    relationships ("hold-for-review my Petronas invoices").

CustomerMaster rows already exist per-tenant per-buyer, learned from
extraction + connector sync. This column just adds the override knob
to each row.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("enrichment", "0004_encrypt_customermaster_pii"),
    ]

    operations = [
        migrations.AddField(
            model_name="customermaster",
            name="auto_submit_override",
            field=models.CharField(
                max_length=16,
                choices=[
                    ("none", "Follow org default"),
                    ("always", "Always auto-submit"),
                    ("review", "Always require review"),
                ],
                default="none",
            ),
        ),
    ]
