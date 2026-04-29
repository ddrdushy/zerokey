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


class LHDNRateLimitError(LHDNError):
    """LHDN returned 429. Carries ``retry_after_seconds`` parsed from
    the Retry-After header; -1 if absent. Caller (Celery task wrapper)
    schedules a retry with that delay."""

    def __init__(self, message: str, retry_after_seconds: int = -1) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LHDNDuplicateError(LHDNError):
    """422 with code ``DuplicateSubmission`` — identical document
    hash submitted within 10 minutes. Per spec, the customer should
    wait for the original to validate rather than retry."""

    def __init__(self, message: str, retry_after_seconds: int = -1) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LHDNCancellationWindowError(LHDNError):
    """400 with code ``OperationPeriodOver`` — invoice is past the
    72-hour cancellation window. The caller surfaces a "use a credit
    note instead" message to the customer."""


@dataclass
class LHDNCredentials:
    base_url: str
    client_id: str
    client_secret: str
    tin: str
    environment: str  # sandbox | production
    # LHDN's portal hostname for QR / "view on MyInvois" links.
    # Distinct from base_url (API) — customers visit this to verify
    # a published document via its longId. Optional for back-compat
    # with rows saved before the portal_url field was introduced;
    # the QR construction degrades gracefully when missing.
    portal_url: str = ""


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
        raise LHDNError("LHDN MyInvois integration not configured for this organization.")

    env = row.active_environment
    column = f"{env}_credentials"
    plain = decrypt_dict_values(getattr(row, column) or {})

    missing = [k for k in ("client_id", "client_secret", "base_url", "tin") if not plain.get(k)]
    if missing:
        raise LHDNError(
            f"LHDN {env} credentials missing fields: {missing}. "
            f"Configure them in Settings → Integrations."
        )

    # Portal URL is optional in the schema; pick from the row, then
    # fall back to LHDN's published default for the active env so the
    # QR-link constructor always has *something* sane to work with.
    portal = (plain.get("portal_url") or "").strip().rstrip("/")
    if not portal:
        portal = (
            "https://preprod.myinvois.hasil.gov.my"
            if env == "sandbox"
            else "https://myinvois.hasil.gov.my"
        )

    return LHDNCredentials(
        base_url=plain["base_url"].rstrip("/"),
        client_id=plain["client_id"],
        client_secret=plain["client_secret"],
        tin=plain["tin"],
        environment=env,
        portal_url=portal,
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
        raise LHDNAuthError(f"LHDN auth request failed: {type(exc).__name__}") from exc

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

    # Per LHDN integration spec §3.2: cache TTL = expires_in - 300
    # (5-minute buffer). Proactive renewal before expiry avoids 401s
    # in flight on long-running submission jobs that read a "fresh"
    # token but don't actually call LHDN until 4 minutes later.
    _token_cache[cache_key] = (token, time.time() + expires_in - 300)
    return token


def submit_documents(
    *, creds: LHDNCredentials, signed_xml_documents: list[dict[str, Any]]
) -> dict[str, Any]:
    """POST one or more signed UBL invoices to LHDN.

    ``signed_xml_documents`` is a list of envelope dicts produced by
    :func:`encode_for_submission`. LHDN's request shape:

        {
          "documents": [
            {
              "format": "XML",
              "documentHash": "<sha256-hex>",
              "codeNumber": "<unique caller-generated id>",
              "document": "<base64 of the XML>"
            },
            ...
          ]
        }

    Per spec §4.1 batch constraints:
      - Max 100 documents per submission
      - Max 5 MB total submission size
      - Max 300 KB per document (post-base64)

    The guards here raise ``LHDNError`` (programmer error) before
    any network call rather than letting LHDN reject — the caller
    is responsible for splitting batches.

    LHDN's response carries a top-level ``submissionUid`` we use to
    poll status. 429 raises ``LHDNRateLimitError`` with the
    Retry-After value parsed; the caller respects it. 422 with
    ``DuplicateSubmission`` raises ``LHDNDuplicateError``.
    """
    _enforce_batch_limits(signed_xml_documents)

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
        raise LHDNError(f"LHDN submit request failed: {type(exc).__name__}") from exc

    if response.status_code == 401:
        raise LHDNAuthError("LHDN rejected the bearer token.")
    if response.status_code == 429:
        raise LHDNRateLimitError(
            "LHDN rate limit exceeded.",
            retry_after_seconds=_parse_retry_after(response),
        )
    if response.status_code in (400, 422):
        body = _safe_json(response)
        code = _extract_error_code(body)
        if code == "DuplicateSubmission":
            raise LHDNDuplicateError(
                _safe_json_dump(body),
                retry_after_seconds=_parse_retry_after(response),
            )
        if code == "OperationPeriodOver":
            raise LHDNCancellationWindowError(_safe_json_dump(body))
        # Generic schema / business rule failure.
        raise LHDNValidationError(_safe_json_dump(body))
    if response.status_code >= 500:
        raise LHDNError(f"LHDN server error: HTTP {response.status_code}")
    if response.status_code != 202:
        raise LHDNError(f"Unexpected LHDN response: HTTP {response.status_code}")

    return response.json()


# Per LHDN integration spec §4.1.
MAX_DOCUMENTS_PER_SUBMISSION = 100
MAX_TOTAL_SUBMISSION_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_PER_DOCUMENT_BYTES = 300 * 1024  # 300 KB


def _enforce_batch_limits(documents: list[dict[str, Any]]) -> None:
    if len(documents) > MAX_DOCUMENTS_PER_SUBMISSION:
        raise LHDNError(
            f"Batch too large: {len(documents)} documents > "
            f"{MAX_DOCUMENTS_PER_SUBMISSION} max. Split into smaller batches."
        )
    total = 0
    for idx, doc in enumerate(documents):
        # The envelope's ``document`` field is the base64 payload —
        # what LHDN actually counts toward the 300 KB limit.
        encoded = doc.get("document", "")
        size = len(encoded)
        if size > MAX_PER_DOCUMENT_BYTES:
            raise LHDNError(
                f"Document #{idx} is {size} bytes (post-base64) > {MAX_PER_DOCUMENT_BYTES} max."
            )
        total += size
    if total > MAX_TOTAL_SUBMISSION_BYTES:
        raise LHDNError(
            f"Submission total {total} bytes > {MAX_TOTAL_SUBMISSION_BYTES} max. Split the batch."
        )


def _parse_retry_after(response: httpx.Response) -> int:
    """Read the Retry-After header. Returns -1 if absent / malformed."""
    raw = response.headers.get("Retry-After", "").strip()
    if not raw:
        return -1
    try:
        return int(raw)
    except ValueError:
        # The HTTP spec also allows an HTTP-date in Retry-After. We
        # don't see that format from LHDN today; if we ever do, parse
        # it here. For now, treating an unrecognized format as "no
        # hint" + falling back to the worker's standard backoff is
        # safe + simple.
        return -1


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError):
        return {"raw": response.text[:512]}


def _extract_error_code(body: Any) -> str:
    """Pull the LHDN error code out of an error response body.

    LHDN returns either ``{"code": "...", "message": "..."}`` or a
    nested envelope ``{"error": {"code": "...", ...}}``. Be tolerant
    of both shapes.
    """
    if not isinstance(body, dict):
        return ""
    if isinstance(body.get("error"), dict):
        code = body["error"].get("code")
        if code:
            return str(code)
    code = body.get("code") or body.get("errorCode")
    return str(code) if code else ""


def encode_for_submission(*, signed_xml_bytes: bytes, code_number: str) -> dict[str, str]:
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


def get_submission_status(*, creds: LHDNCredentials, submission_uid: str) -> dict[str, Any]:
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
    return _authed_get(creds=creds, url=url, what="submission")


def get_document_raw(*, creds: LHDNCredentials, document_uuid: str) -> dict[str, Any]:
    """Fetch a validated document (per spec §4.4: ``/raw``).

    Returns the document body wrapped in LHDN's envelope. The
    ``longId`` field is the slug used to construct the public QR /
    verification URL on the portal hostname:
    ``{portal_url}/{uuid}/share/{longId}``.
    """
    url = urljoin(
        creds.base_url + "/",
        f"api/v1.0/documents/{document_uuid}/raw",
    )
    return _authed_get(creds=creds, url=url, what="document")


# Back-compat alias — Slice 58 callers used get_document_qr.
get_document_qr = get_document_raw


def cancel_document(
    *,
    creds: LHDNCredentials,
    document_uuid: str,
    reason: str,
) -> dict[str, Any]:
    """Cancel a validated document within the 72-hour window.

    Per spec §4.3, the endpoint is ``PUT /api/v1.0/documents/state/
    {uuid}/state`` with body ``{"status": "cancelled", "reason": "..."}``.
    LHDN's 400 ``OperationPeriodOver`` surfaces as
    ``LHDNCancellationWindowError`` so the caller can redirect the
    operator to issue a credit note instead.
    """
    if not reason or not reason.strip():
        raise LHDNError("Cancellation reason is required.")
    url = urljoin(
        creds.base_url + "/",
        f"api/v1.0/documents/state/{document_uuid}/state",
    )
    token = get_access_token(creds)
    try:
        response = httpx.put(
            url,
            json={"status": "cancelled", "reason": reason.strip()[:300]},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise LHDNError(f"LHDN cancel request failed: {type(exc).__name__}") from exc

    if response.status_code == 401:
        raise LHDNAuthError("LHDN rejected the bearer token.")
    if response.status_code == 404:
        raise LHDNNotFoundError(f"Document {document_uuid} not found.")
    if response.status_code == 429:
        raise LHDNRateLimitError(
            "LHDN rate limit exceeded.",
            retry_after_seconds=_parse_retry_after(response),
        )
    if response.status_code in (400, 422):
        body = _safe_json(response)
        code = _extract_error_code(body)
        if code == "OperationPeriodOver":
            raise LHDNCancellationWindowError(_safe_json_dump(body))
        raise LHDNValidationError(_safe_json_dump(body))
    if response.status_code >= 500:
        raise LHDNError(f"LHDN server error: HTTP {response.status_code}")
    if response.status_code not in (200, 204):
        raise LHDNError(f"Unexpected LHDN cancel response: HTTP {response.status_code}")

    return _safe_json(response) or {"status": "cancelled"}


def validate_tin(*, creds: LHDNCredentials, tin: str) -> bool:
    """Check whether LHDN recognizes a TIN (per spec §4.5).

    Per LHDN docs, the response body is empty + the status code
    distinguishes the outcome. Used by the customer-master enrich
    path before submission to catch typo'd buyer TINs early.

    Returns ``True`` if LHDN accepts the TIN, ``False`` if it
    rejects it. Raises ``LHDNError`` for connectivity / auth
    failures so the caller can degrade gracefully (treat unknown
    as "not validated" rather than "invalid").
    """
    tin = (tin or "").strip()
    if not tin:
        return False
    url = urljoin(creds.base_url + "/", f"api/v1.0/taxpayer/validate/{tin}")
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
        raise LHDNError(f"LHDN TIN validation failed: {type(exc).__name__}") from exc

    if response.status_code == 401:
        raise LHDNAuthError("LHDN rejected the bearer token.")
    if response.status_code == 200:
        return True
    if response.status_code == 404:
        return False
    if response.status_code == 429:
        raise LHDNRateLimitError(
            "LHDN rate limit exceeded.",
            retry_after_seconds=_parse_retry_after(response),
        )
    if response.status_code >= 500:
        raise LHDNError(f"LHDN server error: HTTP {response.status_code}")
    raise LHDNError(f"Unexpected LHDN TIN-validate response: HTTP {response.status_code}")


def _authed_get(*, creds: LHDNCredentials, url: str, what: str) -> dict[str, Any]:
    """Common GET path: bearer auth + status-code routing.

    Used by ``get_submission_status`` and ``get_document_raw``.
    Each maps to the same set of typed errors.
    """
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
        raise LHDNError(f"LHDN {what} request failed: {type(exc).__name__}") from exc

    if response.status_code == 401:
        raise LHDNAuthError("LHDN rejected the bearer token.")
    if response.status_code == 404:
        raise LHDNNotFoundError(f"LHDN {what} not found.")
    if response.status_code == 429:
        raise LHDNRateLimitError(
            "LHDN rate limit exceeded.",
            retry_after_seconds=_parse_retry_after(response),
        )
    if response.status_code != 200:
        raise LHDNError(f"Unexpected LHDN {what} response: HTTP {response.status_code}")

    return response.json()


def _safe_json_dump(body: Any) -> str:
    try:
        return json.dumps(body)[:1024]
    except (TypeError, ValueError):
        return str(body)[:1024]
