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


def _count_by_severity(issues: list[Issue]) -> dict[str, int]:
    counter: Counter[str] = Counter(issue.severity for issue in issues)
    return {
        "error": counter.get("error", 0),
        "warning": counter.get("warning", 0),
        "info": counter.get("info", 0),
    }
