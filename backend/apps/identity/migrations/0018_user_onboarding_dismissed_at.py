from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0017_totp_secret"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="onboarding_dismissed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
