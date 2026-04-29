"""Notification preference services.

Preferences are per-user, per-tenant — one row per (user, organization)
pair, holding a `preferences` JSON dict keyed by event name with
``{"in_app": bool, "email": bool}`` per event. Empty dict = platform
defaults (everything on); we materialise the row lazily on first save.

Event allowlist enforced here so the schema is documented in one place
and a typo on the customer side rejects rather than silently saves an
unknown event key.

Future: the bell aggregator (Slice 28) and the email channel (when it
ships) will both read these preferences before delivering. Today only
the customer-side editor surface uses them; the runtime side hasn't
landed yet — that's a follow-up slice.
"""

from __future__ import annotations

import uuid
from typing import Any

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import NotificationPreference, User

# Canonical list of events the user can express a preference about.
# Each entry: (key, label, description). The UI renders the list in
# this order. Adding an event is a one-line change here; existing
# rows that don't have a setting for the new event fall back to "on".
EVENT_KEYS: list[tuple[str, str, str]] = [
    (
        "inbox.item_opened",
        "New inbox item",
        "An invoice flagged for human attention.",
    ),
    (
        "invoice.validated",
        "Invoice validated",
        "An invoice passed all LHDN-shape checks.",
    ),
    (
        "invoice.lhdn_rejected",
        "LHDN rejection",
        "MyInvois rejected an invoice you submitted.",
    ),
    (
        "audit.chain_verified",
        "Chain verification",
        "The customer-triggered or scheduled chain verifier ran.",
    ),
    (
        "organization.membership.updated",
        "Member access change",
        "An owner or admin changed someone's role or active state.",
    ),
]

VALID_CHANNELS = {"in_app", "email"}


class NotificationPreferenceError(Exception):
    """Raised when a preferences update is invalid."""


def get_preferences(*, organization_id: uuid.UUID | str, user: User) -> dict[str, Any]:
    """Return current per-event preferences for the user in this org.

    Auto-materialises a row with ``{}`` (platform defaults) if none
    exists — same lazy-init pattern as the SystemSetting resolver.
    Returns the schema (event allowlist + label + description) plus
    the user's current settings, so the UI renders both pieces from
    one round-trip.
    """
    row, _ = NotificationPreference.objects.get_or_create(
        organization_id=organization_id,
        user=user,
        defaults={"preferences": {}},
    )
    stored = row.preferences or {}

    events_out: list[dict[str, Any]] = []
    for key, label, description in EVENT_KEYS:
        per_event = stored.get(key, {})
        events_out.append(
            {
                "key": key,
                "label": label,
                "description": description,
                "in_app": per_event.get("in_app", True),
                "email": per_event.get("email", True),
            }
        )
    return {"events": events_out}


def set_preferences(
    *,
    organization_id: uuid.UUID | str,
    user: User,
    updates: dict[str, dict[str, bool]],
) -> dict[str, Any]:
    """Replace per-event channel toggles for the user in this org.

    ``updates`` shape: ``{"<event_key>": {"in_app": bool, "email": bool}}``.
    Unknown event keys raise ``NotificationPreferenceError``. Channel
    keys outside ``VALID_CHANNELS`` are silently dropped (we'll add
    new channels over time and don't want a stale frontend to fail).

    Audited as ``identity.notification_preferences.updated`` with a
    list of event keys whose preferences changed (no boolean values
    in payload — same field-names-only convention).
    """
    if not isinstance(updates, dict):
        raise NotificationPreferenceError("Updates must be an object.")

    valid_keys = {key for key, _, _ in EVENT_KEYS}
    invalid = set(updates.keys()) - valid_keys
    if invalid:
        raise NotificationPreferenceError(
            f"Unknown event keys: {sorted(invalid)}. Allowed: {sorted(valid_keys)}"
        )

    row, _ = NotificationPreference.objects.get_or_create(
        organization_id=organization_id,
        user=user,
        defaults={"preferences": {}},
    )
    current = dict(row.preferences or {})
    changed: list[str] = []
    for event_key, channels in updates.items():
        if not isinstance(channels, dict):
            raise NotificationPreferenceError(f"Channels for {event_key!r} must be an object.")
        sanitised = {ch: bool(v) for ch, v in channels.items() if ch in VALID_CHANNELS}
        if current.get(event_key, {}) != sanitised:
            current[event_key] = sanitised
            changed.append(event_key)

    if changed:
        row.preferences = current
        row.save(update_fields=["preferences", "updated_at"])
        record_event(
            action_type="identity.notification_preferences.updated",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(user.id),
            organization_id=str(organization_id),
            affected_entity_type="NotificationPreference",
            affected_entity_id=str(row.id),
            payload={"event_keys_changed": sorted(changed)},
        )

    return get_preferences(organization_id=organization_id, user=user)
