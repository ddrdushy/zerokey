"""Cloud intermediary-signing endpoint for the desktop app.

Phase 3 of DESKTOP_PIVOT_PLAN.md.

Contract:

    POST /api/v1/licenses/sign/document/
    body:
      entitlement: "<wire-format entitlement>"
      digest_b64:  "<base64 SHA-256 of the bytes to be signed>"
      digest_alg:  "SHA-256"
    response:
      signature_b64: "<base64 RSA-PSS-SHA256 over the digest>"
      signing_cert_pem: "<PEM-encoded intermediary cert chain>"
      serial_hex:       "<cert serial for audit reference>"
      audit_event_id:   "<cloud-side audit reference>"

We deliberately sign only a *digest*, not the full document. The desktop:
  1. Builds the unsigned MyInvois XML.
  2. Canonicalises the SignedInfo (XAdES BES).
  3. SHA-256 hashes that bytes.
  4. Sends us the digest.
  5. We sign the digest with Symprio's intermediary private key.
  6. Desktop assembles the final XAdES envelope, submits to LHDN
     directly from the customer's machine.

That contract means:
  - The cloud never sees invoice contents → privacy story holds.
  - The cloud's signing surface is tiny and uniform across document
    types (invoice / CN / DN / refund / consolidated).
  - The desktop still owns LHDN submission, so cloud downtime doesn't
    block sending — only signing-key access is centralised.

Authentication is by entitlement bearer, not session cookies. The
license_id inside the verified entitlement is the audit subject.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.submission.certificates import (
    CertificateError,
    IntermediaryNotConfigured,
    load_intermediary_certificate,
)

from .entitlements import EntitlementError, verify_entitlement

logger = logging.getLogger(__name__)

SUPPORTED_DIGEST_ALGS = {"SHA-256"}


@api_view(["POST"])
@permission_classes([AllowAny])
def sign_document_view(request: Request) -> Response:
    """Sign a desktop-provided digest with Symprio's intermediary key."""

    raw_entitlement = (request.data.get("entitlement") or "").strip()
    digest_b64 = (request.data.get("digest_b64") or "").strip()
    digest_alg = (request.data.get("digest_alg") or "SHA-256").strip().upper()

    if not raw_entitlement:
        return Response(
            {"detail": "entitlement is required.", "code": "missing_entitlement"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not digest_b64:
        return Response(
            {"detail": "digest_b64 is required.", "code": "missing_digest"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if digest_alg not in SUPPORTED_DIGEST_ALGS:
        return Response(
            {
                "detail": f"Unsupported digest_alg {digest_alg}.",
                "code": "unsupported_digest_alg",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Verify the entitlement Ed25519 signature + parse the payload. A
    # malformed / unsigned / expired-format entitlement gets rejected
    # before we touch the signing key.
    try:
        payload = verify_entitlement(raw_entitlement)
    except EntitlementError as exc:
        return Response(
            {"detail": str(exc), "code": "invalid_entitlement"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    # The entitlement must permit intermediary signing for the org's
    # plan. Starter plans require this; bring-your-own customers don't
    # call this endpoint.
    if "intermediary" not in (payload.get("signing_modes_allowed") or []):
        return Response(
            {
                "detail": "Entitlement does not permit intermediary signing.",
                "code": "intermediary_not_permitted",
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    if (payload.get("status") or "") != "active":
        return Response(
            {
                "detail": (
                    f"Entitlement reports status={payload.get('status')!r}; "
                    "intermediary signing requires status=active."
                ),
                "code": "entitlement_not_active",
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        digest_bytes = base64.b64decode(digest_b64, validate=True)
    except (base64.binascii.Error, ValueError):
        return Response(
            {"detail": "digest_b64 is not valid base64.", "code": "bad_digest_encoding"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(digest_bytes) != 32:
        return Response(
            {
                "detail": "SHA-256 digest must be 32 bytes.",
                "code": "bad_digest_length",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Load the platform-level intermediary cert.
    try:
        cert = load_intermediary_certificate()
    except IntermediaryNotConfigured as exc:
        # Operational error, not a customer error.
        logger.error("licensing.sign.intermediary_not_configured: %s", exc)
        return Response(
            {
                "detail": (
                    "The Symprio intermediary signing key is not configured. "
                    "Contact support."
                ),
                "code": "intermediary_not_configured",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except CertificateError:
        logger.exception("licensing.sign.cert_error")
        return Response(
            {"detail": "Signing service unavailable.", "code": "signing_unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    private_key = cert.private_key
    if not isinstance(private_key, rsa.RSAPrivateKey):  # pragma: no cover — guarded upstream
        return Response(
            {"detail": "Unsupported signing key type.", "code": "key_type"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Sign the digest with RSA-SHA256, PKCS#1 v1.5 padding (LHDN
    # XAdES BES uses RSA-SHA256 with PKCS#1 v1.5 — not PSS).
    signature = private_key.sign(
        digest_bytes,
        padding.PKCS1v15(),
        _PrehashedSHA256(),
    )

    # Audit. Carries the license_id, org_tin (already in payload) and
    # the cert serial. Never the digest contents — we treat the digest
    # itself as potentially-sensitive (it could leak document
    # fingerprints if logged in bulk).
    event = record_event(
        action_type="licensing.intermediary_sign.issued",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id=f"license:{payload.get('license_id')}",
        affected_entity_type="License",
        affected_entity_id=str(payload.get("license_id") or ""),
        payload={
            "organization_tin": payload.get("organization_tin"),
            "cert_serial_hex": cert.serial_hex,
            "digest_alg": digest_alg,
            "digest_prefix": digest_b64[:16],  # enough to correlate, not enough to forge
        },
    )

    return Response(
        {
            "signature_b64": base64.b64encode(signature).decode("ascii"),
            "signing_cert_pem": cert.cert_pem.decode("ascii"),
            "serial_hex": cert.serial_hex,
            "audit_event_id": str(event.id),
        }
    )


class _PrehashedSHA256:
    """Tells the cryptography lib we're handing it an already-hashed digest.

    Tiny wrapper around hashes.SHA256 + Prehashed so the signing path
    is one ``private_key.sign(digest, padding, algorithm)`` call. Saves
    a roundabout import from ``cryptography.hazmat.primitives.asymmetric.utils``.
    """

    def __new__(cls) -> Any:
        from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

        return Prehashed(hashes.SHA256())
