"""LHDN MyInvois client (Slice 58).

Thin HTTP client over LHDN's MyInvois API. Reads its credentials
from the customer's ``OrganizationIntegration`` row (Slice 57)
based on the active environment (sandbox / production). Today's
endpoints:

  - POST /connect/token
       OAuth2 client_credentials grant — returns an access token.
  - POST /api/v1.0/documentsubmissions
       Submit one or more signed UBL invoices.
  - GET  /api/v1.0/documentsubmissions/{submission_id}
       Poll a submission's status. Per LHDN docs the response
       includes per-document UUIDs once issued.
  - GET  /api/v1.0/documents/{uuid}/details
       Read back the LHDN-stored document (carries the QR URL).

This module is deliberately small — it formats requests, parses
responses, raises typed errors. The retry / polling / state-
machine logic lives in ``apps.submission.services``. The signing
+ XML production is upstream in ``apps.submission.signing``.

LHDN API reference:
  https://sdk.myinvois.hasil.gov.my/  (rate-limited; cite, don't fetch)

Token caching:
  Each successful token request is cached on the
  ``OrganizationIntegration`` row's last_test cursor to avoid
  re-authing on every submit. Real production caches in Redis
  with the LHDN-provided expires_in; the dev path caches per
  process for simplicity.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from apps.administration.crypto import decrypt_dict_values

logger = logging.getLogger(__name__)


# Sane HTTP timeout per request. LHDN occasionally lags during
# enforcement deadlines; 20s tolerates the spike without holding
# the worker forever.
REQUEST_TIMEOUT_SECONDS = 20.0


class LHDNError(Exception):
    """Base class for LHDN API errors."""


class LHDNAuthError(LHDNError):
    """Token request failed (bad credentials, expired)."""


class LHDNValidationError(LHDNError):
    """Submission was rejected by LHDN's pre-validation
    (schema, signature, business rules)."""


class LHDNNotFoundError(LHDNError):
    """Submission ID or document UUID doesn't exist on LHDN's side."""


@dataclass
class LHDNCredentials:
    base_url: str
    client_id: str
    client_secret: str
    tin: str
    environment: str  # sandbox | production


def credentials_for_org(*, organization_id: uuid.UUID | str) -> LHDNCredentials:
    """Resolve the org's active-environment LHDN creds.

    Reads the ``OrganizationIntegration`` row + decrypts the
    credentials for whichever environment is currently active.
    Raises ``LHDNError`` if the integration isn't configured.
    """
    from apps.identity.models import OrganizationIntegration
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason="lhdn_client.cred_lookup"):
        row = OrganizationIntegration.objects.filter(
            organization_id=organization_id,
            integration_key="lhdn_myinvois",
        ).first()

    if row is None:
        raise LHDNError(
            "LHDN MyInvois integration not configured for this organization."
        )

    env = row.active_environment
    column = f"{env}_credentials"
    plain = decrypt_dict_values(getattr(row, column) or {})

    missing = [
        k for k in ("client_id", "client_secret", "base_url", "tin")
        if not plain.get(k)
    ]
    if missing:
        raise LHDNError(
            f"LHDN {env} credentials missing fields: {missing}. "
            f"Configure them in Settings → Integrations."
        )

    return LHDNCredentials(
        base_url=plain["base_url"].rstrip("/"),
        client_id=plain["client_id"],
        client_secret=plain["client_secret"],
        tin=plain["tin"],
        environment=env,
    )


# Process-local token cache. Maps (client_id, base_url) → (token, expires_at).
# Production swap point: replace with Redis if we want cache
# coherence across worker processes. For Slice 58 + low-volume
# submission cadence the per-process cache is plenty.
_token_cache: dict[tuple[str, str], tuple[str, float]] = {}


def get_access_token(creds: LHDNCredentials, *, force: bool = False) -> str:
    """OAuth2 client-credentials token. Cached per (client_id, base_url).

    ``force=True`` bypasses the cache (used by test_connection so
    operators see a real auth call, not a cached hit).
    """
    cache_key = (creds.client_id, creds.base_url)
    if not force:
        cached = _token_cache.get(cache_key)
        if cached is not None and cached[1] > time.time():
            return cached[0]

    url = urljoin(creds.base_url + "/", "connect/token")
    try:
        response = httpx.post(
            url,
            data={
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "grant_type": "client_credentials",
                "scope": "InvoicingAPI",
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise LHDNAuthError(
            f"LHDN auth request failed: {type(exc).__name__}"
        ) from exc

    if response.status_code != 200:
        # LHDN returns OAuth2-style error JSON ({"error": "invalid_client",
        # "error_description": "..."}) on 4xx. We surface the error
        # code only — the description sometimes echoes parts of the
        # client_id which is fine, but never the secret.
        try:
            err_body = response.json()
            err_code = err_body.get("error", "unknown_error")
        except (json.JSONDecodeError, ValueError):
            err_code = f"HTTP {response.status_code}"
        raise LHDNAuthError(f"LHDN auth rejected: {err_code}")

    body = response.json()
    token = body.get("access_token")
    expires_in = int(body.get("expires_in", 3600))
    if not token:
        raise LHDNAuthError("LHDN auth response missing access_token.")

    # Bake in a 60s safety margin so we don't try to use a token
    # 1ms before LHDN considers it expired.
    _token_cache[cache_key] = (token, time.time() + expires_in - 60)
    return token


def submit_documents(
    *, creds: LHDNCredentials, signed_xml_documents: list[str]
) -> dict[str, Any]:
    """POST one or more signed UBL invoices to LHDN.

    ``signed_xml_documents`` is a list of base64-encoded UTF-8
    XML payloads. LHDN's request shape is:

        {
          "documents": [
            {
              "format": "XML",
              "documentHash": "<sha256-base64>",
              "codeNumber": "<unique caller-generated id>",
              "document": "<base64 of the XML>"
            },
            ...
          ]
        }

    Today we accept the already-base64-encoded payload (the caller
    wraps the call with ``encode_for_submission``). LHDN's response
    carries a top-level ``submissionUid`` we use to poll status.
    """
    url = urljoin(creds.base_url + "/", "api/v1.0/documentsubmissions")
    token = get_access_token(creds)
    payload = {"documents": signed_xml_documents}
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise LHDNError(
            f"LHDN submit request failed: {type(exc).__name__}"
        ) from exc

    if response.status_code == 401:
        raise LHDNAuthError("LHDN rejected the bearer token.")
    if response.status_code in (400, 422):
        # 400/422 — schema or business-rule rejection. Body carries
        # per-document errors. Return as a typed exception with the
        # response body so the caller can persist it on the invoice.
        raise LHDNValidationError(_safe_json_dump(response.json()))
    if response.status_code >= 500:
        raise LHDNError(f"LHDN server error: HTTP {response.status_code}")
    if response.status_code != 202:
        raise LHDNError(
            f"Unexpected LHDN response: HTTP {response.status_code}"
        )

    return response.json()


def encode_for_submission(
    *, signed_xml_bytes: bytes, code_number: str
) -> dict[str, str]:
    """Wrap one signed XML document in LHDN's submit envelope.

    ``code_number`` is a caller-supplied unique identifier (we use
    the Invoice's ``invoice_number`` or its UUID); LHDN echoes it
    back in submission status responses so we can correlate.
    """
    import base64
    import hashlib

    digest = hashlib.sha256(signed_xml_bytes).hexdigest()
    return {
        "format": "XML",
        "documentHash": digest,
        "codeNumber": code_number,
        "document": base64.b64encode(signed_xml_bytes).decode("ascii"),
    }


def get_submission_status(
    *, creds: LHDNCredentials, submission_uid: str
) -> dict[str, Any]:
    """Poll LHDN for a submission's current state.

    Response carries:
      - ``submissionUid``
      - ``documentSummary`` array — each item has ``uuid``,
        ``status`` (``Submitted``, ``Valid``, ``Invalid``,
        ``Cancelled``), ``invoiceCodeNumber``.
      - ``overallStatus`` — ``InProgress`` until LHDN finishes
        validation, then ``Valid`` / ``Invalid`` / ``Partial``.
    """
    url = urljoin(
        creds.base_url + "/",
        f"api/v1.0/documentsubmissions/{submission_uid}",
    )
    token = get_access_token(creds)
    try:
        response = httpx.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise LHDNError(
            f"LHDN status request failed: {type(exc).__name__}"
        ) from exc

    if response.status_code == 401:
        raise LHDNAuthError("LHDN rejected the bearer token.")
    if response.status_code == 404:
        raise LHDNNotFoundError(
            f"Submission {submission_uid} not found on LHDN."
        )
    if response.status_code != 200:
        raise LHDNError(
            f"Unexpected LHDN response: HTTP {response.status_code}"
        )

    return response.json()


def get_document_qr(
    *, creds: LHDNCredentials, document_uuid: str
) -> dict[str, Any]:
    """Fetch a validated document's metadata (carries the QR URL)."""
    url = urljoin(
        creds.base_url + "/",
        f"api/v1.0/documents/{document_uuid}/details",
    )
    token = get_access_token(creds)
    try:
        response = httpx.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise LHDNError(
            f"LHDN document fetch failed: {type(exc).__name__}"
        ) from exc

    if response.status_code == 401:
        raise LHDNAuthError("LHDN rejected the bearer token.")
    if response.status_code == 404:
        raise LHDNNotFoundError(
            f"Document {document_uuid} not found on LHDN."
        )
    if response.status_code != 200:
        raise LHDNError(
            f"Unexpected LHDN response: HTTP {response.status_code}"
        )

    return response.json()


def _safe_json_dump(body: Any) -> str:
    try:
        return json.dumps(body)[:1024]
    except (TypeError, ValueError):
        return str(body)[:1024]
