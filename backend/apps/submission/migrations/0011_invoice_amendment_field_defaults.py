"""Default-empty for the Slice 60 amendment columns.

The columns were added in 0007 as ``TextField(blank=True)`` /
``CharField(blank=True)`` with no ``default=``. Postgres created
them as ``NOT NULL`` with no DB default, so any code path that
calls ``Invoice.objects.create(...)`` without explicitly passing
these three fields fails with an IntegrityError.

In practice this broke the extraction pipeline:
``apps.submission.services.create_invoice_from_extraction``
omits them (rightly — they only matter for CN/DN/RN amendments)
and every fresh upload was getting stuck in ``extracting`` state
with the worker raising on the Invoice insert. Adding the
``default=''`` brings the model + DB into agreement and lets
the bare ``Invoice.objects.create()`` succeed for plain invoices.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("submission", "0010_approval_request"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invoice",
            name="adjustment_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="invoice",
            name="original_invoice_internal_id",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AlterField(
            model_name="invoice",
            name="original_invoice_uuid",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
