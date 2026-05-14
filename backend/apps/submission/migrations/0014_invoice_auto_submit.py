"""Phase 3 of PORTAL_PLAN.md — Not Submitted state + audit reason.

Adds:

  - ``Invoice.Status.NOT_SUBMITTED`` enum value. Distinct from
    ``READY_FOR_REVIEW`` ("we haven't tried yet, customer should look")
    — NOT_SUBMITTED means "the auto-submit pipeline considered this
    one and deliberately held back, customer can click Submit when
    ready." On the invoice list it gets its own pill so the operator
    knows it's been triaged, not abandoned.

  - ``Invoice.auto_submit_blocked_reason`` — short string captured at
    transition time. Surfaced inline on the row so the customer
    doesn't have to guess why ("Auto-submit disabled",
    "Extraction confidence below 0.92", "Buyer requires review",
    "Validation: supplier_tin.format").

No data migration — existing rows have ``auto_submit_blocked_reason=""``
and keep their current status.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("submission", "0013_invoice_scheduled_submit_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="auto_submit_blocked_reason",
            field=models.CharField(max_length=128, blank=True, default=""),
        ),
        # Note: Status.NOT_SUBMITTED is added at the enum level on the
        # model; Django's CharField already accepts any choice we put
        # in the TextChoices, no schema change needed for the enum
        # addition itself.
    ]
