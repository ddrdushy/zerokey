# Generated for Slice 87 — two-step approval workflow.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0015_whatsapp_phone_number_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="approval_policy",
            field=models.CharField(
                choices=[
                    ("none", "No approval"),
                    ("always", "Always requires approval"),
                    ("threshold", "Requires approval over threshold"),
                ],
                default="none",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="approval_threshold_amount",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=19, null=True
            ),
        ),
    ]
