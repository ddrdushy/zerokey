"""Phase 1 — intermediary signing mode (PORTAL_PLAN.md).

Adds two columns to Organization:

  - ``signing_mode`` — enum ``intermediary | self_signed``. Default
    ``intermediary`` for newly-created orgs, so customers don't need
    to bring an LHDN-issued certificate. ``self_signed`` continues to
    mean "this org has its own cert (uploaded or dev-generated)".

  - ``intermediary_consent_at`` — timestamp the customer accepted the
    "Symprio signs on my behalf" terms. Required for any intermediary
    submission to go out. Null on existing rows; the Settings UI
    surfaces the consent prompt on next sign-in.

Data migration:

  - Orgs with ``certificate_kind == 'uploaded'`` flip to
    ``signing_mode = 'self_signed'``. They have their own real LHDN
    certificate and we keep using it.
  - Every other org defaults to ``signing_mode = 'intermediary'``.
    That includes orgs running on the dev self-signed cert (which
    LHDN production won't accept anyway) and orgs that haven't
    minted a cert yet.

This migration touches the schema only — the signing service that
dispatches on the new column lands in the same commit but is
independent of the column existing first.
"""

from __future__ import annotations

from django.db import migrations, models


def set_initial_signing_mode(apps, schema_editor):
    Organization = apps.get_model("identity", "Organization")
    # Customers running a real uploaded LHDN cert keep their own
    # signing flow. Everyone else falls into the intermediary path.
    Organization.objects.filter(certificate_kind="uploaded").update(signing_mode="self_signed")
    Organization.objects.exclude(certificate_kind="uploaded").update(signing_mode="intermediary")


def revert_initial_signing_mode(apps, schema_editor):
    # Reverting drops everyone back to the implicit "self_signed" world
    # the pre-Phase-1 code assumed. Safe — the column itself is
    # being removed in the same reversal.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0021_organization_deleted_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="signing_mode",
            field=models.CharField(
                max_length=16,
                choices=[
                    ("intermediary", "Intermediary (Symprio signs)"),
                    ("self_signed", "Self-signed (org owns cert)"),
                ],
                default="intermediary",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="intermediary_consent_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.RunPython(set_initial_signing_mode, revert_initial_signing_mode),
    ]
