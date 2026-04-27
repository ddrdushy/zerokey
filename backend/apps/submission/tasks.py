"""Celery tasks for the submission context.

The signing task routes to the dedicated ``signing`` queue, which runs on isolated
worker containers (see ARCHITECTURE.md, "The signing service"). Those containers
have read-only S3 access scoped to the customer-certificates prefix and KMS decrypt
access to the certificate envelope key — nothing else. The blast radius of a
compromise is bounded by these IAM controls, not by application code.

Phase 1 ships placeholders only; real signing and submission land in Phase 3.
"""

from __future__ import annotations

from celery import shared_task


@shared_task(name="submission.sign_invoice", queue="signing")
def sign_invoice(invoice_id: str) -> dict[str, str]:
    """Sign an invoice payload with the customer's LHDN-issued certificate.

    Phase 1 placeholder. Real implementation: load envelope-encrypted cert from S3,
    decrypt envelope key via KMS, sign in-memory, discard cert.
    """
    return {"invoice_id": invoice_id, "status": "not-implemented"}


@shared_task(name="submission.submit_to_lhdn", queue="high")
def submit_to_lhdn(invoice_id: str) -> dict[str, str]:
    """Submit a signed invoice to LHDN MyInvois and poll for the UUID + QR code.

    Phase 1 placeholder. Real implementation lands in Phase 3.
    """
    return {"invoice_id": invoice_id, "status": "not-implemented"}
