"""Register the RapidOCR text-extract engine + image routing (Slice 72).

RapidOCR (PP-OCR via ONNX Runtime) replaces EasyOCR as the launch
primary for images and as the scanned-PDF OCR fallback. EasyOCR's
seeded routes are demoted to a higher priority number (lower
priority) so the router falls through to it only when RapidOCR is
unavailable.

Why a sibling, not a replacement: defensive degradation. If
``rapidocr-onnxruntime`` fails to load (rare but possible —
ARM-only model wheels can drift), EasyOCR keeps OCR working.
The cost of carrying both engines is ~300MB of disk, which is
worth it for the resilience.

Routing priority after this migration:
  TextExtract / image/jpeg|png|webp:
    50  rapidocr   ← new launch primary
    100 easyocr    ← demoted to fallback
  TextExtract / application/pdf:
    100 pdfplumber ← unchanged: native PDFs win here first
    150 rapidocr   ← OCR fallback for scanned PDFs (new)
    200 easyocr    ← unchanged
"""

from __future__ import annotations

from django.db import migrations


ENGINE_NAME = "rapidocr"


def seed(apps, schema_editor):  # noqa: ARG001
    Engine = apps.get_model("extraction", "Engine")
    Rule = apps.get_model("extraction", "EngineRoutingRule")

    engine, _ = Engine.objects.update_or_create(
        name=ENGINE_NAME,
        defaults={
            "vendor": "rapidocr",
            "model_identifier": "pp-ocrv4-en",
            "adapter_version": "1",
            "capability": "text_extract",
            "cost_per_call_micros": 0,
            "description": (
                "RapidOCR — PP-OCRv4 detection + recognition models served "
                "via ONNX Runtime. Launch primary for images and the OCR "
                "lane for scanned PDFs. Stronger table-structure preservation "
                "than EasyOCR, ~200MB smaller install. EasyOCR remains the "
                "fallback when this engine is unavailable."
            ),
        },
    )

    # Image route at priority 50 — wins over EasyOCR (100).
    Rule.objects.update_or_create(
        capability="text_extract",
        priority=50,
        engine=engine,
        match_mime_types="image/jpeg,image/png,image/webp,image/tiff",
        defaults={
            "fallback_engine": None,
            "description": "Images route through RapidOCR (PP-OCRv4 via ONNX).",
            "is_active": True,
        },
    )

    # PDF route at priority 150 — between pdfplumber (100, the native
    # text-extract winner) and EasyOCR (200, the historic OCR fallback).
    # When pdfplumber returns low confidence on a scanned PDF, the future
    # escalation hook can promote this rule first.
    Rule.objects.update_or_create(
        capability="text_extract",
        priority=150,
        engine=engine,
        match_mime_types="application/pdf",
        defaults={
            "fallback_engine": None,
            "description": (
                "Scanned-PDF OCR (PP-OCR via ONNX). Tries before EasyOCR "
                "for better table-row preservation."
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
        ("extraction", "0005_seed_easyocr"),
    ]

    operations = [
        migrations.RunPython(seed, reverse_seed),
    ]
