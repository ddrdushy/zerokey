"""Re-match pass for ready_for_review invoices (Slice 76).

The pay-off step of the connectors initiative — the moment where
the customer's review queue actually shrinks. After every
``apply_sync_proposal`` (and every ``revert_sync_proposal``,
which can also flip what an invoice matches), this pass walks
every Invoice in ``ready_for_review`` for the org and re-runs
the customer/item match. Newly-matched invoices get the master's
auto-filled fields applied + the audit chain records the lift.

Why on revert too: a sync can create a master row that an
invoice now matches; reverting deletes that master, and the
invoice should re-evaluate. The re-match never UN-fills invoice
fields (extracted data is durable), it only re-matches against
whatever master set is current.

The function is idempotent: calling it twice with no DB changes
in between yields zero new lifts on the second call.

Per UX_PRINCIPLES principle 7 (uncertainty is signaled clearly):
auto-filled fields keep the existing per_field_confidence=1.0
treatment from ``_autofill_buyer`` so the review UI's three-band
scheme correctly shows them as green ("from your master, not a
fresh extraction").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.submission.models import Invoice

from .services import _autofill_buyer, _find_customer_master

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RematchResult:
    rematched: int
    lifted: int
    fields_filled_total: int


def rematch_pending_invoices(
    *,
    organization_id: UUID | str,
    triggered_by: str,
) -> RematchResult:
    """Re-run customer-master match on every ready_for_review invoice.

    ``triggered_by`` lands in the audit payload — typically
    ``"connectors.sync_apply"`` or ``"connectors.sync_revert"``.

    Returns counts so the caller (sync_services orchestration) can
    log + emit a follow-up audit event with the totals.
    """
    invoices = list(
        Invoice.objects.filter(
            organization_id=organization_id,
            status=Invoice.Status.READY_FOR_REVIEW,
        ).prefetch_related("line_items")
    )

    rematched = 0
    lifted = 0
    fields_filled_total = 0

    for invoice in invoices:
        rematched += 1
        master = _find_customer_master(invoice)
        if master is None:
            continue

        with transaction.atomic():
            autofilled = _autofill_buyer(invoice, master)
            if autofilled:
                invoice.save()
                lifted += 1
                fields_filled_total += len(autofilled)

                record_event(
                    action_type="invoice.master_match_lifted_by_sync",
                    actor_type=AuditEvent.ActorType.SERVICE,
                    actor_id="enrichment.rematch",
                    organization_id=str(invoice.organization_id),
                    affected_entity_type="Invoice",
                    affected_entity_id=str(invoice.id),
                    payload={
                        "triggered_by": triggered_by,
                        "fields_filled": sorted(autofilled),
                        "customer_master_id": str(master.id),
                    },
                )

    if rematched:
        logger.info(
            "enrichment.rematch_pending_invoices",
            extra={
                "organization_id": str(organization_id),
                "rematched": rematched,
                "lifted": lifted,
                "fields_filled_total": fields_filled_total,
                "triggered_by": triggered_by,
            },
        )

    return RematchResult(
        rematched=rematched,
        lifted=lifted,
        fields_filled_total=fields_filled_total,
    )
