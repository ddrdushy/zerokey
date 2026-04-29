"""Tests for the LHDN reference catalog refresh (Slice 71)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from apps.administration import catalog_refresh
from apps.administration.models import (
    ClassificationCode,
    CountryCode,
    MsicCode,
    TaxTypeCode,
    UnitOfMeasureCode,
)


def _msic_fetcher(rows: list[tuple[str, str]] | None = None):
    rows = rows if rows is not None else [
        ("47190", "Other retail sale in non-specialized stores"),
        ("62010", "Computer programming activities"),
    ]

    def fetch():
        return [
            {"code": c, "description_en": en, "description_bm": ""}
            for c, en in rows
        ]

    return fetch


def _classification_fetcher(rows: list[tuple[str, str]] | None = None):
    rows = rows if rows is not None else [
        ("004", "Consolidated e-invoice"),
        ("022", "Others"),
    ]

    def fetch():
        return [
            {"code": c, "description_en": en, "description_bm": ""}
            for c, en in rows
        ]

    return fetch


def _trivial_other_fetchers() -> dict[str, callable]:
    """Empty fetchers for the catalogs we don't care about in a test.

    The refresh will mark all existing rows in those catalogs as
    inactive — which is fine for tests that only verify the targeted
    catalog's behaviour.
    """
    return {
        "uom": lambda: [],
        "tax_type": lambda: [],
        "country": lambda: [],
    }


# =============================================================================
# refresh_all_catalogs — reconciliation rules
# =============================================================================


@pytest.mark.django_db
class TestRefreshReconciliation:
    def test_inserts_new_codes(self, db) -> None:
        # Start with a clean classification table.
        ClassificationCode.objects.all().delete()
        fetchers = {
            "msic": _msic_fetcher([]),
            "classification": _classification_fetcher(),
            **_trivial_other_fetchers(),
        }
        summary = catalog_refresh.refresh_all_catalogs(fetchers=fetchers)
        assert summary["classification"].added == 2
        assert ClassificationCode.objects.filter(code="004").exists()
        assert ClassificationCode.objects.filter(code="022").exists()

    def test_updates_changed_descriptions(self, db) -> None:
        ClassificationCode.objects.update_or_create(
            code="022",
            defaults={"description_en": "OLD DESC", "is_active": True},
        )
        fetchers = {
            "msic": _msic_fetcher([]),
            "classification": _classification_fetcher(
                [("022", "Others")]
            ),
            **_trivial_other_fetchers(),
        }
        summary = catalog_refresh.refresh_all_catalogs(fetchers=fetchers)
        # 022 is updated; everything else in classification is
        # deactivated.
        assert summary["classification"].updated == 1
        row = ClassificationCode.objects.get(code="022")
        assert row.description_en == "Others"

    def test_deactivates_dropped_codes(self, db) -> None:
        ClassificationCode.objects.update_or_create(
            code="999",
            defaults={"description_en": "Defunct", "is_active": True},
        )
        fetchers = {
            "msic": _msic_fetcher([]),
            "classification": _classification_fetcher(
                [("004", "Consolidated e-invoice")]
            ),
            **_trivial_other_fetchers(),
        }
        summary = catalog_refresh.refresh_all_catalogs(fetchers=fetchers)
        assert summary["classification"].deactivated >= 1
        defunct = ClassificationCode.objects.get(code="999")
        assert defunct.is_active is False
        # Don't delete — historical invoices still reference it.
        assert ClassificationCode.objects.filter(code="999").exists()

    def test_reactivates_returned_codes(self, db) -> None:
        ClassificationCode.objects.update_or_create(
            code="022",
            defaults={
                "description_en": "Others",
                "is_active": False,  # was deactivated previously
            },
        )
        fetchers = {
            "msic": _msic_fetcher([]),
            "classification": _classification_fetcher(
                [("022", "Others")]
            ),
            **_trivial_other_fetchers(),
        }
        summary = catalog_refresh.refresh_all_catalogs(fetchers=fetchers)
        assert summary["classification"].reactivated == 1
        row = ClassificationCode.objects.get(code="022")
        assert row.is_active is True

    def test_extra_field_handled(self, db) -> None:
        # tax_type has the applies_to_sst_registered extra field.
        TaxTypeCode.objects.all().delete()

        def tax_fetcher():
            return [
                {
                    "code": "01",
                    "description_en": "Sales Tax",
                    "applies_to_sst_registered": True,
                },
                {
                    "code": "E",
                    "description_en": "Exempt",
                    "applies_to_sst_registered": False,
                },
            ]

        fetchers = {
            "msic": _msic_fetcher([]),
            "classification": _classification_fetcher([]),
            "uom": lambda: [],
            "tax_type": tax_fetcher,
            "country": lambda: [],
        }
        catalog_refresh.refresh_all_catalogs(fetchers=fetchers)
        assert TaxTypeCode.objects.get(code="01").applies_to_sst_registered is True
        assert TaxTypeCode.objects.get(code="E").applies_to_sst_registered is False

    def test_audit_event_emitted(self, db) -> None:
        from apps.audit.models import AuditEvent

        fetchers = {
            "msic": _msic_fetcher(),
            "classification": _classification_fetcher(),
            **_trivial_other_fetchers(),
        }
        catalog_refresh.refresh_all_catalogs(fetchers=fetchers)
        ev = AuditEvent.objects.filter(
            action_type="administration.catalog_refresh.completed"
        ).first()
        assert ev is not None
        # The payload has per-catalog counts.
        assert "msic" in ev.payload
        assert "classification" in ev.payload

    def test_one_failed_fetcher_doesnt_break_others(self, db) -> None:
        ClassificationCode.objects.update_or_create(
            code="022",
            defaults={"description_en": "Others", "is_active": True},
        )

        def boom():
            raise RuntimeError("network down")

        fetchers = {
            "msic": boom,  # blows up
            "classification": _classification_fetcher(
                [("022", "Others")]
            ),
            **_trivial_other_fetchers(),
        }
        summary = catalog_refresh.refresh_all_catalogs(fetchers=fetchers)
        # MSIC catalog had a failed fetch — should report zeros.
        assert summary["msic"].added == 0
        # Classification still ran successfully.
        assert ClassificationCode.objects.filter(code="022").exists()


# =============================================================================
# default_fetchers — env-driven configuration
# =============================================================================


@pytest.mark.django_db
class TestDefaultFetchers:
    def test_raises_when_url_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("LHDN_CATALOG_BASE_URL", raising=False)
        with pytest.raises(catalog_refresh.CatalogNotConfigured):
            catalog_refresh.default_fetchers()

    def test_returns_http_fetchers_when_url_set(self, monkeypatch) -> None:
        monkeypatch.setenv(
            "LHDN_CATALOG_BASE_URL", "https://example.test/codes"
        )
        fetchers = catalog_refresh.default_fetchers()
        # All 5 catalogs covered.
        assert set(fetchers.keys()) == {
            "msic",
            "classification",
            "uom",
            "tax_type",
            "country",
        }
        # Each fetcher is callable but we don't actually invoke
        # them — that would do real HTTP. The shape is enough.
        for fn in fetchers.values():
            assert callable(fn)


# =============================================================================
# Celery task wrapper
# =============================================================================


@pytest.mark.django_db
class TestRefreshTask:
    def test_unconfigured_logs_audit_skip(self, monkeypatch) -> None:
        from apps.administration.tasks import refresh_reference_catalogs
        from apps.audit.models import AuditEvent

        monkeypatch.delenv("LHDN_CATALOG_BASE_URL", raising=False)
        result = refresh_reference_catalogs()
        assert result == {}
        ev = AuditEvent.objects.filter(
            action_type="administration.catalog_refresh.skipped"
        ).first()
        assert ev is not None
        assert "LHDN_CATALOG_BASE_URL" in ev.payload["reason"]
