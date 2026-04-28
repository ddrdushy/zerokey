"""Register the EasyOCR text-extract engine + image routing rules.

The original seed (0002) only routed PDFs (pdfplumber) for TextExtract.
Image uploads (image/jpeg, image/png, image/webp) hit ``NoRouteFound``.
This migration plugs that gap by registering EasyOCR and giving it
priority 100 for image MIMEs (the launch primary for images).

Also registers a priority-200 rule for application/pdf so EasyOCR is
available as a fallback when pdfplumber returns low-confidence text on
a scanned PDF. The router today picks the first matching priority and
doesn't auto-fall-back, but having the rule in place means a future
"escalate text_extract on low confidence" slice doesn't need a
migration; it just edits the routing logic.

No credentials needed: EasyOCR is in-process. Cost is 0 (no API call).
"""

from __future__ import annotations

from django.db import migrations


ENGINE_NAME = "easyocr"


def seed(apps, schema_editor):  # noqa: ARG001
    Engine = apps.get_model("extraction", "Engine")
    Rule = apps.get_model("extraction", "EngineRoutingRule")

    engine, _ = Engine.objects.update_or_create(
        name=ENGINE_NAME,
        defaults={
            "vendor": "easyocr",
            "model_identifier": "english",
            "adapter_version": "1",
            "capability": "text_extract",
            "cost_per_call_micros": 0,
            "description": (
                "EasyOCR — in-process OCR for images and scanned PDFs. "
                "Images route here at priority 100 (launch primary); PDFs "
                "at priority 200 (fallback when pdfplumber returns low "
                "confidence)."
            ),
        },
    )

    Rule.objects.update_or_create(
        capability="text_extract",
        priority=100,
        engine=engine,
        match_mime_types="image/jpeg,image/png,image/webp",
        defaults={
            "fallback_engine": None,
            "description": "Images run through EasyOCR.",
            "is_active": True,
        },
    )

    Rule.objects.update_or_create(
        capability="text_extract",
        priority=200,
        engine=engine,
        match_mime_types="application/pdf",
        defaults={
            "fallback_engine": None,
            "description": (
                "Scanned-PDF fallback. Lower priority than pdfplumber so "
                "native PDFs go through pdfplumber first; this rule is "
                "ready for the future low-confidence escalation hook."
            ),
            "is_active": True,
        },
    )


def reverse_seed(apps, schema_editor):  # noqa: ARG001
    Engine = apps.get_model("extraction", "Engine")
    Rule = apps.get_model("extraction", "EngineRoutingRule")
    Rule.objects.filter(engine__name=ENGINE_NAME).delete()
    Engine.objects.filter(name=ENGINE_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("extraction", "0004_seed_ollama_structure"),
    ]

    operations = [
        migrations.RunPython(seed, reverse_seed),
    ]
