"""Add Organization.extraction_mode (Slice 54).

Per-tenant extraction lane. ``ai_vision`` (default) keeps the
existing vision-escalation + LLM-structuring path. ``ocr_only``
short-circuits the AI calls and routes through OCR + a deterministic
regex floor structurer (PaddleOCR + LayoutLMv3 in Slices 55+56).
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0007_notif_pref_rls"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="extraction_mode",
            field=models.CharField(
                choices=[("ai_vision", "AI extraction"), ("ocr_only", "OCR only")],
                default="ai_vision",
                max_length=16,
            ),
        ),
    ]
