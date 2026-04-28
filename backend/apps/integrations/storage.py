"""S3-compatible object storage abstraction.

Per ARCHITECTURE.md, S3 holds every binary in the system: original uploaded
invoices, generated signed XML documents, audit-log archive bundles, and
exports. The application is the only writer; customer access goes through
short-lived pre-signed URLs minted by Django.

INTEGRATION_CATALOG.md is silent on the key/bucket structure, so this module
*is* the design:

  Bucket layout (one bucket per object class)
  -------------------------------------------
    zerokey-uploads     — IngestionJob originals (PDF/image/Excel/CSV/ZIP)
    zerokey-signed      — Generated signed XML invoices submitted to LHDN
    zerokey-exports     — User-requested exports (audit bundles, archive zips)

  Key prefix conventions
  ----------------------
    tenants/{org_id}/ingestion/{job_id}/{filename}    — uploads
    tenants/{org_id}/invoices/{invoice_id}/signed.xml — signed
    tenants/{org_id}/exports/{export_id}/{name}       — exports

  ``tenants/{org_id}/`` everywhere makes IAM scoping by prefix straightforward
  in production and means a misrouted object is structurally impossible to
  mistake for one belonging to another tenant.

  Pre-signed URLs
  ---------------
  TTL defaults to 5 minutes (``DEFAULT_PRESIGNED_URL_TTL``). Long enough for
  a browser to redirect-and-fetch, short enough that a leaked URL has limited
  blast radius. Production hardening: consider tying URLs to the requester's
  IP/UA via signed cookies if leakage becomes a concern.

  Encryption
  ----------
  Bucket-level KMS encryption is configured at the infrastructure layer, not
  here. Object-level CMK overrides happen for certificate blobs only (those
  go through a separate envelope-encryption path in the signing service).

In dev we point the same boto3 client at MinIO via ``S3_ENDPOINT_URL``. The
production swap to AWS S3 is a config change, not a code change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import IO, Any
from uuid import UUID

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_PRESIGNED_URL_TTL = 300  # seconds — 5 minutes


@dataclass(frozen=True)
class StoredObject:
    """Pointer to a successfully written S3 object."""

    bucket: str
    key: str
    size: int
    content_type: str


class StorageError(Exception):
    """Wraps boto3 ClientError with a flat message."""


def _client() -> Any:
    """Build a boto3 S3 client from settings.

    A new client per call is fine: boto3 is thread-safe and the cost is
    negligible compared to the network call. Caching it would require care
    around forks (Celery workers fork after import).
    """
    endpoint_url = getattr(settings, "S3_ENDPOINT_URL", None) or None
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=getattr(settings, "S3_REGION", "ap-southeast-5"),
        aws_access_key_id=getattr(settings, "S3_ACCESS_KEY", None),
        aws_secret_access_key=getattr(settings, "S3_SECRET_KEY", None),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},  # MinIO requires path style
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _public_client() -> Any:
    """Same as ``_client`` but uses the public-facing endpoint URL.

    Pre-signed URLs are signed against an endpoint; in dev the backend talks
    to MinIO at ``http://minio:9000`` (internal docker DNS) but the browser
    has to talk to it at ``http://localhost:9000``. Pre-signed URLs are bound
    to the host they were signed for, so we sign with the public endpoint.
    """
    endpoint_url = getattr(settings, "S3_PUBLIC_ENDPOINT_URL", None) or getattr(
        settings, "S3_ENDPOINT_URL", None
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=getattr(settings, "S3_REGION", "ap-southeast-5"),
        aws_access_key_id=getattr(settings, "S3_ACCESS_KEY", None),
        aws_secret_access_key=getattr(settings, "S3_SECRET_KEY", None),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


# --- Key builders -------------------------------------------------------------------


def ingestion_object_key(*, organization_id: UUID | str, job_id: UUID | str, filename: str) -> str:
    """Per the design above: tenants/{org}/ingestion/{job}/{filename}."""
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"tenants/{organization_id}/ingestion/{job_id}/{safe_name}"


def signed_invoice_key(*, organization_id: UUID | str, invoice_id: UUID | str) -> str:
    return f"tenants/{organization_id}/invoices/{invoice_id}/signed.xml"


def export_key(*, organization_id: UUID | str, export_id: UUID | str, filename: str) -> str:
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"tenants/{organization_id}/exports/{export_id}/{safe_name}"


# --- Operations ---------------------------------------------------------------------


def put_object(
    *,
    bucket: str,
    key: str,
    body: IO[bytes] | bytes,
    content_type: str,
) -> StoredObject:
    """Upload an object. Streams the body where possible (boto3 manages it)."""
    try:
        _client().put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    except ClientError as exc:
        raise StorageError(f"failed to write s3://{bucket}/{key}: {exc}") from exc

    # HEAD it to confirm size; cheaper than tracking the upload size up-front.
    try:
        head = _client().head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        raise StorageError(f"wrote but could not stat s3://{bucket}/{key}: {exc}") from exc

    return StoredObject(
        bucket=bucket,
        key=key,
        size=int(head["ContentLength"]),
        content_type=head.get("ContentType", content_type),
    )


def presigned_download_url(*, bucket: str, key: str, ttl: int = DEFAULT_PRESIGNED_URL_TTL) -> str:
    """Mint a short-lived signed URL the browser can redirect to."""
    try:
        return _public_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=ttl,
        )
    except ClientError as exc:
        raise StorageError(f"failed to sign url for s3://{bucket}/{key}: {exc}") from exc


def delete_object(*, bucket: str, key: str) -> None:
    try:
        _client().delete_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        raise StorageError(f"failed to delete s3://{bucket}/{key}: {exc}") from exc
