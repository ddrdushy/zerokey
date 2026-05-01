"""Submission context views.

Phase 2 surface (Phase 3 adds the actual signing + LHDN submission):
  GET   /api/v1/invoices/                  — all-invoices list with filters
  GET   /api/v1/invoices/by-job/<job_id>/  — fetch the invoice for an IngestionJob
  GET   /api/v1/invoices/<id>/             — invoice detail with line items
  PATCH /api/v1/invoices/<id>/             — apply user corrections, re-validate
"""

from __future__ import annotations

from datetime import datetime

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import services
from .models import Invoice
from .serializers import InvoiceListSummarySerializer, InvoiceSerializer


def _active_org(request: Request) -> str | None:
    session = getattr(request, "session", None)
    return session.get("organization_id") if session is not None else None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_invoices(request: Request) -> Response:
    """All-invoices list, scoped to the active org.

    Filters: ``?status=<exact>``, ``?search=<substring>``,
    ``?limit=<n>``, ``?before_created_at=<iso>`` (cursor pagination).
    """
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"results": [], "total": 0})

    status_filter = request.query_params.get("status") or None
    search = request.query_params.get("search") or None

    try:
        limit = int(request.query_params.get("limit", "50"))
    except ValueError:
        return Response(
            {"detail": "limit must be an integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    limit = max(1, min(limit, 200))

    raw_before = request.query_params.get("before_created_at")
    before: datetime | None = None
    if raw_before:
        try:
            before = datetime.fromisoformat(raw_before)
        except ValueError:
            return Response(
                {"detail": "before_created_at must be ISO 8601."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    rows = services.list_invoices_for_organization(
        organization_id=organization_id,
        status=status_filter,
        search=search,
        limit=limit,
        before_created_at=before,
    )
    total = services.count_invoices_for_organization(organization_id=organization_id)
    return Response(
        {
            "results": InvoiceListSummarySerializer(rows, many=True).data,
            "total": total,
        }
    )


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def invoice_detail(request: Request, invoice_id: str) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == "PATCH":
        return _invoice_update(request, organization_id, invoice_id)

    invoice = services.get_invoice(organization_id=organization_id, invoice_id=invoice_id)
    if invoice is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(InvoiceSerializer(invoice).data)


def _invoice_update(request: Request, organization_id: str, invoice_id: str) -> Response:
    """Apply user corrections and return the re-validated invoice."""
    if not isinstance(request.data, dict):
        return Response(
            {"detail": "Body must be a JSON object."}, status=status.HTTP_400_BAD_REQUEST
        )
    try:
        result = services.update_invoice(
            organization_id=organization_id,
            invoice_id=invoice_id,
            updates=request.data,
            actor_user_id=request.user.id,
        )
    except Invoice.DoesNotExist:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    except services.InvoiceUpdateError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(InvoiceSerializer(result.invoice).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def compliance_posture_view(request: Request) -> Response:
    """Slice 96 — compliance posture metrics.

    Derived from the existing Invoice + AuditEvent rows; no new
    columns, no separate aggregation table. The numbers are honest
    snapshots, not pre-aggregated; for a tenant with millions of
    invoices we'd swap in materialised counts. Today's tenants are
    in the hundreds.

    Window: last 30 days by default; ``?days=90`` overrides.

    Returns:
      total: count of invoices with issue_date in the window
      validated: validated by LHDN
      rejected: rejected by LHDN
      cancelled, error: terminal but not validated
      in_flight: ready_for_review / submitting / signing
      success_rate: validated / (validated + rejected + cancelled + error)
      median_seconds_to_validation: half of validated invoices took
        this long or less from creation → validated_timestamp
      penalty_window_compliance: % of validated invoices submitted
        within 30 days of issue_date (LHDN's Phase 4 enforcement
        window)
    """
    from datetime import timedelta
    from statistics import median

    from django.utils import timezone

    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        days = int(request.query_params.get("days", "30"))
    except ValueError:
        days = 30
    days = max(1, min(days, 365))

    cutoff = timezone.now() - timedelta(days=days)
    invoices = Invoice.objects.filter(
        organization_id=organization_id,
        created_at__gte=cutoff,
    ).only(
        "status",
        "created_at",
        "validation_timestamp",
        "issue_date",
    )

    counts = {
        "total": 0,
        "validated": 0,
        "rejected": 0,
        "cancelled": 0,
        "error": 0,
        "in_flight": 0,
        "ready_for_review": 0,
    }
    seconds_to_validation: list[float] = []
    in_window = 0
    out_of_window = 0
    PENALTY_DAYS = 30

    for inv in invoices:
        counts["total"] += 1
        s = inv.status
        if s in counts:
            counts[s] += 1
        elif s == "submitting" or s == "signing" or s == "awaiting_approval":
            counts["in_flight"] += 1
        if s == Invoice.Status.VALIDATED and inv.validation_timestamp and inv.created_at:
            seconds_to_validation.append(
                (inv.validation_timestamp - inv.created_at).total_seconds()
            )
        if s == Invoice.Status.VALIDATED and inv.validation_timestamp and inv.issue_date:
            delta_days = (inv.validation_timestamp.date() - inv.issue_date).days
            if 0 <= delta_days <= PENALTY_DAYS:
                in_window += 1
            else:
                out_of_window += 1

    terminal = counts["validated"] + counts["rejected"] + counts["cancelled"] + counts["error"]
    success_rate = (counts["validated"] / terminal) if terminal else None
    penalty_compliance = (
        (in_window / (in_window + out_of_window)) if (in_window + out_of_window) else None
    )

    return Response(
        {
            "window_days": days,
            "counts": counts,
            "success_rate": round(success_rate, 4) if success_rate is not None else None,
            "median_seconds_to_validation": (
                round(median(seconds_to_validation), 1) if seconds_to_validation else None
            ),
            "penalty_window_compliance": (
                round(penalty_compliance, 4) if penalty_compliance is not None else None
            ),
            "penalty_window_days": PENALTY_DAYS,
            "in_penalty_window": in_window,
            "out_of_penalty_window": out_of_window,
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def schedule_submit_view(request: Request, invoice_id: str) -> Response:
    """Slice 96 — set / clear an invoice's deferred-submit timestamp.

    Body: ``{"scheduled_submit_at": "2026-05-03T09:00:00Z"}`` to set,
    or ``{"scheduled_submit_at": null}`` to clear.

    The dispatch beat task (``submission.dispatch_scheduled``) picks
    up rows whose timestamp has come due AND whose status is
    ``ready_for_review``. Clearing simply cancels the schedule;
    the user can still hit Submit immediately.
    """
    from datetime import datetime

    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)

    invoice = services.get_invoice(organization_id=organization_id, invoice_id=invoice_id)
    if invoice is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    if invoice.status != Invoice.Status.READY_FOR_REVIEW:
        return Response(
            {
                "detail": (
                    f"Can only schedule from ready_for_review state; current state "
                    f"is {invoice.status}."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    body = request.data if isinstance(request.data, dict) else {}
    raw = body.get("scheduled_submit_at")
    if raw is None or raw == "":
        invoice.scheduled_submit_at = None
    else:
        if not isinstance(raw, str):
            return Response(
                {"detail": "scheduled_submit_at must be an ISO datetime string or null."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            # Normalise Z → +00:00 since fromisoformat in 3.11+ accepts both
            # but earlier versions don't. We're on 3.12 but be defensive.
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return Response(
                {"detail": f"scheduled_submit_at is not a valid ISO datetime: {raw!r}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        invoice.scheduled_submit_at = value

    invoice.save(update_fields=["scheduled_submit_at", "updated_at"])

    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    record_event(
        action_type="invoice.scheduled" if invoice.scheduled_submit_at else "invoice.unscheduled",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(request.user.id),
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={
            "scheduled_submit_at": (
                invoice.scheduled_submit_at.isoformat() if invoice.scheduled_submit_at else None
            )
        },
    )
    return Response(InvoiceSerializer(invoice).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def validate_preview_view(request: Request, invoice_id: str) -> Response:
    """Run validation against an in-memory invoice + draft, no persist.

    The review UI debounces field edits and posts the current draft
    here; we apply the draft to a fresh copy of the saved invoice and
    run the rule engine. Issues come back in the same shape as
    ``invoice.validation_issues`` so the FE can swap them in directly.

    Read-only — never persists. Safe to call as fast as the FE wants.
    """
    from apps.validation.services import preview_validation

    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)

    invoice = services.get_invoice(organization_id=organization_id, invoice_id=invoice_id)
    if invoice is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    draft = request.data if isinstance(request.data, dict) else {}
    issues = preview_validation(invoice_id=invoice.id, draft=draft)
    counts = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return Response(
        {
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "field_path": issue.field_path,
                    "message": issue.message,
                    "detail": issue.detail,
                }
                for issue in issues
            ],
            "summary": {
                "issue_count": len(issues),
                "errors": counts["error"],
                "warnings": counts["warning"],
                "infos": counts["info"],
            },
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def invoice_by_job(request: Request, job_id: str) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)
    invoice = services.get_invoice_for_job(organization_id=organization_id, ingestion_job_id=job_id)
    if invoice is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(InvoiceSerializer(invoice).data)


# --- Slice 59B: LHDN lifecycle endpoints ----------------------------------


def _can_user_submit_lhdn(user, organization_id) -> bool:
    """Roles that may submit/cancel LHDN documents.

    Owner / admin / approver / submitter may submit. Viewer cannot.
    Backend gate is the source of truth; UI mirrors for cleanliness.
    """
    from apps.identity.models import OrganizationMembership

    return OrganizationMembership.objects.filter(
        user=user,
        organization_id=organization_id,
        is_active=True,
        role__name__in=["owner", "admin", "approver", "submitter"],
    ).exists()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_invoice_to_lhdn_view(request: Request, invoice_id: str) -> Response:
    """Sign + submit one invoice to LHDN.

    Synchronous response — the operator wants to see the immediate
    outcome (LHDN typically returns 202 + a submissionUid in <2s).
    Polling for the validation status happens via the separate
    /poll-lhdn/ endpoint.

    Returns the updated Invoice payload so the FE can re-render in
    place without a fetch.
    """
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not _can_user_submit_lhdn(request.user, organization_id):
        return Response(
            {"detail": "You don't have permission to submit invoices."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        invoice = Invoice.objects.get(id=invoice_id, organization_id=organization_id)
    except Invoice.DoesNotExist:
        return Response(
            {"detail": "Invoice not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Pre-flight checks before kicking off signing — surface the
    # most common errors here (cleaner than letting the orchestrator
    # raise + audit a generic failure).
    if not invoice.invoice_number:
        return Response(
            {"detail": ("Invoice number is required before LHDN submission.")},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if invoice.status in {
        Invoice.Status.SUBMITTING,
        Invoice.Status.VALIDATED,
        Invoice.Status.CANCELLED,
    }:
        return Response(
            {"detail": (f"Invoice is already in {invoice.status} state.")},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Slice 87 — approval gate. If the org's policy demands an
    # approval and this invoice doesn't have an active one, refuse
    # the submit. The UI surfaces a "Request approval" gesture
    # alongside, which creates the ApprovalRequest row.
    from . import approvals

    if approvals.invoice_requires_approval(invoice) and not approvals.has_active_approval(invoice):
        return Response(
            {
                "detail": (
                    "This invoice requires approval before submission. "
                    "Request approval from an Approver, Admin, or Owner."
                ),
                "needs_approval": True,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    from . import lhdn_submission

    result = lhdn_submission.submit_invoice_to_lhdn(invoice.id)
    invoice.refresh_from_db()
    return Response(
        {
            "ok": result.get("ok", False),
            "reason": result.get("reason", ""),
            "submission_uid": result.get("submission_uid", ""),
            "invoice": InvoiceSerializer(invoice).data,
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cancel_invoice_lhdn_view(request: Request, invoice_id: str) -> Response:
    """Cancel a validated LHDN invoice within the 72-hour window.

    Body: ``{"reason": "..."}``. Reason is required (LHDN's contract,
    enforced both client-side + by the orchestrator).
    """
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not _can_user_submit_lhdn(request.user, organization_id):
        return Response(
            {"detail": "You don't have permission to cancel invoices."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        invoice = Invoice.objects.get(id=invoice_id, organization_id=organization_id)
    except Invoice.DoesNotExist:
        return Response(
            {"detail": "Invoice not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    body = request.data or {}
    reason = str(body.get("reason") or "").strip()

    from . import lhdn_submission

    result = lhdn_submission.cancel_invoice(
        invoice_id=invoice.id,
        reason=reason,
        actor_user_id=request.user.id,
    )
    invoice.refresh_from_db()
    return Response(
        {
            "ok": result.get("ok", False),
            "reason": result.get("reason", ""),
            "code": result.get("code", ""),
            "invoice": InvoiceSerializer(invoice).data,
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def poll_invoice_lhdn_view(request: Request, invoice_id: str) -> Response:
    """Trigger one synchronous status poll for the invoice.

    Used by the FE's "Refresh status" button. The Celery beat
    scheduler also polls in the background; this endpoint is the
    operator-on-demand path.
    """
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        invoice = Invoice.objects.get(id=invoice_id, organization_id=organization_id)
    except Invoice.DoesNotExist:
        return Response(
            {"detail": "Invoice not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    from . import lhdn_submission

    result = lhdn_submission.poll_invoice_status(invoice.id)
    invoice.refresh_from_db()
    return Response(
        {
            "ok": result.get("ok", False),
            "reason": result.get("reason", ""),
            "document_status": result.get("document_status", ""),
            "lhdn_uuid": result.get("lhdn_uuid", ""),
            "invoice": InvoiceSerializer(invoice).data,
        }
    )


# --- Slice 61 + 62: Issue amendments (CN / DN / RN) ---------------------


def _issue_amendment_view(
    request: Request,
    invoice_id: str,
    *,
    create_fn,
    noun: str,
    response_id_key: str,
) -> Response:
    """Shared body for the three amendment endpoints.

    ``create_fn`` is one of amendments.create_{credit,debit,refund}_note.
    Same auth + body shape across all three; only the create call
    + the response key differ.
    """
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not _can_user_submit_lhdn(request.user, organization_id):
        return Response(
            {"detail": f"You don't have permission to issue {noun}s."},
            status=status.HTTP_403_FORBIDDEN,
        )
    try:
        source = Invoice.objects.get(id=invoice_id, organization_id=organization_id)
    except Invoice.DoesNotExist:
        return Response(
            {"detail": "Invoice not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    body = request.data or {}
    reason = str(body.get("reason") or "").strip()
    line_adjustments = body.get("line_adjustments")
    if line_adjustments is not None and not isinstance(line_adjustments, list):
        return Response(
            {"detail": "line_adjustments must be an array."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    from . import amendments

    try:
        new_inv = create_fn(
            source_invoice_id=source.id,
            reason=reason,
            actor_user_id=request.user.id,
            line_adjustments=line_adjustments,
        )
    except amendments.AmendmentError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    number_key = response_id_key.replace("_id", "_number")
    return Response(
        {
            response_id_key: str(new_inv.id),
            number_key: new_inv.invoice_number,
            "ingestion_job_id": str(new_inv.ingestion_job_id),
            "invoice": InvoiceSerializer(new_inv).data,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def issue_credit_note_view(request: Request, invoice_id: str) -> Response:
    """Issue a Credit Note (LHDN type 02) against a Validated invoice.

    Body: ``{"reason": "...", "line_adjustments": [...]?}``.
    ``line_adjustments`` is optional — if omitted, credits every
    line at the source amount.
    """
    from . import amendments

    return _issue_amendment_view(
        request,
        invoice_id,
        create_fn=amendments.create_credit_note,
        noun="credit note",
        response_id_key="credit_note_id",
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def issue_debit_note_view(request: Request, invoice_id: str) -> Response:
    """Issue a Debit Note (LHDN type 03) against a Validated invoice.

    Used to add charges to a previously-issued invoice (late fees,
    additional services billed after issue).
    """
    from . import amendments

    return _issue_amendment_view(
        request,
        invoice_id,
        create_fn=amendments.create_debit_note,
        noun="debit note",
        response_id_key="debit_note_id",
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def issue_refund_note_view(request: Request, invoice_id: str) -> Response:
    """Issue a Refund Note (LHDN type 04) against a Validated invoice.

    Confirms that a refund payment has been made to the buyer.
    Distinct from CN: a CN reduces an outstanding receivable; an
    RN documents an actual money refund.
    """
    from . import amendments

    return _issue_amendment_view(
        request,
        invoice_id,
        create_fn=amendments.create_refund_note,
        noun="refund note",
        response_id_key="refund_note_id",
    )


# --- Slice 84 — signed-document download (decrypted) ---------------------


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def signed_document_download_view(request: Request, invoice_id: str) -> Response:
    """Download the decrypted signed bytes for a submitted invoice.

    Returns the document with the appropriate content-type
    (``application/xml`` for the XML path, ``application/json``
    for the JSON path). The audit chain records the read so a
    later auditor can see who pulled the bytes.

    A 404 is returned for invoices that have no stored blob yet
    (Phase 2 invoices that submitted before Slice 84 landed, or
    invoices where the persist step failed). Cross-tenant
    requests return 404 — same opacity rule the rest of the
    invoice API uses.
    """
    from django.http import HttpResponse

    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    from . import signed_blob

    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)

    invoice = services.get_invoice(organization_id=organization_id, invoice_id=invoice_id)
    if invoice is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    if not invoice.signed_xml_s3_key:
        return Response(
            {"detail": "No signed document on file for this invoice."},
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        result = signed_blob.fetch_signed_bytes(invoice_id=invoice.id)
    except signed_blob.SignedBlobError as exc:
        return Response(
            {"detail": f"Could not retrieve signed document: {exc}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    record_event(
        action_type="submission.signed_blob.read",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(request.user.id),
        organization_id=str(organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={
            "format": result["format"],
            "digest_sha256": result["digest_sha256"],
        },
    )

    content_type = "application/xml" if result["format"] == "xml" else "application/json"
    extension = "xml" if result["format"] == "xml" else "json"
    response = HttpResponse(result["signed_bytes"], content_type=content_type)
    response["Content-Disposition"] = (
        f'attachment; filename="invoice-{invoice.id}-signed.{extension}"'
    )
    return response


# --- Slice 87 — two-step approval workflow ------------------------------


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def request_approval_view(request: Request, invoice_id: str) -> Response:
    """Submitter / owner / admin asks an approver to gate this invoice."""
    from . import approvals

    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)
    invoice = services.get_invoice(organization_id=organization_id, invoice_id=invoice_id)
    if invoice is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    reason = str((request.data or {}).get("reason") or "").strip()
    try:
        req = approvals.request_approval(
            invoice_id=invoice.id, actor_user_id=request.user.id, reason=reason
        )
    except approvals.ApprovalError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    invoice.refresh_from_db()
    return Response(
        {
            "approval_id": str(req.id),
            "status": req.status,
            "invoice": InvoiceSerializer(invoice).data,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def approve_invoice_view(request: Request, approval_id: str) -> Response:
    """An approver decides on a pending request."""
    from .approvals import ApprovalError, approve
    from .models import ApprovalRequest

    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)
    # Tenant-scope first so cross-tenant requests 404 (don't leak existence).
    pending = ApprovalRequest.objects.filter(
        id=approval_id, organization_id=organization_id
    ).first()
    if pending is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    note = str((request.data or {}).get("note") or "").strip()
    try:
        req = approve(
            approval_id=approval_id,
            actor_user_id=request.user.id,
            note=note,
        )
    except ApprovalError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"approval_id": str(req.id), "status": req.status})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reject_invoice_view(request: Request, approval_id: str) -> Response:
    """An approver rejects a pending request."""
    from .approvals import ApprovalError, reject
    from .models import ApprovalRequest

    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)
    pending = ApprovalRequest.objects.filter(
        id=approval_id, organization_id=organization_id
    ).first()
    if pending is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    reason = str((request.data or {}).get("reason") or "").strip()
    try:
        req = reject(
            approval_id=approval_id,
            actor_user_id=request.user.id,
            reason=reason,
        )
    except ApprovalError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"approval_id": str(req.id), "status": req.status})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pending_approvals_view(request: Request) -> Response:
    """List invoices awaiting approval for the active org."""
    from .models import ApprovalRequest

    organization_id = _active_org(request)
    if not organization_id:
        return Response({"results": []})
    rows = (
        ApprovalRequest.objects.filter(
            organization_id=organization_id,
            status=ApprovalRequest.Status.PENDING,
        )
        .select_related("invoice")
        .order_by("-requested_at")[:200]
    )
    results = []
    for r in rows:
        results.append(
            {
                "approval_id": str(r.id),
                "invoice_id": str(r.invoice_id),
                "invoice_number": r.invoice.invoice_number,
                "grand_total": (
                    str(r.invoice.grand_total) if r.invoice.grand_total is not None else None
                ),
                "currency_code": r.invoice.currency_code,
                "buyer_legal_name": r.invoice.buyer_legal_name,
                "requested_by_user_id": str(r.requested_by_user_id),
                "requested_at": r.requested_at.isoformat(),
                "requested_reason": r.requested_reason,
            }
        )
    return Response({"results": results})


# --- Slice 88 — submission CSV export ----------------------------------


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def export_invoices_csv_view(request: Request) -> Response:
    """Stream the active org's submission stream as CSV.

    Query params (all optional):
      ?since=<iso8601>   — created_at >=
      ?until=<iso8601>   — created_at <=
      ?status=<exact>    — exact invoice status filter
    """
    from django.http import StreamingHttpResponse

    from . import exports

    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        since = exports.parse_iso_or_400(request.query_params.get("since"))
        until = exports.parse_iso_or_400(request.query_params.get("until"))
    except ValueError as exc:
        return Response(
            {"detail": f"Invalid timestamp: {exc}"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    status_filter = request.query_params.get("status") or None

    response = StreamingHttpResponse(
        exports.stream_invoices_csv(
            organization_id=organization_id,
            since=since,
            until=until,
            status=status_filter,
            actor_user_id=request.user.id,
        ),
        content_type="text/csv; charset=utf-8",
    )
    response["Content-Disposition"] = 'attachment; filename="zerokey-invoices-export.csv"'
    return response
