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


# --- LHDN reference catalogs ----------------------------------------------------
#
# These are the LHDN-published lookup lists every invoice references: MSIC
# codes (industry classification), classification codes (e-invoice
# category), UOM codes, tax-type codes, country codes. They're platform-
# wide reference data (NOT tenant-scoped) — every customer's validation
# rules read from the same tables. The super-admin refresh job (placeholder
# in apps.administration.tasks) pulls fresh copies from LHDN monthly and
# upserts; the seed migration ships a representative subset for first
# boot before the refresh has run.
#
# Each catalog row has ``last_refreshed_at`` so an audit reader can see
# which version of the LHDN published catalog the row was reconciled
# against. ``active=False`` rows are kept around so historical invoices
# that referenced a now-deprecated code still verify — see
# LHDN_INTEGRATION.md "reference data caching".


class _ReferenceMeta(models.Model):
    """Mixin for the reference catalog tables. Common fields, no DB table."""

    is_active = models.BooleanField(default=True, db_index=True)
    last_refreshed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class MsicCode(_ReferenceMeta):
    """Malaysia Standard Industrial Classification — 5-digit code per LHDN.

    The canonical list lives at LHDN; we cache a representative subset
    in seed data and refresh from the published catalog monthly. The
    English description is authoritative; ``description_bm`` (Bahasa
    Malaysia) is populated where we have it.
    """

    code = models.CharField(max_length=8, primary_key=True)
    description_en = models.CharField(max_length=512)
    description_bm = models.CharField(max_length=512, blank=True)
    parent_code = models.CharField(max_length=8, blank=True, db_index=True)

    class Meta:
        db_table = "msic_code"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} {self.description_en[:40]}"


class ClassificationCode(_ReferenceMeta):
    """LHDN e-invoice classification (Category) code.

    Used per LineItem to identify the type of supply for tax-treatment
    purposes. Distinct from MSIC (which classifies the supplier's
    business) — same row may carry both.
    """

    code = models.CharField(max_length=16, primary_key=True)
    description_en = models.CharField(max_length=512)
    description_bm = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "classification_code"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} {self.description_en[:40]}"


class UnitOfMeasureCode(_ReferenceMeta):
    """UN/CEFACT UOM code, the LHDN-accepted set.

    Examples: ``C62`` (one/each), ``KGM`` (kilogram), ``LTR`` (litre),
    ``MTR`` (metre), ``ZZ`` (other / not classified).
    """

    code = models.CharField(max_length=16, primary_key=True)
    description_en = models.CharField(max_length=255)

    class Meta:
        db_table = "unit_of_measure_code"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} {self.description_en}"


class TaxTypeCode(_ReferenceMeta):
    """LHDN-published tax type code.

    Examples: ``01`` (Sales Tax), ``02`` (Service Tax), ``E`` (Exempt),
    ``06`` (Not Applicable). The ``applies_to_sst_registered`` flag
    feeds into the SST consistency rule — registered suppliers should
    use 01/02 on taxable lines, not E or 06.
    """

    code = models.CharField(max_length=8, primary_key=True)
    description_en = models.CharField(max_length=255)
    applies_to_sst_registered = models.BooleanField(default=True)

    class Meta:
        db_table = "tax_type_code"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} {self.description_en}"


class CountryCode(_ReferenceMeta):
    """ISO 3166-1 alpha-2 country code.

    Used on the buyer block when the buyer is foreign. Full ISO list is
    250 codes — ships in seed data as one block since the list is
    stable and small.
    """

    code = models.CharField(max_length=2, primary_key=True)
    name_en = models.CharField(max_length=128)

    class Meta:
        db_table = "country_code"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} {self.name_en}"
