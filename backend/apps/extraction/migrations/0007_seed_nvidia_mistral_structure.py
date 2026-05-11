"""Register the NVIDIA NIM Mistral FieldStructure engine + priority-25 rule.

Slice 108. Adds a third structuring engine alongside Ollama (50) and
Anthropic Claude (100). Sits at priority 25 so the router tries it
first when configured; if the API key is absent or NIM is unreachable
the adapter raises ``EngineUnavailable`` and the chain falls through
to Ollama and then Anthropic.

No credentials seeded here. Host, API key, and model live in
``Engine.credentials`` and are populated either from ``.env`` (dev) or
from the operations console. A fresh deployment with no key returns
``EngineUnavailable`` immediately and the next rule takes over.
"""

from __future__ import annotations

from django.db import migrations


ENGINE_NAME = "nvidia-mistral-structure"


def seed(apps, schema_editor):  # noqa: ARG001
    Engine = apps.get_model("extraction", "Engine")
    Rule = apps.get_model("extraction", "EngineRoutingRule")

    engine, _ = Engine.objects.update_or_create(
        name=ENGINE_NAME,
        defaults={
            "vendor": "nvidia-nim",
            "model_identifier": "configurable",
            "adapter_version": "1",
            "capability": "field_structure",
            "cost_per_call_micros": 0,
            "description": (
                "NVIDIA NIM-hosted model adapter for field structuring. "
                "Default model is nvidia/llama-3.3-nemotron-super-49b-v1 "
                "(cold-start <1s, full-invoice ~15s). The slug is "
                "'nvidia-mistral-structure' for historical reasons; the "
                "actual model is per-credential. Endpoint is OpenAI-"
                "compatible /v1/chat/completions."
            ),
        },
    )

    Rule.objects.update_or_create(
        capability="field_structure",
        priority=25,
        engine=engine,
        defaults={
            "match_mime_types": "*",
            "fallback_engine": None,
            "description": (
                "Prefer NVIDIA NIM when configured; falls through to "
                "Ollama (50) then Anthropic Claude (100) if unavailable."
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
        ("extraction", "0006_seed_rapidocr"),
    ]

    operations = [
        migrations.RunPython(seed, reverse_seed),
    ]
