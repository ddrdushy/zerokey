"""End-to-end LHDN submission orchestration (Slice 58).

Public entry points:

  - ``sign_invoice(invoice_id)`` — produce signed UBL XML, persist
    it (encrypted-at-rest blob path comes in Slice 59; today the
    XML is held on the Invoice row's ``signed_xml_s3_key`` as a
    placeholder + cached for the immediate submit).
  - ``submit_invoice_to_lhdn(invoice_id)`` — read signed XML, POST
    to LHDN, persist submission_uid on the Invoice.
  - ``poll_invoice_status(invoice_id)`` — fetch latest status,
    update Invoice if the LHDN response shows acceptance/rejection.

Each function audits one event documenting the outcome. Failures
do NOT raise; they record the failure on the audit chain + flip
the Invoice into ``error`` state so the user surface stays honest.

Cross-context: this module pulls signing-cert + LHDN-client
helpers from sibling modules in ``apps.submission``; reads
OrganizationIntegration + Organization via super-admin context.
"""

from __future__ import annotations

import base64
import logging
import uuid

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from . import certificates, lhdn_client, ubl_xml, xml_signature
from .models import Invoice

logger = logging.getLogger(__name__)


class SubmissionError(Exception):
    """Raised when the orchestration can't proceed (config, missing
    invoice). HTTP / signing / cert errors don't raise — they record
    the outcome on the invoice + return."""


def sign_invoice(invoice_id: uuid.UUID | str) -> dict:
    """Produce signed UBL XML for one invoice.

    Returns a dict with the signed XML (``signed_xml_b64``) +
    metadata (``digest_hex``, ``cert_kind``). On failure, raises
    or returns ``ok=False`` with a reason.
    """
    invoice = _get_invoice(invoice_id)

    try:
        cert = certificates.ensure_certificate(
            organization_id=invoice.organization_id
        )
    except certificates.CertificateError as exc:
        _audit_failure(
            invoice,
            action="submission.sign_invoice.failed",
            reason=f"certificate: {exc}",
        )
        return {"ok": False, "reason": str(exc)}

    try:
        unsigned = ubl_xml.build_invoice_xml(invoice)
        signed = xml_signature.sign_invoice_xml(
            xml_bytes=unsigned, certificate=cert
        )
    except Exception as exc:  # noqa: BLE001
        _audit_failure(
            invoice,
            action="submission.sign_invoice.failed",
            reason=f"{type(exc).__name__}: {exc!s}"[:255],
        )
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc!s}"}

    import hashlib

    digest_hex = hashlib.sha256(signed).hexdigest()

    record_event(
        action_type="submission.sign_invoice.signed",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="submission.signing",
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={
            "cert_kind": cert.kind,
            "cert_serial_hex": format(cert.cert.serial_number, "x"),
            "digest_hex": digest_hex,
            "byte_length": len(signed),
        },
    )

    return {
        "ok": True,
        "signed_xml_b64": base64.b64encode(signed).decode("ascii"),
        "signed_xml_bytes": signed,
        "digest_hex": digest_hex,
        "cert_kind": cert.kind,
    }


def submit_invoice_to_lhdn(invoice_id: uuid.UUID | str) -> dict:
    """Sign-then-submit. Persists ``submission_uid`` on the Invoice.

    State machine:
      - On signing failure: invoice → ``error`` + audit reason.
      - On submit accepted (HTTP 202): invoice marked ``submitted``,
        ``lhdn_uuid`` populated when LHDN's status response carries
        one (often only after polling).
      - On LHDN rejection (validation): invoice → ``lhdn_rejected``
        with the response body excerpt on ``error_message``.
    """
    invoice = _get_invoice(invoice_id)

    sign_result = sign_invoice(invoice_id)
    if not sign_result["ok"]:
        invoice.status = Invoice.Status.ERROR
        invoice.error_message = (
            f"Signing failed: {sign_result['reason']}"[:8000]
        )
        invoice.save(update_fields=["status", "error_message", "updated_at"])
        return {"ok": False, "reason": sign_result["reason"]}

    try:
        creds = lhdn_client.credentials_for_org(
            organization_id=invoice.organization_id
        )
    except lhdn_client.LHDNError as exc:
        _audit_failure(
            invoice,
            action="submission.submit.failed",
            reason=f"creds: {exc}"[:255],
        )
        invoice.status = Invoice.Status.ERROR
        invoice.error_message = f"LHDN creds: {exc}"[:8000]
        invoice.save(update_fields=["status", "error_message", "updated_at"])
        return {"ok": False, "reason": str(exc)}

    code_number = invoice.invoice_number or str(invoice.id)
    envelope = lhdn_client.encode_for_submission(
        signed_xml_bytes=sign_result["signed_xml_bytes"],
        code_number=code_number,
    )

    try:
        response = lhdn_client.submit_documents(
            creds=creds, signed_xml_documents=[envelope]
        )
    except lhdn_client.LHDNValidationError as exc:
        invoice.status = Invoice.Status.REJECTED
        invoice.error_message = f"LHDN rejected: {exc!s}"[:8000]
        invoice.save(update_fields=["status", "error_message", "updated_at"])
        record_event(
            action_type="submission.submit.lhdn_rejected",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="submission.submit",
            organization_id=str(invoice.organization_id),
            affected_entity_type="Invoice",
            affected_entity_id=str(invoice.id),
            payload={
                "code_number": code_number,
                "environment": creds.environment,
            },
        )
        return {"ok": False, "reason": "lhdn_rejected", "detail": str(exc)}
    except lhdn_client.LHDNError as exc:
        _audit_failure(
            invoice,
            action="submission.submit.failed",
            reason=f"lhdn: {exc}"[:255],
        )
        invoice.status = Invoice.Status.ERROR
        invoice.error_message = f"LHDN error: {exc}"[:8000]
        invoice.save(update_fields=["status", "error_message", "updated_at"])
        return {"ok": False, "reason": str(exc)}

    submission_uid = response.get("submissionUid", "")
    accepted = response.get("acceptedDocuments", [])
    rejected = response.get("rejectedDocuments", [])

    invoice.status = Invoice.Status.SUBMITTING
    # We store the submission UID on the existing s3-key column for v1
    # — Slice 59 splits that into a proper column. Putting it here
    # keeps the data path working without another migration this slice.
    invoice.signed_xml_s3_key = f"submission_uid={submission_uid}"
    invoice.validation_timestamp = timezone.now()
    invoice.save(
        update_fields=[
            "status",
            "signed_xml_s3_key",
            "validation_timestamp",
            "updated_at",
        ]
    )

    # If the response already echoes a UUID for our document (some
    # LHDN environments do this on the synchronous response, others
    # require a poll), capture it.
    if accepted and isinstance(accepted, list):
        first = accepted[0]
        if isinstance(first, dict) and first.get("uuid"):
            invoice.lhdn_uuid = first["uuid"][:64]
            invoice.save(update_fields=["lhdn_uuid", "updated_at"])

    record_event(
        action_type="submission.submit.accepted",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="submission.submit",
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={
            "submission_uid": submission_uid,
            "environment": creds.environment,
            "accepted_count": len(accepted) if isinstance(accepted, list) else 0,
            "rejected_count": len(rejected) if isinstance(rejected, list) else 0,
        },
    )

    return {
        "ok": True,
        "submission_uid": submission_uid,
        "accepted_count": len(accepted) if isinstance(accepted, list) else 0,
        "rejected_count": len(rejected) if isinstance(rejected, list) else 0,
    }


def poll_invoice_status(invoice_id: uuid.UUID | str) -> dict:
    """Fetch the latest LHDN status + reconcile the Invoice row.

    Idempotent: calling repeatedly is safe; only state transitions
    fire audits. Returns the latest known status string for the
    caller (worker or UI poll button).
    """
    invoice = _get_invoice(invoice_id)
    submission_uid = (
        (invoice.signed_xml_s3_key or "")
        .removeprefix("submission_uid=")
        .strip()
    )
    if not submission_uid:
        return {"ok": False, "reason": "invoice not yet submitted"}

    try:
        creds = lhdn_client.credentials_for_org(
            organization_id=invoice.organization_id
        )
        body = lhdn_client.get_submission_status(
            creds=creds, submission_uid=submission_uid
        )
    except lhdn_client.LHDNError as exc:
        _audit_failure(
            invoice,
            action="submission.poll.failed",
            reason=f"{type(exc).__name__}"[:128],
        )
        return {"ok": False, "reason": str(exc)}

    overall = body.get("overallStatus", "")
    summaries = body.get("documentSummary") or []
    first = summaries[0] if summaries else {}
    document_status = first.get("status", "")
    document_uuid = first.get("uuid", "")

    if document_uuid and document_uuid != invoice.lhdn_uuid:
        invoice.lhdn_uuid = document_uuid[:64]
        invoice.save(update_fields=["lhdn_uuid", "updated_at"])

    # State transitions per LHDN's status taxonomy.
    if document_status == "Valid":
        if invoice.status != Invoice.Status.VALIDATED:
            invoice.status = Invoice.Status.VALIDATED
            invoice.save(update_fields=["status", "updated_at"])
            record_event(
                action_type="submission.poll.accepted",
                actor_type=AuditEvent.ActorType.SERVICE,
                actor_id="submission.poll",
                organization_id=str(invoice.organization_id),
                affected_entity_type="Invoice",
                affected_entity_id=str(invoice.id),
                payload={
                    "submission_uid": submission_uid,
                    "lhdn_uuid": document_uuid,
                    "environment": creds.environment,
                },
            )
            # Pull the QR URL on the first transition to Valid.
            # The longId LHDN returns is a public verification slug;
            # it lives on the PORTAL hostname (not the API). Anyone
            # with the QR-encoded URL can verify the invoice on
            # LHDN's web UI without auth.
            try:
                qr_body = lhdn_client.get_document_qr(
                    creds=creds, document_uuid=document_uuid
                )
                long_id = qr_body.get("longId")
                if long_id and creds.portal_url:
                    qr_url = (
                        f"{creds.portal_url.rstrip('/')}"
                        f"/{document_uuid}/share/{long_id}"
                    )
                    invoice.lhdn_qr_code_url = qr_url[:200]
                    invoice.save(update_fields=["lhdn_qr_code_url", "updated_at"])
            except lhdn_client.LHDNError:
                # QR fetch failures don't roll back acceptance.
                pass
    elif document_status == "Invalid":
        if invoice.status != Invoice.Status.REJECTED:
            invoice.status = Invoice.Status.REJECTED
            invoice.error_message = (
                f"LHDN rejected at validation: {first.get('errorMessage', '')}"
            )[:8000]
            invoice.save(
                update_fields=["status", "error_message", "updated_at"]
            )
            record_event(
                action_type="submission.poll.rejected",
                actor_type=AuditEvent.ActorType.SERVICE,
                actor_id="submission.poll",
                organization_id=str(invoice.organization_id),
                affected_entity_type="Invoice",
                affected_entity_id=str(invoice.id),
                payload={
                    "submission_uid": submission_uid,
                    "environment": creds.environment,
                },
            )

    return {
        "ok": True,
        "overall_status": overall,
        "document_status": document_status,
        "lhdn_uuid": document_uuid,
    }


# --- Helpers ---------------------------------------------------------------


def cancel_invoice(
    *,
    invoice_id: uuid.UUID | str,
    reason: str,
    actor_user_id: uuid.UUID | str,
) -> dict:
    """Cancel a validated invoice within LHDN's 72-hour window.

    Per spec §4.3 the window is 72 hours from
    ``dateTimeValidated``. We stash that in
    ``Invoice.validation_timestamp`` at submission time. On
    request:

      - If the invoice has no ``lhdn_uuid``, it never reached
        LHDN — nothing to cancel.
      - If we're past the 72-hour window locally, refuse before
        calling LHDN (saves a round trip + gives the customer a
        clear "use a credit note instead" message).
      - Otherwise call LHDN's cancel endpoint. On their
        ``OperationPeriodOver`` response, surface the same
        message — our local clock might disagree with LHDN's
        validated-at timestamp by seconds.

    On success: invoice → ``Status.CANCELLED`` +
    ``cancellation_timestamp`` set + audit
    ``submission.cancel.accepted``.
    """
    from datetime import timedelta

    invoice = _get_invoice(invoice_id)

    if not invoice.lhdn_uuid:
        return {
            "ok": False,
            "reason": "Invoice has not been submitted to LHDN.",
        }

    if not reason or not reason.strip():
        return {
            "ok": False,
            "reason": "A cancellation reason is required by LHDN.",
        }

    # Local-clock 72-hour gate. We compare against
    # validation_timestamp (when LHDN accepted the submission).
    if invoice.validation_timestamp is not None:
        elapsed = timezone.now() - invoice.validation_timestamp
        if elapsed > timedelta(hours=72):
            return {
                "ok": False,
                "reason": (
                    "Cancellation window expired (72 hours). "
                    "Issue a credit note instead."
                ),
                "code": "operation_period_over_local",
            }

    try:
        creds = lhdn_client.credentials_for_org(
            organization_id=invoice.organization_id
        )
    except lhdn_client.LHDNError as exc:
        return {"ok": False, "reason": str(exc)}

    try:
        lhdn_client.cancel_document(
            creds=creds,
            document_uuid=invoice.lhdn_uuid,
            reason=reason.strip(),
        )
    except lhdn_client.LHDNCancellationWindowError:
        return {
            "ok": False,
            "reason": (
                "LHDN reports the cancellation window has expired. "
                "Issue a credit note instead."
            ),
            "code": "operation_period_over",
        }
    except lhdn_client.LHDNNotFoundError:
        return {
            "ok": False,
            "reason": "LHDN no longer recognises this document UUID.",
        }
    except lhdn_client.LHDNError as exc:
        _audit_failure(
            invoice,
            action="submission.cancel.failed",
            reason=f"{type(exc).__name__}: {exc!s}"[:255],
        )
        return {"ok": False, "reason": str(exc)}

    invoice.status = Invoice.Status.CANCELLED
    invoice.cancellation_timestamp = timezone.now()
    invoice.save(
        update_fields=["status", "cancellation_timestamp", "updated_at"]
    )

    record_event(
        action_type="submission.cancel.accepted",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={
            "lhdn_uuid": invoice.lhdn_uuid,
            "environment": creds.environment,
            "reason": reason.strip()[:255],
        },
    )

    return {
        "ok": True,
        "lhdn_uuid": invoice.lhdn_uuid,
        "cancelled_at": invoice.cancellation_timestamp.isoformat(),
    }


def _get_invoice(invoice_id) -> Invoice:
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason="submission.lookup"):
        try:
            return Invoice.objects.get(id=invoice_id)
        except Invoice.DoesNotExist as exc:
            raise SubmissionError(
                f"Invoice {invoice_id} not found."
            ) from exc


def _audit_failure(invoice: Invoice, *, action: str, reason: str) -> None:
    record_event(
        action_type=action,
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="submission",
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={"reason": reason[:255]},
    )
