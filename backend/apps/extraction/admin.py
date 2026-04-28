"""Django admin registration for the extraction context.

The ``Engine`` editor is the super-admin's surface for rotating per-engine
vendor credentials without redeploying. The ``credentials`` JSON field is
editable inline; populated values take precedence over the matching env
var fallback.
"""

from __future__ import annotations

from django.contrib import admin

from .models import Engine, EngineCall, EngineRoutingRule


@admin.register(Engine)
class EngineAdmin(admin.ModelAdmin):
    list_display = ("name", "vendor", "capability", "status", "adapter_version")
    list_filter = ("capability", "status", "vendor")
    search_fields = ("name", "vendor", "model_identifier")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("name", "vendor", "model_identifier", "adapter_version")}),
        ("Routing", {"fields": ("capability", "status", "cost_per_call_micros")}),
        (
            "Credentials",
            {
                "fields": ("credentials",),
                "description": (
                    "Per-engine credentials (api keys, endpoints). Resolves DB → "
                    "env var fallback. Plaintext today; KMS-backed encryption "
                    "lands with the signing service. Do NOT paste into chat."
                ),
            },
        ),
        ("Description", {"fields": ("description",)}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(EngineRoutingRule)
class EngineRoutingRuleAdmin(admin.ModelAdmin):
    list_display = ("capability", "priority", "engine", "match_mime_types", "is_active")
    list_filter = ("capability", "is_active")
    search_fields = ("engine__name", "match_mime_types", "description")
    readonly_fields = ("created_at", "updated_at")


@admin.register(EngineCall)
class EngineCallAdmin(admin.ModelAdmin):
    list_display = ("engine", "outcome", "duration_ms", "confidence", "started_at")
    list_filter = ("outcome", "engine")
    search_fields = ("engine__name", "request_id", "error_class")
    readonly_fields = (
        "engine",
        "request_id",
        "organization_id",
        "started_at",
        "duration_ms",
        "outcome",
        "error_class",
        "cost_micros",
        "confidence",
        "diagnostics",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
