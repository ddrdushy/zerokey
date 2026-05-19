"""Desktop-side client for the cloud's intermediary signing endpoint.

Phase 3 of DESKTOP_PIVOT_PLAN.md.

Used by ``apps.submission.certificates.ensure_certificate()`` when an
org is in ``signing_mode='intermediary'``. The flow:

  1. Desktop builds the unsigned MyInvois XML.
  2. Canonicalises the SignedInfo (XAdES BES — same logic the cloud
     used to run server-side; moves with the rest of submission/).
  3. SHA-256 digests those bytes.
  4. Calls ``sign_document(digest, entitlement)`` here.
  5. We POST to the cloud, get back signature + cert PEM, wrap them
     into a ``RemoteSignedBundle`` that the caller assembles into the
     final XAdES envelope.

We never send the canonicalised XML itself — only the digest. The
cloud has no record of invoice contents; this is load-bearing for the
privacy story.

Failure modes:
  - Network down / cloud down → ``CloudSigningUnavailable``. Caller
    (Phase 3 update to ``ensure_certificate``) queues the document as
    ``waiting_to_sign`` and surfaces a banner.
  - Entitlement invalid (revoked, malformed) → ``CloudSigningRejected``.
    Caller surfaces "license problem — open Settings".
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from typing import Final

import urllib.error
import urllib.request
import json

logger = logging.getLogger(__name__)

DEFAULT_API_BASE: Final = "https://zerokey.symprio.com"
SIGN_PATH: Final = "/api/v1/licenses/sign/document/"

# Network timeout for one signing call. Picked low because LHDN itself
# enforces deadlines; if we're spending more than 5s round-tripping a
# digest the customer is going to see a stall they can't act on.
DEFAULT_TIMEOUT_SEC: Final = 5.0


class CloudSigningError(Exception):
    """Base for cloud signing failures."""


class CloudSigningUnavailable(CloudSigningError):
    """Network or cloud-side error — retry-friendly."""


class CloudSigningRejected(CloudSigningError):
    """Cloud refused the request — license / entitlement issue.

    ``code`` mirrors the JSON ``code`` field from the cloud:
    ``invalid_entitlement``, ``intermediary_not_permitted``,
    ``entitlement_not_active``, etc.
    """

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RemoteSignedBundle:
    signature: bytes
    signing_cert_pem: bytes
    serial_hex: str
    audit_event_id: str


def _api_base() -> str:
    return os.environ.get("ZK_LICENSE_API_BASE") or DEFAULT_API_BASE


def sign_document(
    *,
    digest: bytes,
    entitlement: str,
    digest_alg: str = "SHA-256",
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> RemoteSignedBundle:
    """Sign ``digest`` via the cloud intermediary key.

    Returns a ``RemoteSignedBundle``; the caller embeds the signature
    + cert into the XAdES envelope. ``digest`` MUST be the raw
    SHA-256 of the canonicalised SignedInfo (32 bytes), not the b64
    encoding.
    """
    if len(digest) != 32:
        raise CloudSigningRejected(
            f"digest must be 32 bytes for SHA-256 (got {len(digest)})",
            code="bad_digest_length",
        )
    body = json.dumps(
        {
            "entitlement": entitlement,
            "digest_b64": base64.b64encode(digest).decode("ascii"),
            "digest_alg": digest_alg,
        }
    ).encode("utf-8")

    url = _api_base().rstrip("/") + SIGN_PATH
    req = urllib.request.Request(
        url,
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
            payload = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Cloud responded with an error code. Parse the JSON body if
        # we got one, otherwise wrap.
        try:
            err_body = json.loads(exc.read().decode("utf-8"))
        except (ValueError, AttributeError):
            err_body = {}
        code = err_body.get("code", "")
        detail = err_body.get("detail", f"HTTP {exc.code}")
        if exc.code >= 500:
            # 5xx classes as retryable.
            raise CloudSigningUnavailable(f"Cloud signing {exc.code}: {detail}") from exc
        raise CloudSigningRejected(detail, code=code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CloudSigningUnavailable(
            f"Cloud signing unreachable: {exc.__class__.__name__}: {exc}"
        ) from exc
    except ValueError as exc:
        raise CloudSigningUnavailable(
            f"Cloud signing returned non-JSON response: {exc}"
        ) from exc

    try:
        sig_bytes = base64.b64decode(payload["signature_b64"], validate=True)
        cert_pem = payload["signing_cert_pem"].encode("ascii")
        serial_hex = payload["serial_hex"]
        audit_event_id = payload["audit_event_id"]
    except (KeyError, TypeError, ValueError, base64.binascii.Error) as exc:
        raise CloudSigningUnavailable(
            f"Cloud signing returned malformed payload: {exc}"
        ) from exc

    return RemoteSignedBundle(
        signature=sig_bytes,
        signing_cert_pem=cert_pem,
        serial_hex=serial_hex,
        audit_event_id=audit_event_id,
    )
