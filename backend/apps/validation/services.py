"""Validation service — runs rules, persists issues, audits the run.

The convergence point. Every other context that wants validation calls
``validate_invoice(invoice_id)`` rather than touching ``ValidationIssue``
directly.

Idempotency: a re-run of validation on the same invoice replaces the
prior issue set rather than accumulating duplicates. The replacement
happens inside one transaction so a failure mid-run never leaves a
half-written set on the row.

Audit: each run emits exactly one ``invoice.validated`` event whose
payload reports the issue counts by severity (no message text, since
messages can carry user-facing data). Per ``ingestion.job.errored``-style
convention the action_type is past-tense; the *act of running validation*
is the audited event, regardless of whether issues were found.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.submission.models import Invoice

from .models import ValidationIssue
from .rules import Issue, run_all_rules

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationResult:
    invoice_id: UUID
    issue_count: int
    error_count: int
    warning_count: int
    info_count: int

    @property
    def has_blocking_errors(self) -> bool:
        return self.error_count > 0


def validate_invoice(invoice_id: UUID | str) -> ValidationResult:
    """Run every rule on the invoice and persist the resulting issue set.

    Replaces any prior issues for the invoice atomically. Returns a
    summary with per-severity counts so callers (the structuring
    pipeline, the API, the future review UI) can decide whether to
    proceed with submission.
    """
    invoice = Invoice.objects.prefetch_related("line_items").get(id=invoice_id)

    raw_issues = run_all_rules(invoice)
    counts = _count_by_severity(raw_issues)

    with transaction.atomic():
        ValidationIssue.objects.filter(invoice_id=invoice.id).delete()
        ValidationIssue.objects.bulk_create(
            [
                ValidationIssue(
                    organization_id=invoice.organization_id,
                    invoice_id=invoice.id,
                    code=issue.code,
                    severity=issue.severity,
                    field_path=issue.field_path,
                    message=issue.message,
                    detail=issue.detail,
                )
                for issue in raw_issues
            ]
        )

        record_event(
            action_type="invoice.validated",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="validation.pipeline",
            organization_id=str(invoice.organization_id),
            affected_entity_type="Invoice",
            affected_entity_id=str(invoice.id),
            payload={
                "issue_count": len(raw_issues),
                "errors": counts["error"],
                "warnings": counts["warning"],
                "infos": counts["info"],
                # Code list (not messages) so an audit reader can reason about
                # WHICH rules fired without leaking user-visible message copy.
                "codes": sorted({issue.code for issue in raw_issues}),
            },
        )

    return ValidationResult(
        invoice_id=invoice.id,
        issue_count=len(raw_issues),
        error_count=counts["error"],
        warning_count=counts["warning"],
        info_count=counts["info"],
    )


def issues_for_invoice(*, organization_id: UUID, invoice_id: UUID) -> list[ValidationIssue]:
    """Read API for the review UI. Tenant-scoped — RLS belt-and-suspenders."""
    return list(
        ValidationIssue.objects.filter(
            organization_id=organization_id, invoice_id=invoice_id
        ).order_by("severity", "field_path")
    )


def preview_validation(
    *,
    invoice_id: UUID | str,
    draft: dict[str, object] | None = None,
) -> list[Issue]:
    """Run validation against a hypothetical Invoice without persisting.

    The review UI debounces edits and calls this to show live
    pass/fail feedback as the user types — the alternative was building
    a parallel TypeScript rule engine that would inevitably drift from
    the Python source of truth. Same rules, same result, no duplication.

    ``draft`` shape mirrors ``update_invoice``:

      {
        "<header_field>": "<value>", ...    # sparse subset of EDITABLE_HEADER_FIELDS
        "line_items":        [{"line_number": int, ...}, ...],   # cell edits
        "add_line_items":    [{"description": "...", ...}],      # appended rows
        "remove_line_items": [int, ...],                         # removed line_numbers
      }

    Slice 98 — line-item drafts are now applied. Same rule engine
    sees the post-edit state, so totals.subtotal.mismatch /
    totals.tax.mismatch / line.subtotal.mismatch all preview live
    when the user edits a line. Unknown keys / unknown line numbers
    are silently skipped (preview is best-effort; save remains the
    authoritative validator).

    Returns the raw ``Issue`` list (not persisted ``ValidationIssue``
    rows) so the view layer can serialize it directly.
    """
    from copy import copy as shallow_copy
    from decimal import Decimal

    from apps.submission.models import LineItem
    from apps.submission.services import (  # local import — submission depends on validation, not vice versa
        EDITABLE_HEADER_FIELDS,
        EDITABLE_LINE_FIELDS,
        _coerce_line_field,
        _set_invoice_field,
    )

    draft = draft or {}
    invoice = Invoice.objects.prefetch_related("line_items").get(id=invoice_id)

    # 1. Header field drafts — mutate the invoice in-place. Django won't
    #    persist unless ``.save()`` is called.
    for name, raw_value in draft.items():
        if name in {"line_items", "add_line_items", "remove_line_items"}:
            continue
        if name not in EDITABLE_HEADER_FIELDS:
            continue
        _set_invoice_field(invoice, name, str(raw_value or ""))

    # 2. Materialise the existing lines into a working list. We
    #    deep-shallow-copy each LineItem so our mutations don't leak
    #    into the prefetch cache attached to ``invoice``.
    working_lines: list[LineItem] = [shallow_copy(line) for line in invoice.line_items.all()]
    by_number: dict[int, LineItem] = {l.line_number: l for l in working_lines}

    # 3. Apply line-cell edits (line_items[N].field = value).
    line_payload = draft.get("line_items")
    if isinstance(line_payload, list):
        for entry in line_payload:
            if not isinstance(entry, dict):
                continue
            line_number = entry.get("line_number")
            if not isinstance(line_number, int) or line_number not in by_number:
                continue
            line = by_number[line_number]
            for field_name, raw_value in entry.items():
                if field_name == "line_number":
                    continue
                if field_name not in EDITABLE_LINE_FIELDS:
                    continue
                try:
                    coerced = _coerce_line_field(line, field_name, raw_value)
                except Exception:
                    continue  # preview is best-effort
                setattr(line, field_name, coerced)

    # 4. Drop removed lines.
    remove_payload = draft.get("remove_line_items")
    if isinstance(remove_payload, list):
        removed_set = {n for n in remove_payload if isinstance(n, int)}
        working_lines = [l for l in working_lines if l.line_number not in removed_set]

    # 5. Append pending-add lines as in-memory LineItem instances.
    add_payload = draft.get("add_line_items")
    if isinstance(add_payload, list) and add_payload:
        next_number = max((l.line_number for l in working_lines), default=0) + 1
        for entry in add_payload:
            if not isinstance(entry, dict):
                continue
            description = (entry.get("description") or "").strip()
            if not description:
                continue  # match update_invoice semantics — empty descriptions are dropped
            line = LineItem(
                organization_id=invoice.organization_id,
                invoice=invoice,
                line_number=next_number,
                description=description[:8000],
                quantity=_safe_decimal(entry.get("quantity")),
                unit_price_excl_tax=_safe_decimal(entry.get("unit_price_excl_tax")),
                line_subtotal_excl_tax=_safe_decimal(entry.get("line_subtotal_excl_tax")),
                tax_rate=_safe_decimal(entry.get("tax_rate")),
                tax_amount=_safe_decimal(entry.get("tax_amount")),
                line_total_incl_tax=_safe_decimal(entry.get("line_total_incl_tax")),
                tax_type_code=str(entry.get("tax_type_code") or "")[:16],
                unit_of_measurement=str(entry.get("unit_of_measurement") or "")[:16],
                classification_code=str(entry.get("classification_code") or "")[:16],
            )
            working_lines.append(line)
            next_number += 1

    # 6. Hand the rule engine a view of the invoice that returns the
    #    mutated line set. ``run_all_rules`` reads via
    #    ``invoice.line_items.all()`` — Django's prefetch cache
    #    intercepts that call when ``_prefetched_objects_cache`` is
    #    populated, so we drop our working list there. Direct
    #    assignment to ``invoice.line_items`` is rejected by the
    #    reverse-related-set descriptor; the prefetch cache is the
    #    documented escape hatch.
    if not hasattr(invoice, "_prefetched_objects_cache"):
        invoice._prefetched_objects_cache = {}
    invoice._prefetched_objects_cache["line_items"] = working_lines

    return run_all_rules(invoice)


def _safe_decimal(raw):  # type: ignore[no-untyped-def]
    """Decimal coercion that swallows everything for the preview path."""
    from decimal import Decimal, InvalidOperation

    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None




def _count_by_severity(issues: list[Issue]) -> dict[str, int]:
    counter: Counter[str] = Counter(issue.severity for issue in issues)
    return {
        "error": counter.get("error", 0),
        "warning": counter.get("warning", 0),
        "info": counter.get("info", 0),
    }
