"""Seed the launch plan catalog.

Per BUSINESS_MODEL.md the launch tiers are Trial (14-day) → Solo →
Team → Growth → Enterprise. Pricing is in MYR. Each plan is shipped
at version=1; future price changes ship as v2 alongside.

Adding a new plan / new version: append to ``PLANS`` and write a new
migration. Never edit a published plan in-place — historical
Subscriptions reference (slug, version) for accurate replay.
"""

from __future__ import annotations

from django.db import migrations

PLANS = [
    {
        "slug": "trial",
        "version": 1,
        "name": "Trial",
        "tier": "trial",
        "description": "14-day free trial with full Solo features.",
        "monthly_price_cents": 0,
        "annual_price_cents": 0,
        "billing_currency": "MYR",
        "included_invoices_per_month": 50,
        "per_overage_cents": 0,
        "included_users": 2,
        "included_api_keys": 1,
        "features": {
            "webhooks": False,
            "sso": False,
            "consolidated_b2c": False,
            "priority_support": False,
        },
        "is_active": True,
        "is_public": False,  # Auto-applied on signup; not on pricing page.
    },
    {
        "slug": "solo",
        "version": 1,
        "name": "Solo",
        "tier": "solo",
        "description": "For founders and freelancers.",
        "monthly_price_cents": 4900,  # MYR 49
        "annual_price_cents": 49000,  # MYR 490 (~17% off)
        "billing_currency": "MYR",
        "included_invoices_per_month": 100,
        "per_overage_cents": 50,  # MYR 0.50 per overage invoice
        "included_users": 1,
        "included_api_keys": 2,
        "features": {
            "webhooks": False,
            "sso": False,
            "consolidated_b2c": False,
            "priority_support": False,
        },
        "is_active": True,
        "is_public": True,
    },
    {
        "slug": "team",
        "version": 1,
        "name": "Team",
        "tier": "team",
        "description": "For SMEs with a finance team.",
        "monthly_price_cents": 14900,  # MYR 149
        "annual_price_cents": 149000,
        "billing_currency": "MYR",
        "included_invoices_per_month": 500,
        "per_overage_cents": 30,  # MYR 0.30 per overage invoice
        "included_users": 5,
        "included_api_keys": 5,
        "features": {
            "webhooks": True,
            "sso": False,
            "consolidated_b2c": True,
            "priority_support": False,
        },
        "is_active": True,
        "is_public": True,
    },
    {
        "slug": "growth",
        "version": 1,
        "name": "Growth",
        "tier": "growth",
        "description": "For larger Malaysian SMEs scaling on LHDN.",
        "monthly_price_cents": 39900,  # MYR 399
        "annual_price_cents": 399000,
        "billing_currency": "MYR",
        "included_invoices_per_month": 2500,
        "per_overage_cents": 20,  # MYR 0.20 per overage invoice
        "included_users": 25,
        "included_api_keys": 25,
        "features": {
            "webhooks": True,
            "sso": True,
            "consolidated_b2c": True,
            "priority_support": True,
        },
        "is_active": True,
        "is_public": True,
    },
    {
        "slug": "enterprise",
        "version": 1,
        "name": "Enterprise",
        "tier": "enterprise",
        "description": "Custom volume, dedicated support, BYO contracts.",
        "monthly_price_cents": 0,  # 0 = "contact sales"
        "annual_price_cents": 0,
        "billing_currency": "MYR",
        "included_invoices_per_month": 0,  # 0 = unlimited
        "per_overage_cents": 0,
        "included_users": 0,  # 0 = unlimited
        "included_api_keys": 0,
        "features": {
            "webhooks": True,
            "sso": True,
            "consolidated_b2c": True,
            "priority_support": True,
            "custom_contracts": True,
            "dedicated_support": True,
        },
        "is_active": True,
        "is_public": True,
    },
]


def seed(apps, schema_editor):  # noqa: ARG001
    Plan = apps.get_model("billing", "Plan")
    for spec in PLANS:
        Plan.objects.update_or_create(
            slug=spec["slug"],
            version=spec["version"],
            defaults={k: v for k, v in spec.items() if k not in {"slug", "version"}},
        )


def reverse_seed(apps, schema_editor):  # noqa: ARG001
    Plan = apps.get_model("billing", "Plan")
    Plan.objects.filter(slug__in=[p["slug"] for p in PLANS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0002_billing_rls"),
    ]

    operations = [
        migrations.RunPython(seed, reverse_seed),
    ]
