"""Tests for the LHDN reference catalogs.

Covers:
  - The seed migration populates every catalog with a non-empty set.
  - Lookup helpers return True for known codes, False for unknown / blank.
  - Inactive rows are NOT considered valid (historical-but-deprecated
    codes don't pass new-invoice validation).
  - The refresh stub stamps ``last_refreshed_at`` and reports counts.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.administration.models import (
    ClassificationCode,
    CountryCode,
    MsicCode,
    TaxTypeCode,
    UnitOfMeasureCode,
)
from apps.administration.services import (
    is_valid_classification,
    is_valid_country,
    is_valid_msic,
    is_valid_tax_type,
    is_valid_uom,
    refresh_reference_catalogs,
)


@pytest.mark.django_db
class TestSeedData:
    def test_msic_seed_present(self) -> None:
        # Common codes from the seed list — these should always be there
        # after migrations, with descriptions populated.
        retail = MsicCode.objects.get(code="47190")
        assert "non-specialized stores" in retail.description_en

        software = MsicCode.objects.get(code="62010")
        assert software.is_active is True

    def test_classification_seed_includes_others(self) -> None:
        """Code 022 = "Others" is the catch-all every customer falls back to."""
        others = ClassificationCode.objects.get(code="022")
        assert others.description_en.lower().startswith("others")

    def test_uom_seed_includes_one_each(self) -> None:
        each = UnitOfMeasureCode.objects.get(code="C62")
        assert each.is_active is True

    def test_tax_type_seed_complete(self) -> None:
        codes = set(TaxTypeCode.objects.values_list("code", flat=True))
        # The full LHDN published list — small enough to ship in one go.
        assert codes >= {"01", "02", "03", "04", "05", "06", "E"}

    def test_country_seed_includes_malaysia_and_partners(self) -> None:
        malaysia = CountryCode.objects.get(code="MY")
        assert malaysia.name_en == "Malaysia"
        # Sample of trade partners we'd expect.
        for code in ("SG", "TH", "ID", "CN", "US", "GB"):
            assert CountryCode.objects.filter(code=code).exists(), code


@pytest.mark.django_db
class TestLookupHelpers:
    def test_known_codes_resolve(self) -> None:
        assert is_valid_msic("62010") is True
        assert is_valid_classification("022") is True
        assert is_valid_uom("KGM") is True
        assert is_valid_tax_type("01") is True
        assert is_valid_country("MY") is True

    def test_unknown_codes_dont_resolve(self) -> None:
        assert is_valid_msic("99999") is False
        assert is_valid_classification("ZZZ") is False
        assert is_valid_uom("nope") is False
        assert is_valid_tax_type("99") is False
        assert is_valid_country("XX") is False

    def test_blank_input_is_false(self) -> None:
        assert is_valid_msic("") is False
        assert is_valid_classification("") is False
        assert is_valid_uom("") is False
        assert is_valid_tax_type("") is False
        assert is_valid_country("") is False

    def test_inactive_rows_are_filtered_out(self) -> None:
        """Deprecated codes don't pass new validation but stay around so
        historical invoices that referenced them remain auditable."""
        TaxTypeCode.objects.filter(code="01").update(is_active=False)
        try:
            assert is_valid_tax_type("01") is False
        finally:
            TaxTypeCode.objects.filter(code="01").update(is_active=True)


@pytest.mark.django_db
class TestRefreshStub:
    def test_refresh_stamps_last_refreshed_at_on_active_rows(self) -> None:
        before = timezone.now()
        # Clear last_refreshed_at on a sample to confirm the stamp updates.
        MsicCode.objects.filter(code="62010").update(last_refreshed_at=None)

        counts = refresh_reference_catalogs()
        # All five catalogs touched.
        assert set(counts) == {"msic", "classification", "uom", "tax_type", "country"}
        # Each catalog stamped > 0 rows.
        for label, n in counts.items():
            assert n > 0, label

        msic = MsicCode.objects.get(code="62010")
        assert msic.last_refreshed_at is not None
        assert msic.last_refreshed_at >= before

    def test_refresh_skips_inactive_rows(self) -> None:
        TaxTypeCode.objects.filter(code="E").update(is_active=False, last_refreshed_at=None)
        try:
            refresh_reference_catalogs()
            inactive = TaxTypeCode.objects.get(code="E")
            assert inactive.last_refreshed_at is None
        finally:
            TaxTypeCode.objects.filter(code="E").update(is_active=True)
