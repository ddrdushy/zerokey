"""Live LHDN TIN verification for CustomerMaster rows (Slice 70).

Format-only TIN validation has been wired into the validation rule
set since Slice 13. This module adds the real LHDN round-trip that
asks "is this TIN actually registered with LHDN?" — the same
question LHDN's HITS validator asks at submission time.

Catching a typo'd / non-existent buyer TIN here, before the customer
hits Submit, saves a rejection round-trip. The check is async (a
Celery task fires post-enrich); the customer doesn't wait on it. The
review screen reads ``CustomerMaster.tin_verification_state`` and
renders the right pill ("Verified", "Failed verification",
"Unverified") next to the buyer name.

State transitions on the master row:

  unverified → verified         (LHDN 200 OK)
  unverified → failed           (LHDN 404 — TIN not registered)
  unverified → unverified       (any transient: 401, 429, 5xx, no creds)

Stale-revalidate: a master that was verified > VERIFY_REFRESH_DAYS
ago gets re-verified the next time it's used. LHDN can revoke
TINs (rare but possible for dissolved entities), so a "verified
14 months ago" master shouldn't be trusted blindly.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import CustomerMaster

logger = logging.getLogger(__name__)


# How fresh a "verified" verdict has to be before we trust it.
# 90 days picked because LHDN-issued TINs rarely change (a TIN
# typically outlives an organization), but 90 days is short enough
# that a dissolved entity can't keep silently passing checks for
# a year.
VERIFY_REFRESH_DAYS = 90


class TinVerificationError(Exception):
    """Raised on configuration / lookup failure (not LHDN 200 vs 404)."""


def needs_verification(master: CustomerMaster) -> bool:
    """Is this master due for a fresh LHDN TIN check?

    Skip masters with no TIN — there's nothing to verify. Skip
    ``failed`` masters that have already been hit recently (avoid
    hammering LHDN on a row we already know is bad). Re-verify
    ``verified`` masters older than ``VERIFY_REFRESH_DAYS`` so a
    revoked TIN eventually flips to failed.

    Slice 73 — ``unverified_external_source`` (a synced TIN from a
    connector) is treated like plain ``unverified``: verify
    immediately. The customer trusts the source to populate, but
    LHDN is the only authority on whether the TIN is valid.

    Slice 73 — ``manually_resolved`` is treated like ``verified``
    for the purposes of staleness — the user explicitly picked
    the value, so we re-check on the same 90-day cadence rather
    than on every enrichment.
    """
    if not master.tin:
        return False
    state = master.tin_verification_state
    if state in {
        CustomerMaster.TinVerificationState.UNVERIFIED,
        CustomerMaster.TinVerificationState.UNVERIFIED_EXTERNAL_SOURCE,
    }:
        return True
    if state == CustomerMaster.TinVerificationState.FAILED:
        # Re-check failed every VERIFY_REFRESH_DAYS — gives the
        # customer a path out if they corrected the TIN since.
        return _is_stale(master)
    if state in {
        CustomerMaster.TinVerificationState.VERIFIED,
        CustomerMaster.TinVerificationState.MANUALLY_RESOLVED,
    }:
        return _is_stale(master)
    return False


def _is_stale(master: CustomerMaster) -> bool:
    if master.tin_last_verified_at is None:
        return True
    age = timezone.now() - master.tin_last_verified_at
    return age > timedelta(days=VERIFY_REFRESH_DAYS)


def verify_master_tin(master_id: uuid.UUID | str) -> dict[str, str]:
    """Hit LHDN's TIN-validate endpoint + persist the verdict.

    Returns a small dict ``{state, reason}`` for log enrichment.
    The persisted state on the row is the source of truth.

    Never raises on LHDN-side failures — those leave the row in
    its current state (so a transient outage doesn't flip a
    legitimately-verified master to "failed"). Only configuration
    + DB errors propagate.
    """
    from apps.identity.tenancy import super_admin_context
    from apps.submission import lhdn_client

    with super_admin_context(reason="enrichment.tin_verify.lookup"):
        master = CustomerMaster.objects.filter(id=master_id).first()
    if master is None:
        raise TinVerificationError(f"CustomerMaster {master_id} not found.")
    if not master.tin:
        return {"state": "skipped", "reason": "no_tin"}

    try:
        creds = lhdn_client.credentials_for_org(organization_id=master.organization_id)
    except lhdn_client.LHDNError as exc:
        # No creds → leave the master alone. Customer hasn't
        # configured LHDN yet; they'll get verification once they do.
        logger.info(
            "enrichment.tin_verify.no_creds",
            extra={"master_id": str(master_id), "error": str(exc)},
        )
        return {"state": "skipped", "reason": "no_creds"}

    try:
        recognized = lhdn_client.validate_tin(creds=creds, tin=master.tin)
    except lhdn_client.LHDNAuthError:
        return {"state": "skipped", "reason": "lhdn_auth"}
    except lhdn_client.LHDNRateLimitError:
        return {"state": "skipped", "reason": "lhdn_rate_limit"}
    except lhdn_client.LHDNError as exc:
        logger.info(
            "enrichment.tin_verify.transient",
            extra={
                "master_id": str(master_id),
                "error_class": type(exc).__name__,
            },
        )
        return {"state": "skipped", "reason": "lhdn_transient"}

    new_state = (
        CustomerMaster.TinVerificationState.VERIFIED
        if recognized
        else CustomerMaster.TinVerificationState.FAILED
    )
    prior_state = master.tin_verification_state

    with super_admin_context(reason="enrichment.tin_verify.persist"):
        # Re-fetch under the super-admin context so the save passes
        # the RLS WITH CHECK clause without relying on call-site
        # tenancy state.
        master = CustomerMaster.objects.filter(id=master_id).first()
        if master is None:
            return {"state": "skipped", "reason": "missing_after_lookup"}
        master.tin_verification_state = new_state
        master.tin_last_verified_at = timezone.now()
        master.save(
            update_fields=[
                "tin_verification_state",
                "tin_last_verified_at",
                "updated_at",
            ]
        )

    record_event(
        action_type="enrichment.tin_verified",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="enrichment.tin_verify",
        organization_id=str(master.organization_id),
        affected_entity_type="CustomerMaster",
        affected_entity_id=str(master.id),
        payload={
            "from_state": prior_state,
            "to_state": new_state,
            "environment": creds.environment,
            # NOTE: TIN itself is excluded from the audit payload —
            # it's PII-adjacent (taxpayer identifier). The state
            # transition + master id is enough to reconstruct.
        },
    )

    return {"state": new_state, "reason": "lhdn"}
