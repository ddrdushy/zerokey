"""API key creation / listing / revocation services.

Per SECURITY.md: the plaintext is shown ONCE at creation and never
persisted. Storage is ``key_prefix`` (lookup index) + ``key_hash``
(SHA-256 of plaintext for verification). The same plaintext can never
be reconstructed from the row — a customer who lost the key has to
revoke and create a new one.

Revocation is soft delete: ``is_active=False`` + ``revoked_at`` so
audit-log queries by ``actor_id=APIKey.id`` keep resolving forever.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import APIKey, User


# Customer-visible prefix that disambiguates dev / live / sandbox keys.
# Today only "live" — sandbox lands when we have a sandbox environment
# story.
_KEY_PREFIX = "zk_live_"

# Length of the random body. 40 chars of base32 gives ~200 bits of
# entropy, which is overkill but cheap. Plus the 8-char prefix = 48
# total characters in the plaintext.
_RANDOM_LEN = 40

# Number of plaintext characters that make up the stored prefix
# (key_prefix column). 12 = "zk_live_" + 4 random chars — long enough
# for the customer UI to visually distinguish "zk_live_AbCd…" from
# "zk_live_XyZw…" without leaking the secret.
_PREFIX_LEN = 12


class APIKeyError(Exception):
    """Raised when an API-key operation can't be applied."""


def _hash(plaintext: str) -> str:
    """SHA-256 hex of the plaintext. The stored verification value."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _random_plaintext() -> str:
    """Build a fresh, fully-random plaintext key.

    URL-safe base64 trimmed to length, plus our env prefix. Not
    a cryptographic property — just keeps the rendered key readable.
    """
    body = secrets.token_urlsafe(_RANDOM_LEN)[:_RANDOM_LEN]
    return f"{_KEY_PREFIX}{body}"


def create_api_key(
    *,
    organization_id: uuid.UUID | str,
    label: str,
    actor_user: User,
) -> tuple[APIKey, str]:
    """Mint a new API key, return ``(row, plaintext)``.

    ``plaintext`` is shown ONCE to the customer at the call site and
    must not be persisted anywhere else. The row stores only
    ``key_prefix`` (for lookup) + ``key_hash`` (for verify).

    Audited as ``identity.api_key.created`` with the prefix + label
    in the payload — the prefix is the public identifier customers
    see in the UI, so it's safe to include.
    """
    label = (label or "").strip()
    if not label:
        raise APIKeyError("label is required.")
    if len(label) > 64:
        raise APIKeyError("label must be 64 characters or fewer.")

    plaintext = _random_plaintext()
    prefix = plaintext[:_PREFIX_LEN]
    hashed = _hash(plaintext)

    row = APIKey.objects.create(
        organization_id=organization_id,
        label=label,
        key_prefix=prefix,
        key_hash=hashed,
        created_by_user_id=actor_user.id,
        is_active=True,
    )

    record_event(
        action_type="identity.api_key.created",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user.id),
        organization_id=str(organization_id),
        affected_entity_type="APIKey",
        affected_entity_id=str(row.id),
        payload={"label": label, "key_prefix": prefix},
    )
    return row, plaintext


def list_api_keys(
    *, organization_id: uuid.UUID | str
) -> list[dict[str, Any]]:
    """List active + revoked keys for the org. Plaintext NEVER returned."""
    qs = APIKey.objects.filter(organization_id=organization_id).order_by(
        "-created_at"
    )
    return [
        {
            "id": str(k.id),
            "label": k.label,
            "key_prefix": k.key_prefix,
            "is_active": bool(k.is_active),
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "created_by_user_id": str(k.created_by_user_id)
            if k.created_by_user_id
            else None,
            "last_used_at": k.last_used_at.isoformat()
            if k.last_used_at
            else None,
            "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
        }
        for k in qs
    ]


def revoke_api_key(
    *,
    organization_id: uuid.UUID | str,
    api_key_id: uuid.UUID | str,
    actor_user: User,
) -> dict[str, Any]:
    """Soft-revoke an API key. Idempotent on already-revoked rows."""
    try:
        row = APIKey.objects.get(
            id=api_key_id, organization_id=organization_id
        )
    except APIKey.DoesNotExist as exc:
        raise APIKeyError(
            f"API key {api_key_id} not found in this organization."
        ) from exc

    if not row.is_active:
        # Already revoked — return current shape, no audit noise.
        return _row_to_dict(row)

    row.is_active = False
    row.revoked_at = timezone.now()
    row.revoked_by_user_id = actor_user.id
    row.save(update_fields=["is_active", "revoked_at", "revoked_by_user_id", "updated_at"])

    record_event(
        action_type="identity.api_key.revoked",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user.id),
        organization_id=str(organization_id),
        affected_entity_type="APIKey",
        affected_entity_id=str(row.id),
        payload={"key_prefix": row.key_prefix, "label": row.label},
    )
    return _row_to_dict(row)


def _row_to_dict(row: APIKey) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "label": row.label,
        "key_prefix": row.key_prefix,
        "is_active": bool(row.is_active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }
