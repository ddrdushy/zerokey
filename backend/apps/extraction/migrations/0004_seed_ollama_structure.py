"""Register the Ollama FieldStructure engine + a high-priority routing rule.

Why this lands as a separate migration rather than amending the original
seed: the original 0002 captures the *Anthropic-only* launch shape, and
keeping that history readable matters more than collapsing migrations.
The router prefers lower-priority numbers, so giving Ollama priority 50
(vs Anthropic's 100) makes it the default whenever it's configured —
the existing Anthropic engine remains as fallback.

No credentials seeded here. The host (cloud vs local), API key, and
model live in ``Engine.credentials`` and are populated either from
``.env`` (dev) or from the operations console (production). A fresh
deployment with neither configured returns ``EngineUnavailable`` from
the adapter and routing falls through to the next rule (Anthropic).

Reverse: removes the engine row + rule. Existing routing falls back to
Anthropic with priority 100.
"""

from __future__ import annotations

from django.db import migrations


ENGINE_NAME = "ollama-structure"


def seed(apps, schema_editor):  # noqa: ARG001
    Engine = apps.get_model("extraction", "Engine")
    Rule = apps.get_model("extraction", "EngineRoutingRule")

    engine, _ = Engine.objects.update_or_create(
        name=ENGINE_NAME,
        defaults={
            "vendor": "ollama",
            "model_identifier": "configurable",
            "adapter_version": "1",
            "capability": "field_structure",
            "cost_per_call_micros": 0,
            "description": (
                "Ollama field-structure adapter. Same code path for local "
                "(http://host.docker.internal:11434) and cloud "
                "(https://ollama.com) — host + api_key + model live in "
                "Engine.credentials."
            ),
        },
    )

    Rule.objects.update_or_create(
        capability="field_structure",
        priority=50,
        engine=engine,
        defaults={
            "match_mime_types": "*",
            "fallback_engine": None,
            "description": (
                "Prefer Ollama for field structuring when configured; "
                "Anthropic remains at priority 100 as fallback."
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
        ("extraction", "0003_engine_credentials"),
    ]

    operations = [
        migrations.RunPython(seed, reverse_seed),
    ]
