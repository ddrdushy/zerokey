"""Django admin registration for the administration context.

These ModelAdmins are the first super-admin surface for SystemSetting until
the operations console UI lands. The ``values`` field is editable as JSON
so an admin can add/rotate credentials for LHDN, Stripe, etc. without a
code deploy.
"""

from __future__ import annotations

from django.contrib import admin

from .models import SystemSetting


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ("namespace", "description", "updated_at")
    search_fields = ("namespace", "description")
    readonly_fields = ("created_at", "updated_at")
    fields = ("namespace", "values", "description", "updated_by_id", "created_at", "updated_at")
