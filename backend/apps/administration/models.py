"""Models for the administration context.

This context owns platform-level configuration that the super-admin manages
from the operations console. Per ROADMAP.md Phase 5, the console exists as
an editor over these tables; the data model lands first so the rest of the
platform can read from it before the UI exists.

Cross-context model imports are forbidden — call ``apps.administration.services``
from outside this app.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class SystemSetting(models.Model):
    """Platform-wide configuration namespace edited by the super-admin.

    One row per integration namespace (e.g. ``"lhdn"``, ``"stripe"``). The
    ``values`` JSON dict carries the namespace's keys (``client_id``,
    ``base_url``, etc.). Resolution order at the call site is DB ⇒
    environment-variable fallback ⇒ default ⇒ raise.

    Why a single ``values`` JSONField rather than one row per (namespace,
    key) pair: the super-admin edits these as a set ("LHDN credentials"),
    not one key at a time, and atomic-update semantics fit a single row.

    Plaintext for now; KMS-backed envelope encryption lands alongside the
    signing service. Do NOT log this row — its values are credentials.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Stable namespace identifier ("lhdn", "stripe"). Single row per
    # namespace; the super-admin updates the values atomically.
    namespace = models.SlugField(max_length=64, unique=True)

    values = models.JSONField(default=dict, blank=True)
    description = models.CharField(max_length=255, blank=True)

    # Audit-ish breadcrumb for the operations console; the authoritative
    # record is in ``audit_event`` (every edit emits a system event).
    updated_by_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "system_setting"
        ordering = ["namespace"]

    def __str__(self) -> str:
        return f"SystemSetting({self.namespace})"
