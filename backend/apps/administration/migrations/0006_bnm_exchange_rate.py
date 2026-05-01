"""BNM exchange-rate cache (Slice 96)."""

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("administration", "0005_encrypt_existing_secrets"),
    ]

    operations = [
        migrations.CreateModel(
            name="BnmExchangeRate",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("rate_date", models.DateField()),
                ("currency_code", models.CharField(max_length=3)),
                ("buying_rate", models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)),
                ("selling_rate", models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)),
                ("middle_rate", models.DecimalField(max_digits=12, decimal_places=6)),
                ("fetched_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "db_table": "bnm_exchange_rate",
                "ordering": ["-rate_date", "currency_code"],
            },
        ),
        migrations.AddConstraint(
            model_name="bnmexchangerate",
            constraint=models.UniqueConstraint(
                fields=["rate_date", "currency_code"],
                name="bnm_exchange_rate_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="bnmexchangerate",
            index=models.Index(
                fields=["currency_code", "-rate_date"],
                name="bnm_exchange_rate_lookup",
            ),
        ),
    ]
