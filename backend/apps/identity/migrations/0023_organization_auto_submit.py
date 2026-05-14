"""Phase 3 of PORTAL_PLAN.md — auto-submit toggle on Organization.

Two new columns:

  - ``auto_submit_default`` — Org-level toggle. When ``True`` (and the
    per-customer override allows + validation + extraction confidence
    are above the threshold), ZeroKey signs and submits new invoices
    to LHDN without a manual click. Default ``False`` — opt-in,
    matches the spec's fail-closed posture.

  - ``auto_submit_confidence_threshold`` — Float in [0, 1]. Below this,
    a candidate auto-submission falls back to the Not Submitted queue
    no matter the org default. Default ``0.92``.

The fields don't need a data migration — every existing row gets the
``False`` / ``0.92`` defaults, which preserves today's "everything
requires manual submit" behaviour for orgs that didn't opt in.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0022_organization_signing_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="auto_submit_default",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="organization",
            name="auto_submit_confidence_threshold",
            field=models.FloatField(default=0.92),
        ),
    ]
