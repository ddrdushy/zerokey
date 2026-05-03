"""Seed the launch FeatureFlag declarations.

Per PRODUCT_REQUIREMENTS.md Domain 11 + BUSINESS_MODEL.md the platform
gates features by flag at three scopes (global / plan / org). The
runtime resolver lives in apps.billing.services.is_feature_enabled.

Adding a new flag: append to ``FLAGS`` here AND wire reads via
``is_feature_enabled(...)`` at the call site. Forgetting the seed
means the first read will fail-closed (return False) — surface-able
in the admin /admin/flags page so the operator notices.
"""

from __future__ import annotations

from django.db import migrations

# Each row carries (slug, display_name, default_enabled, category, description).
# Defaults reflect what an *unconfigured* tenant should see — the launch
# tiers in 0003_seed_plans.py override these per-plan.
FLAGS = [
    ("webhooks", "Webhooks", False, "integration", "Outbound webhooks for invoice events."),
    ("sso", "Single sign-on", False, "identity", "OIDC single sign-on for the customer's tenant."),
    ("multi_entity_dashboard", "Multi-entity dashboard", False, "core", "Cross-entity consolidated dashboard for accountant + multi-LE customers."),
    ("advanced_approvals", "Advanced approval chains", False, "core", "Multi-step approval routing on submitted invoices."),
    ("custom_validation_rules", "Custom validation rules", False, "core", "Per-tenant rule overrides on top of the LHDN rule set."),
    ("sandbox_environment", "Sandbox environment", False, "core", "Dedicated sandbox for testing integrations without touching prod."),
    ("api_ingestion", "Public API ingestion", False, "ingestion", "Per-tenant API key for programmatic invoice submission."),
    ("whatsapp_ingestion", "WhatsApp ingestion", False, "ingestion", "Inbound WhatsApp invoice forwarding."),
    ("email_forwarding", "Email forwarding", True, "ingestion", "Inbound email-to-invoice forwarding (per-org address)."),
    ("csv_export", "CSV export", True, "core", "Customer-side CSV export of invoices and audit log."),
    ("priority_support", "Priority support", False, "support", "Faster SLA, chat support."),
    ("consolidated_b2c", "Consolidated B2C invoicing", False, "core", "Bulk B2C invoice generation (retail / e-commerce)."),
    ("ip_allowlisting", "IP allowlisting", False, "security", "Restrict tenant access to allowlisted IPs."),
    ("connectors_sql_account", "SQL Account connector", False, "integration", "CSV-driven SQL Account customer + item sync."),
    ("connectors_autocount", "AutoCount connector", False, "integration", "CSV-driven AutoCount customer + item sync."),
    ("connectors_sage_ubs", "Sage UBS connector", False, "integration", "CSV-driven Sage UBS customer + item sync."),
]


def seed(apps, schema_editor):
    FeatureFlag = apps.get_model("billing", "FeatureFlag")
    for slug, display_name, default_enabled, category, description in FLAGS:
        FeatureFlag.objects.update_or_create(
            slug=slug,
            defaults={
                "display_name": display_name,
                "default_enabled": default_enabled,
                "category": category,
                "description": description,
            },
        )


def unseed(apps, schema_editor):
    FeatureFlag = apps.get_model("billing", "FeatureFlag")
    FeatureFlag.objects.filter(slug__in=[f[0] for f in FLAGS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0005_featureflag_featureflagoverride_overagewaiver"),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
