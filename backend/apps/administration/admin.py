"""Django admin registration for the administration context.

These ModelAdmins are the first super-admin surface for SystemSetting until
the operations console UI lands. The ``values`` field is editable as JSON
so an admin can add/rotate credentials for LHDN, Stripe, etc. without a
code deploy.
"""

from __future__ import annotations

from django.contrib import admin

from .models import (
    ClassificationCode,
    CountryCode,
    MsicCode,
    SystemSetting,
    TaxTypeCode,
    UnitOfMeasureCode,
)


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ("namespace", "description", "updated_at")
    search_fields = ("namespace", "description")
    readonly_fields = ("created_at", "updated_at")
    fields = ("namespace", "values", "description", "updated_by_id", "created_at", "updated_at")


# --- Reference catalog admin views ---------------------------------------------
#
# Read-mostly surfaces; the canonical write path is the
# refresh_reference_catalogs task (Slice 18). Inline editing here is
# emergency-only — toggle ``is_active`` if a code needs to be temporarily
# deprecated before the next monthly refresh.


class _ReferenceAdminBase(admin.ModelAdmin):
    list_filter = ("is_active",)
    readonly_fields = ("last_refreshed_at", "created_at", "updated_at")


@admin.register(MsicCode)
class MsicCodeAdmin(_ReferenceAdminBase):
    list_display = ("code", "description_en", "parent_code", "is_active")
    search_fields = ("code", "description_en", "description_bm")


@admin.register(ClassificationCode)
class ClassificationCodeAdmin(_ReferenceAdminBase):
    list_display = ("code", "description_en", "is_active")
    search_fields = ("code", "description_en", "description_bm")


@admin.register(UnitOfMeasureCode)
class UnitOfMeasureCodeAdmin(_ReferenceAdminBase):
    list_display = ("code", "description_en", "is_active")
    search_fields = ("code", "description_en")


@admin.register(TaxTypeCode)
class TaxTypeCodeAdmin(_ReferenceAdminBase):
    list_display = ("code", "description_en", "applies_to_sst_registered", "is_active")
    search_fields = ("code", "description_en")


@admin.register(CountryCode)
class CountryCodeAdmin(_ReferenceAdminBase):
    list_display = ("code", "name_en", "is_active")
    search_fields = ("code", "name_en")
