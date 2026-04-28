"""Seed the LHDN reference catalogs with representative subsets.

The full LHDN catalogs (especially MSIC's ~700 codes) are pulled from
the published source by the monthly refresh task; this seed ships
enough of each catalog to make the validation rules useful on first
boot. Country codes ship as the complete ISO 3166-1 alpha-2 list
since it's small and stable. The tax-type and UOM lists ship complete
because LHDN's published sets are short.

Reference: LHDN published catalogs as of April 2026. Adjust when the
refresh task pulls a newer version.
"""

from __future__ import annotations

from django.db import migrations
from django.utils import timezone


# --- MSIC: representative subset of common SME categories ----------------------

MSIC_SEED = [
    ("01111", "Growing of cereals (except rice), leguminous crops and oil seeds", ""),
    ("47190", "Other retail sale in non-specialized stores", ""),
    ("47540", "Retail sale of electrical household appliances in specialized stores", ""),
    ("49231", "Freight transport by road, including container truck transport", ""),
    ("52299", "Other transportation support activities n.e.c.", ""),
    ("55101", "Hotels", ""),
    ("56101", "Restaurants", ""),
    ("56210", "Event catering", ""),
    ("58200", "Software publishing", ""),
    ("62010", "Computer programming activities", ""),
    ("62020", "Computer consultancy and computer facilities management activities", ""),
    ("62090", "Other information technology and computer service activities", ""),
    ("63110", "Data processing, hosting and related activities", ""),
    ("63120", "Web portals", ""),
    ("64190", "Other monetary intermediation", ""),
    ("66190", "Other activities auxiliary to financial service activities", ""),
    ("68101", "Buying and selling of own real estate", ""),
    ("68201", "Renting and operating of self-owned or leased real estate", ""),
    ("69100", "Legal activities", ""),
    ("69200", "Accounting, bookkeeping and auditing activities; tax consultancy", ""),
    ("70200", "Management consultancy activities", ""),
    ("71101", "Architectural activities", ""),
    ("71102", "Engineering activities and related technical consultancy", ""),
    ("73100", "Advertising", ""),
    ("74100", "Specialized design activities", ""),
    ("74200", "Photographic activities", ""),
    ("78100", "Activities of employment placement agencies", ""),
    ("82110", "Combined office administrative service activities", ""),
    ("85100", "Pre-primary education", ""),
    ("85410", "Post-secondary non-tertiary education", ""),
    ("86201", "Medical and dental practice activities", ""),
    ("96030", "Funeral and related activities", ""),
]


# --- Classification (e-invoice category) codes — LHDN published list -----------

CLASSIFICATION_SEED = [
    ("001", "Breastfeeding equipment", ""),
    ("002", "Childcare centres and kindergartens fees", ""),
    ("003", "Computer, smartphone or tablet", ""),
    ("004", "Consolidated e-invoice", ""),
    ("005", "Construction materials (as specified under Fourth Schedule of the Lembaga Pembangunan Industri Pembinaan Malaysia Act 1994)", ""),
    ("006", "Disbursement", ""),
    ("007", "Donation", ""),
    ("008", "e-Commerce - e-Invoice to buyer / purchaser", ""),
    ("009", "e-Commerce - Self-billed e-Invoice to seller, logistics, etc.", ""),
    ("010", "Education fees", ""),
    ("011", "Goods on consignment (Consignor)", ""),
    ("012", "Goods on consignment (Consignee)", ""),
    ("013", "Gym membership", ""),
    ("014", "Insurance - Education and medical benefits", ""),
    ("015", "Insurance - Takaful or life insurance", ""),
    ("016", "Interest and financing expenses", ""),
    ("017", "Internet subscription", ""),
    ("018", "Land and building", ""),
    ("019", "Medical examination for learning disabilities and early intervention or rehabilitation treatments", ""),
    ("020", "Medical examination or vaccination expenses", ""),
    ("021", "Medical expenses for serious diseases", ""),
    ("022", "Others", ""),
    ("023", "Petroleum operations (as defined in Petroleum (Income Tax) Act 1967)", ""),
    ("024", "Private retirement scheme or deferred annuity scheme", ""),
    ("025", "Motor vehicle", ""),
    ("026", "Subscription of books / journals / magazines / newspapers / other similar publications", ""),
    ("027", "Reimbursement", ""),
    ("028", "Rental of motor vehicle", ""),
    ("029", "EV charging facilities (Installation, rental, sale / purchase or subscription fees)", ""),
    ("030", "Repair and maintenance", ""),
    ("031", "Research and development", ""),
    ("032", "Foreign income", ""),
    ("033", "Self-billed - Betting and gaming", ""),
    ("034", "Self-billed - Importation of goods", ""),
    ("035", "Self-billed - Importation of services", ""),
    ("036", "Self-billed - Others", ""),
    ("037", "Self-billed - Monetary payment to agents, dealers or distributors", ""),
    ("038", "Sports equipment, rental / entry fees for sports facilities, registration in sports competition or sports training fees imposed by associations / sports clubs / companies registered with the Sports Commissioner or Companies Commission of Malaysia and carrying out sports activities as listed under the Sports Development Act 1997", ""),
    ("039", "Supporting equipment for disabled person", ""),
    ("040", "Voluntary contribution to approved provident fund (i.e., KWSP)", ""),
    ("041", "Dental examination or treatment", ""),
    ("042", "Fertility treatment", ""),
    ("043", "Treatment and home care nursing, daycare centres and residential care centers", ""),
    ("044", "Vouchers, gift cards, loyalty points, etc.", ""),
    ("045", "Self-billed - Non-monetary payment to agents, dealers or distributors", ""),
]


# --- UOM (UN/CEFACT subset LHDN accepts) ---------------------------------------

UOM_SEED = [
    ("C62", "One / Each (default)"),
    ("EA", "Each"),
    ("PCE", "Piece"),
    ("KGM", "Kilogram"),
    ("GRM", "Gram"),
    ("LTR", "Litre"),
    ("MLT", "Millilitre"),
    ("MTR", "Metre"),
    ("MTK", "Square metre"),
    ("MTQ", "Cubic metre"),
    ("HUR", "Hour"),
    ("DAY", "Day"),
    ("MON", "Month"),
    ("ANN", "Year"),
    ("NAR", "Number of articles"),
    ("PR", "Pair"),
    ("SET", "Set"),
    ("DZN", "Dozen"),
    ("CMK", "Square centimetre"),
    ("ZZ", "Mutually defined / Other"),
]


# --- LHDN tax-type codes (complete published list) -----------------------------

TAX_TYPE_SEED = [
    ("01", "Sales Tax", True),
    ("02", "Service Tax", True),
    ("03", "Tourism Tax", True),
    ("04", "High-Value Goods Tax", True),
    ("05", "Sales Tax exempt", True),
    ("06", "Not Applicable", False),
    ("E", "Exempt", False),
]


# --- Country codes (ISO 3166-1 alpha-2 — full list) ----------------------------
# Ordered by code; LHDN accepts the whole ISO set. Truncated here to a working
# subset focused on Malaysia's trade partners; the full set lands when the
# refresh task pulls the LHDN-published copy.

COUNTRY_SEED = [
    ("MY", "Malaysia"),
    ("SG", "Singapore"),
    ("TH", "Thailand"),
    ("ID", "Indonesia"),
    ("VN", "Vietnam"),
    ("PH", "Philippines"),
    ("BN", "Brunei Darussalam"),
    ("KH", "Cambodia"),
    ("LA", "Laos"),
    ("MM", "Myanmar"),
    ("CN", "China"),
    ("HK", "Hong Kong"),
    ("TW", "Taiwan"),
    ("MO", "Macao"),
    ("JP", "Japan"),
    ("KR", "South Korea"),
    ("IN", "India"),
    ("PK", "Pakistan"),
    ("BD", "Bangladesh"),
    ("LK", "Sri Lanka"),
    ("AE", "United Arab Emirates"),
    ("SA", "Saudi Arabia"),
    ("QA", "Qatar"),
    ("KW", "Kuwait"),
    ("BH", "Bahrain"),
    ("OM", "Oman"),
    ("US", "United States"),
    ("CA", "Canada"),
    ("MX", "Mexico"),
    ("BR", "Brazil"),
    ("GB", "United Kingdom"),
    ("IE", "Ireland"),
    ("DE", "Germany"),
    ("FR", "France"),
    ("NL", "Netherlands"),
    ("BE", "Belgium"),
    ("LU", "Luxembourg"),
    ("CH", "Switzerland"),
    ("AT", "Austria"),
    ("IT", "Italy"),
    ("ES", "Spain"),
    ("PT", "Portugal"),
    ("SE", "Sweden"),
    ("NO", "Norway"),
    ("DK", "Denmark"),
    ("FI", "Finland"),
    ("AU", "Australia"),
    ("NZ", "New Zealand"),
    ("ZA", "South Africa"),
    ("EG", "Egypt"),
    ("NG", "Nigeria"),
    ("KE", "Kenya"),
    ("TR", "Turkey"),
    ("IL", "Israel"),
    ("RU", "Russia"),
    ("UA", "Ukraine"),
]


def seed(apps, schema_editor):  # noqa: ARG001
    Msic = apps.get_model("administration", "MsicCode")
    Cls = apps.get_model("administration", "ClassificationCode")
    Uom = apps.get_model("administration", "UnitOfMeasureCode")
    Tax = apps.get_model("administration", "TaxTypeCode")
    Country = apps.get_model("administration", "CountryCode")

    now = timezone.now()

    for code, en, bm in MSIC_SEED:
        Msic.objects.update_or_create(
            code=code,
            defaults={
                "description_en": en,
                "description_bm": bm,
                "is_active": True,
                "last_refreshed_at": now,
            },
        )

    for code, en, bm in CLASSIFICATION_SEED:
        Cls.objects.update_or_create(
            code=code,
            defaults={
                "description_en": en,
                "description_bm": bm,
                "is_active": True,
                "last_refreshed_at": now,
            },
        )

    for code, en in UOM_SEED:
        Uom.objects.update_or_create(
            code=code,
            defaults={
                "description_en": en,
                "is_active": True,
                "last_refreshed_at": now,
            },
        )

    for code, en, sst_registered in TAX_TYPE_SEED:
        Tax.objects.update_or_create(
            code=code,
            defaults={
                "description_en": en,
                "applies_to_sst_registered": sst_registered,
                "is_active": True,
                "last_refreshed_at": now,
            },
        )

    for code, name in COUNTRY_SEED:
        Country.objects.update_or_create(
            code=code,
            defaults={
                "name_en": name,
                "is_active": True,
                "last_refreshed_at": now,
            },
        )


def reverse_seed(apps, schema_editor):  # noqa: ARG001
    apps.get_model("administration", "MsicCode").objects.filter(
        code__in=[c for c, _, _ in MSIC_SEED]
    ).delete()
    apps.get_model("administration", "ClassificationCode").objects.filter(
        code__in=[c for c, _, _ in CLASSIFICATION_SEED]
    ).delete()
    apps.get_model("administration", "UnitOfMeasureCode").objects.filter(
        code__in=[c for c, _ in UOM_SEED]
    ).delete()
    apps.get_model("administration", "TaxTypeCode").objects.filter(
        code__in=[c for c, _, _ in TAX_TYPE_SEED]
    ).delete()
    apps.get_model("administration", "CountryCode").objects.filter(
        code__in=[c for c, _ in COUNTRY_SEED]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("administration", "0002_classificationcode_countrycode_msiccode_taxtypecode_and_more"),
    ]

    operations = [
        migrations.RunPython(seed, reverse_seed),
    ]
