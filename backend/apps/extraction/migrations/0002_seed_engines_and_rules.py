"""Seed the launch engine catalogue and the default routing rules.

Per ENGINE_REGISTRY.md launch defaults:
  - Native PDF       → pdfplumber (TextExtract)
  - Image            → Anthropic Claude vision (VisionExtract)
  - Raw text         → Anthropic Claude structure (FieldStructure)

The rule catalogue is editable from the super-admin console (later); the
data migration just provides sensible defaults so a fresh deployment routes
correctly.
"""

from __future__ import annotations

from django.db import migrations

ENGINES = [
    {
        "name": "pdfplumber",
        "vendor": "pdfplumber",
        "model_identifier": "0.11",
        "adapter_version": "1",
        "capability": "text_extract",
        "cost_per_call_micros": 0,
        "description": "In-process extraction for native (text-based) PDFs.",
    },
    {
        "name": "anthropic-claude-sonnet-vision",
        "vendor": "anthropic",
        "model_identifier": "claude-sonnet-4-6",
        "adapter_version": "1",
        "capability": "vision_extract",
        "cost_per_call_micros": 8_000,
        "description": "Anthropic Claude Sonnet 4.6 — vision extract for images and scanned PDFs.",
    },
    {
        "name": "anthropic-claude-sonnet-structure",
        "vendor": "anthropic",
        "model_identifier": "claude-sonnet-4-6",
        "adapter_version": "1",
        "capability": "field_structure",
        "cost_per_call_micros": 4_000,
        "description": "Anthropic Claude Sonnet 4.6 — structures raw text into LHDN fields.",
    },
]


RULES = [
    {
        "capability": "text_extract",
        "priority": 100,
        "match_mime_types": "application/pdf",
        "engine_name": "pdfplumber",
        "fallback_engine_name": None,
        "description": "Native PDFs run through pdfplumber.",
    },
    {
        "capability": "vision_extract",
        "priority": 100,
        "match_mime_types": "image/jpeg,image/png,image/webp,application/pdf",
        "engine_name": "anthropic-claude-sonnet-vision",
        "fallback_engine_name": None,
        "description": "Images and scanned PDFs go through Claude vision.",
    },
    {
        "capability": "field_structure",
        "priority": 100,
        "match_mime_types": "*",
        "engine_name": "anthropic-claude-sonnet-structure",
        "fallback_engine_name": None,
        "description": "Raw text is structured into LHDN fields by Claude.",
    },
]


def seed(apps, schema_editor):  # noqa: ARG001
    Engine = apps.get_model("extraction", "Engine")
    Rule = apps.get_model("extraction", "EngineRoutingRule")

    by_name = {}
    for spec in ENGINES:
        engine, _ = Engine.objects.update_or_create(
            name=spec["name"],
            defaults={k: v for k, v in spec.items() if k != "name"},
        )
        by_name[spec["name"]] = engine

    for rule in RULES:
        engine = by_name[rule["engine_name"]]
        fallback = by_name.get(rule["fallback_engine_name"]) if rule["fallback_engine_name"] else None
        Rule.objects.update_or_create(
            capability=rule["capability"],
            priority=rule["priority"],
            engine=engine,
            defaults={
                "match_mime_types": rule["match_mime_types"],
                "fallback_engine": fallback,
                "description": rule["description"],
                "is_active": True,
            },
        )


def reverse_seed(apps, schema_editor):  # noqa: ARG001
    Engine = apps.get_model("extraction", "Engine")
    Rule = apps.get_model("extraction", "EngineRoutingRule")
    Rule.objects.filter(engine__name__in=[e["name"] for e in ENGINES]).delete()
    Engine.objects.filter(name__in=[e["name"] for e in ENGINES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("extraction", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, reverse_seed),
    ]
