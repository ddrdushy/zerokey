"""Enrichment service — match-or-create master records, auto-fill invoices.

The convergence point. ``enrich_invoice(invoice_id)`` is the one entry the
rest of the platform uses; it runs at the end of structuring (right
before validation) and does three things:

  1. Customer master:
       - Match by ``buyer_tin`` (exact). Failing that, by
         ``buyer_legal_name`` exact-case-insensitive against the canonical
         name or any learned alias.
       - On match: increment ``usage_count``, append a new name to
         ``aliases`` if it differs, and copy any *blank* invoice fields
         from the master (auto-fill).
       - On miss: create a new master record from this invoice's buyer
         block.

  2. Item master, per line item:
       - Same matching pattern keyed off ``description``.
       - On match: copy any blank LineItem code fields from the master
         (classification / tax-type / UOM); bump ``usage_count``.
       - On miss: create a new master with the description as canonical
         and the inherited fields blank, ready to learn from later
         corrections.

  3. Audit: a single ``invoice.enriched`` event records counts (matched vs
     created) for both customer + items, and the customer master row id
     so an audit reader can reconstruct what changed without leaking
     buyer names into the payload.

Auto-fill rules:

- We NEVER overwrite a non-empty value the LLM produced. The LLM saw
  the actual document; the master is a pattern from prior invoices,
  weaker evidence on a per-invoice basis.
- We DO fill blanks. That's the entire point: subsequent invoices from
  a known buyer don't have to re-extract the buyer's address.
- When a field is auto-filled, ``per_field_confidence`` for that field
  is set to ``1.0`` — the review UI's three-band scheme renders that as
  green (high confidence), correctly signalling "from your master, not
  a fresh extraction".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.submission.models import Invoice, LineItem

from .models import CustomerMaster, ItemMaster

logger = logging.getLogger(__name__)


# Buyer fields the master knows how to populate. Map: (CustomerMaster
# attribute, Invoice attribute). Iterating this is the only place that
# knows the buyer field set, so adding a new buyer field requires
# changes in exactly one place.
_BUYER_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("legal_name", "buyer_legal_name"),
    ("tin", "buyer_tin"),
    ("registration_number", "buyer_registration_number"),
    ("msic_code", "buyer_msic_code"),
    ("address", "buyer_address"),
    ("phone", "buyer_phone"),
    ("sst_number", "buyer_sst_number"),
    ("country_code", "buyer_country_code"),
)


@dataclass(frozen=True)
class EnrichmentResult:
    customer_matched: bool
    customer_created: bool
    customer_id: UUID | None
    items_matched: int = 0
    items_created: int = 0
    fields_autofilled: list[str] = field(default_factory=list)


def enrich_invoice(invoice_id: UUID | str) -> EnrichmentResult:
    """Run customer + item master enrichment on an Invoice.

    Reload the invoice with line items prefetched so the rule loop sees
    a consistent snapshot. The whole run is wrapped in a single
    transaction so a partial failure doesn't leave orphan masters.
    """
    invoice = Invoice.objects.prefetch_related("line_items").get(id=invoice_id)

    with transaction.atomic():
        customer = _enrich_customer(invoice)
        autofilled = _autofill_buyer(invoice, customer.master) if customer.master else []
        items_matched, items_created = _enrich_line_items(invoice)

        if autofilled:
            invoice.save()

        record_event(
            action_type="invoice.enriched",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="enrichment.pipeline",
            organization_id=str(invoice.organization_id),
            affected_entity_type="Invoice",
            affected_entity_id=str(invoice.id),
            payload={
                "customer_master_id": (str(customer.master.id) if customer.master else None),
                "customer_matched": customer.matched,
                "customer_created": customer.created,
                "items_matched": items_matched,
                "items_created": items_created,
                "fields_autofilled": autofilled,
            },
        )

        # Slice 70 — fire async LHDN TIN verification post-commit if
        # the master is due. The check itself runs out-of-band so the
        # enrichment path doesn't block on the LHDN round-trip.
        if customer.master is not None:
            from . import tin_verification

            if tin_verification.needs_verification(customer.master):
                from .tasks import verify_master_tin

                master_id = str(customer.master.id)
                transaction.on_commit(lambda mid=master_id: verify_master_tin.delay(mid))

    return EnrichmentResult(
        customer_matched=customer.matched,
        customer_created=customer.created,
        customer_id=customer.master.id if customer.master else None,
        items_matched=items_matched,
        items_created=items_created,
        fields_autofilled=list(autofilled),
    )


# --- Customer master --------------------------------------------------------


@dataclass(frozen=True)
class _CustomerOutcome:
    master: CustomerMaster | None
    matched: bool
    created: bool


def _enrich_customer(invoice: Invoice) -> _CustomerOutcome:
    """Find or create a CustomerMaster row for this invoice's buyer.

    Skip entirely when both ``buyer_tin`` and ``buyer_legal_name`` are
    blank — we have nothing to key off, and creating a useless empty
    record would pollute the master table.
    """
    if not invoice.buyer_tin and not invoice.buyer_legal_name:
        return _CustomerOutcome(master=None, matched=False, created=False)

    # Slice 73 — every field this enrichment writes gets an
    # ``extracted`` provenance entry tying it back to the invoice it
    # came from. Future syncs / manual edits / conflict resolutions
    # overlay their own entries; the JSON is keyed by field name so
    # later writes don't lose earlier history per field.
    extracted_at_iso = timezone.now().isoformat()

    def _extracted_entry() -> dict[str, str]:
        return {
            "source": "extracted",
            "extracted_at": extracted_at_iso,
            "invoice_id": str(invoice.id),
        }

    master = _find_customer_master(invoice)
    if master is None:
        provenance: dict[str, dict] = {}
        for master_field, invoice_field in _BUYER_FIELD_MAP:
            if getattr(invoice, invoice_field):
                provenance[master_field] = _extracted_entry()
        master = CustomerMaster.objects.create(
            organization_id=invoice.organization_id,
            legal_name=invoice.buyer_legal_name or "(no name)",
            aliases=[],
            tin=invoice.buyer_tin or "",
            registration_number=invoice.buyer_registration_number or "",
            msic_code=invoice.buyer_msic_code or "",
            address=invoice.buyer_address or "",
            phone=invoice.buyer_phone or "",
            sst_number=invoice.buyer_sst_number or "",
            country_code=invoice.buyer_country_code or "",
            field_provenance=provenance,
            usage_count=1,
            last_used_at=timezone.now(),
        )
        return _CustomerOutcome(master=master, matched=False, created=True)

    # Match: bump usage, learn the alias if the LLM emitted a name variant,
    # and backfill any blank master fields from this invoice (master also
    # learns from new invoices, not just the invoice from the master).
    master.usage_count += 1
    master.last_used_at = timezone.now()
    if (
        invoice.buyer_legal_name
        and invoice.buyer_legal_name != master.legal_name
        and invoice.buyer_legal_name not in master.aliases
    ):
        master.aliases = [*master.aliases, invoice.buyer_legal_name]

    provenance = dict(master.field_provenance or {})
    for master_field, invoice_field in _BUYER_FIELD_MAP:
        if master_field == "legal_name":
            continue
        if getattr(master, master_field):
            continue
        new_value = getattr(invoice, invoice_field) or ""
        if new_value:
            setattr(master, master_field, new_value)
            provenance[master_field] = _extracted_entry()
    master.field_provenance = provenance

    master.save()
    return _CustomerOutcome(master=master, matched=True, created=False)


def _find_customer_master(invoice: Invoice) -> CustomerMaster | None:
    """TIN match first; alias-or-canonical name match second."""
    qs = CustomerMaster.objects.filter(organization_id=invoice.organization_id)

    if invoice.buyer_tin:
        match = qs.filter(tin=invoice.buyer_tin).first()
        if match is not None:
            return match

    if invoice.buyer_legal_name:
        target = invoice.buyer_legal_name.strip()
        match = qs.filter(legal_name__iexact=target).first()
        if match is not None:
            return match
        # Aliases — JSONField __contains is case-sensitive on both
        # Postgres and SQLite, so we do the case-insensitive comparison
        # in Python. The per-tenant alias set is small.
        for record in qs.exclude(aliases__exact=[]):
            if any(alias.lower() == target.lower() for alias in record.aliases):
                return record
    return None


# --- Auto-fill --------------------------------------------------------------


def _autofill_buyer(invoice: Invoice, master: CustomerMaster) -> list[str]:
    """Copy blank invoice fields from the master. Never overwrite.

    Returns the list of field names that were filled so the audit log
    reports what enrichment actually changed.
    """
    filled: list[str] = []
    confidence = dict(invoice.per_field_confidence or {})
    for master_field, invoice_field in _BUYER_FIELD_MAP:
        if master_field == "legal_name":
            # The legal name comes from the document the LLM read; we
            # never silently change what the user sees vs the source.
            continue
        if getattr(invoice, invoice_field):
            continue
        master_value = getattr(master, master_field) or ""
        if not master_value:
            continue
        setattr(invoice, invoice_field, master_value)
        # 1.0 = "from your verified master". The review UI's three-band
        # scheme renders this as the highest-confidence green dot.
        confidence[invoice_field] = 1.0
        filled.append(invoice_field)
    if filled:
        invoice.per_field_confidence = confidence
    return filled


# --- Item master ------------------------------------------------------------


def _enrich_line_items(invoice: Invoice) -> tuple[int, int]:
    """Match-or-create ItemMaster rows for every line item.

    Returns (matched_count, created_count). Line items with empty
    descriptions are skipped — there's nothing meaningful to key off.
    """
    matched = 0
    created = 0
    for line in invoice.line_items.all():
        if not (line.description or "").strip():
            continue

        master, was_created = _find_or_create_item_master(invoice, line)
        master.usage_count += 1
        master.last_used_at = timezone.now()

        if was_created:
            created += 1
        else:
            matched += 1
            _autofill_line_item(line, master)
            line.save()
            _learn_item_alias(master, line.description)

        master.save()
    return matched, created


def _find_or_create_item_master(invoice: Invoice, line: LineItem) -> tuple[ItemMaster, bool]:
    target = line.description.strip()
    qs = ItemMaster.objects.filter(organization_id=invoice.organization_id)

    match = qs.filter(canonical_name__iexact=target).first()
    if match is None:
        for record in qs.exclude(aliases__exact=[]):
            if any(alias.lower() == target.lower() for alias in record.aliases):
                match = record
                break

    if match is not None:
        return match, False

    new = ItemMaster.objects.create(
        organization_id=invoice.organization_id,
        canonical_name=target[:512],
        aliases=[],
        default_classification_code=line.classification_code or "",
        default_tax_type_code=line.tax_type_code or "",
        default_unit_of_measurement=line.unit_of_measurement or "",
        default_unit_price_excl_tax=line.unit_price_excl_tax,
    )
    return new, True


def _autofill_line_item(line: LineItem, master: ItemMaster) -> None:
    """Fill blank LineItem code fields from the master. Never overwrite."""
    if not line.classification_code and master.default_classification_code:
        line.classification_code = master.default_classification_code
    if not line.tax_type_code and master.default_tax_type_code:
        line.tax_type_code = master.default_tax_type_code
    if not line.unit_of_measurement and master.default_unit_of_measurement:
        line.unit_of_measurement = master.default_unit_of_measurement


def _learn_item_alias(master: ItemMaster, description: str) -> None:
    if description == master.canonical_name:
        return
    if description in master.aliases:
        return
    master.aliases = [*master.aliases, description]


# --- Read + edit surface for the Customers UI -------------------------------


# Editable fields on CustomerMaster. The user can correct identifiers the LLM
# got wrong, but ``aliases`` (auto-managed) and ``usage_count`` /
# ``last_used_at`` / ``tin_verification_state`` (system-managed) are not in
# this set — direct edits would corrupt the accumulation logic.
EDITABLE_CUSTOMER_FIELDS: frozenset[str] = frozenset(
    {
        "legal_name",
        "tin",
        "registration_number",
        "msic_code",
        "address",
        "phone",
        "sst_number",
        "country_code",
    }
)


class CustomerUpdateError(Exception):
    """Raised when an update violates the editable-fields allowlist."""


def list_customer_masters(
    *, organization_id: UUID | str, limit: int | None = 200
) -> list[CustomerMaster]:
    """Most-used buyers first. Tenant-scoped — RLS belt-and-suspenders.

    A 200-row default keeps the list page snappy while showing every
    realistic SME's full customer table; an explicit ``limit=None``
    returns everything for export use cases.
    """
    qs = CustomerMaster.objects.filter(organization_id=organization_id).order_by(
        "-usage_count", "legal_name"
    )
    if limit is not None:
        qs = qs[:limit]
    return list(qs)


def get_customer_master(
    *, organization_id: UUID | str, customer_id: UUID | str
) -> CustomerMaster | None:
    return CustomerMaster.objects.filter(organization_id=organization_id, id=customer_id).first()


def list_invoices_for_customer_master(
    *,
    organization_id: UUID | str,
    customer_id: UUID | str,
    limit: int | None = 100,
) -> list:
    """Invoices on this org whose buyer matches the given CustomerMaster.

    Matching mirrors ``_find_customer_master`` (the enrichment-time
    matcher) inverted: TIN-equality wins when the master has a TIN;
    otherwise the master's canonical name OR any learned alias matches
    invoices whose ``buyer_legal_name`` is the same string
    (case-insensitive).

    Returns most-recent-first. Cross-tenant isolation is enforced by
    the explicit ``organization_id`` filter plus RLS on the
    ``invoice`` table.
    """
    # Lazy import to avoid enrichment -> submission cycle at module load.
    from apps.submission.models import Invoice

    master = get_customer_master(organization_id=organization_id, customer_id=customer_id)
    if master is None:
        return []

    qs = Invoice.objects.filter(organization_id=organization_id)
    if master.tin:
        # TIN is the canonical key. Anything matching the TIN is one of
        # the master's invoices regardless of how the LLM wrote the name.
        qs = qs.filter(buyer_tin=master.tin)
    else:
        # No TIN — fall back to the alias / canonical-name set, the same
        # set the enrichment matcher built up from prior LLM extractions.
        names = [master.legal_name, *master.aliases]
        # Case-insensitive match against any of the known names.
        from django.db.models import Q

        name_q = Q()
        for name in names:
            name_q |= Q(buyer_legal_name__iexact=name)
        qs = qs.filter(name_q)

    qs = qs.order_by("-created_at").prefetch_related("line_items")
    if limit is not None:
        qs = qs[:limit]
    return list(qs)


# --- ItemMaster read + edit surface (Slice 83) ----------------------------


# Editable fields on ItemMaster. Defaults the user can correct; aliases /
# usage_count / last_used_at remain system-managed (auto-managed by the
# enrichment matcher and the line-item learner).
EDITABLE_ITEM_FIELDS: frozenset[str] = frozenset(
    {
        "canonical_name",
        "default_msic_code",
        "default_classification_code",
        "default_tax_type_code",
        "default_unit_of_measurement",
        "default_unit_price_excl_tax",
    }
)


class ItemUpdateError(Exception):
    """Editor-facing failure for ItemMaster edits."""


def list_item_masters(*, organization_id: UUID | str, limit: int | None = 200) -> list[ItemMaster]:
    """Most-used items first. Tenant-scoped — RLS belt-and-suspenders."""
    qs = ItemMaster.objects.filter(organization_id=organization_id).order_by(
        "-usage_count", "canonical_name"
    )
    if limit is not None:
        qs = qs[:limit]
    return list(qs)


def get_item_master(*, organization_id: UUID | str, item_id: UUID | str) -> ItemMaster | None:
    return ItemMaster.objects.filter(organization_id=organization_id, id=item_id).first()


@transaction.atomic
def update_item_master(
    *,
    organization_id: UUID | str,
    item_id: UUID | str,
    updates: dict,
    actor_user_id: UUID | str,
) -> ItemMaster:
    """Apply staff edits to an ItemMaster row, audit-logged.

    Renaming the master files the previous canonical name as an alias,
    matching the customer-master rename path. The audit event records
    field names only (values can be commercially sensitive).
    """
    unknown = set(updates.keys()) - EDITABLE_ITEM_FIELDS
    if unknown:
        raise ItemUpdateError(
            f"Cannot edit non-editable fields: {sorted(unknown)}. "
            f"Editable: {sorted(EDITABLE_ITEM_FIELDS)}"
        )

    master = ItemMaster.objects.get(organization_id=organization_id, id=item_id)

    changed: list[str] = []
    rename_old_name: str | None = None
    for field_name, raw_value in updates.items():
        if field_name == "default_unit_price_excl_tax":
            new_value = raw_value if raw_value not in ("", None) else None
        else:
            new_value = "" if raw_value is None else str(raw_value)
        if field_name == "canonical_name" and not str(new_value).strip():
            raise ItemUpdateError("canonical_name cannot be empty.")
        previous = getattr(master, field_name)
        if previous == new_value:
            continue
        if field_name == "canonical_name":
            rename_old_name = previous or ""
        setattr(master, field_name, new_value)
        changed.append(field_name)

    if not changed:
        return master

    if rename_old_name and rename_old_name not in master.aliases:
        master.aliases = [*master.aliases, rename_old_name]

    edited_at_iso = timezone.now().isoformat()
    provenance = dict(master.field_provenance or {})
    for fname in changed:
        provenance[fname] = {
            "source": "manual",
            "entered_at": edited_at_iso,
            "edited_by": str(actor_user_id),
        }
    master.field_provenance = provenance

    master.save()

    record_event(
        action_type="item_master.updated",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="ItemMaster",
        affected_entity_id=str(master.id),
        payload={"changed_fields": sorted(changed)},
    )
    return master


@transaction.atomic
def update_customer_master(
    *,
    organization_id: UUID | str,
    customer_id: UUID | str,
    updates: dict[str, str],
    actor_user_id: UUID | str,
) -> CustomerMaster:
    """Apply staff/user edits to a CustomerMaster row, audit-logged.

    Renaming the master files the previous canonical name as an alias —
    same shape as the ``update_invoice`` master propagation path. The
    audit event records WHICH fields changed (no values: PII).
    """
    unknown = set(updates.keys()) - EDITABLE_CUSTOMER_FIELDS
    if unknown:
        raise CustomerUpdateError(
            f"Cannot edit non-editable fields: {sorted(unknown)}. "
            f"Editable: {sorted(EDITABLE_CUSTOMER_FIELDS)}"
        )

    master = CustomerMaster.objects.get(organization_id=organization_id, id=customer_id)

    changed: list[str] = []
    rename_old_name: str | None = None
    for field_name, raw_value in updates.items():
        new_value = "" if raw_value is None else str(raw_value)
        if field_name == "legal_name" and not new_value.strip():
            raise CustomerUpdateError("legal_name cannot be empty.")
        previous = getattr(master, field_name) or ""
        if previous == new_value:
            continue
        if field_name == "legal_name":
            rename_old_name = previous
        setattr(master, field_name, new_value)
        changed.append(field_name)

    if not changed:
        return master

    if rename_old_name and rename_old_name not in master.aliases:
        master.aliases = [*master.aliases, rename_old_name]

    # Slice 73 — every changed field gets a ``manual`` provenance
    # entry so the UI pill can show "entered manually". Existing
    # extracted/synced provenance for unchanged fields is left
    # alone.
    edited_at_iso = timezone.now().isoformat()
    provenance = dict(master.field_provenance or {})
    for fname in changed:
        provenance[fname] = {
            "source": "manual",
            "entered_at": edited_at_iso,
            "edited_by": str(actor_user_id),
        }
    master.field_provenance = provenance

    master.save()

    record_event(
        action_type="customer_master.updated",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="CustomerMaster",
        affected_entity_id=str(master.id),
        payload={
            # Field names only — values are PII.
            "changed_fields": sorted(changed),
        },
    )
    return master
