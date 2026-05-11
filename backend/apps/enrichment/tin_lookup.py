"""Look up a missing TIN given the buyer's BRN + name (Slice 116).

LHDN exposes a "search taxpayer's TIN" endpoint that, given a
secondary identifier (BRN / NRIC / passport / army-id) plus an
optional name cross-check, returns the TIN — when LHDN actually has
a record. The endpoint complements the existing ``validate_tin``
(which asks "does this TIN exist?"); together they cover both
directions of the identity question:

  - validate_tin: TIN → exists/not  (caller has TIN, wants confirm)
  - search_tin:   BRN + name → TIN  (caller has BRN, wants the TIN)

Why this matters for ZeroKey: most LHDN-format invoices print the
buyer's BRN clearly under the "ID Type/Number" column but leave
the TIN to a smaller / less-obvious field. The structurer's
confidence on the TIN is therefore lower than on the BRN, and on
plenty of real invoices the TIN comes back empty. With BRN +
name in hand, we can ask LHDN directly and fill the TIN with
100% confidence — same as we'd do at submission time anyway.

The result is cached on the ``CustomerMaster`` row, so subsequent
invoices from the same buyer hit our cache rather than re-pinging
LHDN. The standard ``_autofill_buyer`` path already copies blank
fields from the master to the invoice, so once we fill
``master.tin`` here, future invoices auto-resolve without another
LHDN call.

State transitions on the master:

  unverified → verified  (search returned a TIN; we trust it)
  unverified → failed    (search returned 404 — LHDN has no record)
  unverified → unverified (transient: auth / rate-limit / 5xx / no creds)

LHDN's rate limit (~60/min in production) means we *must* cache.
``LOOKUP_REFRESH_DAYS`` mirrors ``VERIFY_REFRESH_DAYS`` so a "we
couldn't find it" verdict gets a chance to re-resolve after the
customer might have corrected their SSM registration.
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


# Re-try a "not found" lookup at most once every 90 days. The same
# rationale as VERIFY_REFRESH_DAYS in tin_verification: long enough
# that we're not hammering LHDN, short enough that a corrected SSM
# registration eventually resolves.
LOOKUP_REFRESH_DAYS = 90


class TinLookupError(Exception):
    """Raised for non-transient lookup failures (DB / config)."""


def needs_lookup(master: CustomerMaster) -> bool:
    """Should we ask LHDN for this master's TIN?

    Yes when:
      - The master has both a BRN (registration_number) and a name,
        AND
      - It does NOT already have a TIN, AND
      - Either we've never tried (last_verified_at is None) or the
        last attempt was more than LOOKUP_REFRESH_DAYS ago.

    No when there's no BRN (nothing to search by), or when we
    already have a TIN (use the existing ``verify_master_tin``
    flow to confirm it rather than re-derive).
    """
    if master.tin:
        return False
    if not master.registration_number or not master.legal_name:
        return False
    if master.tin_last_verified_at is None:
        return True
    age = timezone.now() - master.tin_last_verified_at
    return age > timedelta(days=LOOKUP_REFRESH_DAYS)


def lookup_tin_from_brn(master_id: uuid.UUID | str) -> dict[str, str]:
    """Ask LHDN for the TIN that matches this master's BRN + name.

    Returns a small dict ``{state, reason}`` for log enrichment.
    The persisted state on the row is the source of truth.

    Never raises on LHDN-side failures — those leave the row in
    its current state (transient outages mustn't flip a not-yet-
    looked-up master to "failed"). Only configuration + DB errors
    propagate.
    """
    from apps.identity.tenancy import super_admin_context
    from apps.submission import lhdn_client

    with super_admin_context(reason="enrichment.tin_lookup.fetch"):
        master = CustomerMaster.objects.filter(id=master_id).first()
    if master is None:
        raise TinLookupError(f"CustomerMaster {master_id} not found.")
    if master.tin:
        return {"state": "skipped", "reason": "already_has_tin"}
    if not master.registration_number:
        return {"state": "skipped", "reason": "no_brn"}

    try:
        creds = lhdn_client.credentials_for_org(organization_id=master.organization_id)
    except lhdn_client.LHDNError as exc:
        logger.info(
            "enrichment.tin_lookup.no_creds",
            extra={"master_id": str(master_id), "error": str(exc)},
        )
        return {"state": "skipped", "reason": "no_creds"}

    try:
        found_tin = lhdn_client.search_tin_by_other_id(
            creds=creds,
            id_type="BRN",
            id_value=master.registration_number,
            taxpayer_name=master.legal_name,
        )
    except lhdn_client.LHDNAuthError:
        return {"state": "skipped", "reason": "lhdn_auth"}
    except lhdn_client.LHDNRateLimitError:
        return {"state": "skipped", "reason": "lhdn_rate_limit"}
    except lhdn_client.LHDNError as exc:
        logger.info(
            "enrichment.tin_lookup.transient",
            extra={
                "master_id": str(master_id),
                "error_class": type(exc).__name__,
            },
        )
        return {"state": "skipped", "reason": "lhdn_transient"}

    with super_admin_context(reason="enrichment.tin_lookup.persist"):
        master = CustomerMaster.objects.filter(id=master_id).first()
        if master is None:
            return {"state": "skipped", "reason": "missing_after_lookup"}

        prior_state = master.tin_verification_state
        if found_tin:
            master.tin = found_tin
            master.tin_verification_state = (
                CustomerMaster.TinVerificationState.VERIFIED
            )
        else:
            # LHDN has no record matching this BRN+name. Stamp
            # ``failed`` so the review UI can show an honest
            # "we couldn't find this buyer in the LHDN registry"
            # signal instead of silently leaving the field empty.
            master.tin_verification_state = (
                CustomerMaster.TinVerificationState.FAILED
            )
        master.tin_last_verified_at = timezone.now()
        update_fields = [
            "tin",
            "tin_verification_state",
            "tin_last_verified_at",
            "updated_at",
        ]
        master.save(update_fields=update_fields)

    record_event(
        action_type="enrichment.tin_looked_up",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="enrichment.tin_lookup",
        organization_id=str(master.organization_id),
        affected_entity_type="CustomerMaster",
        affected_entity_id=str(master.id),
        payload={
            "from_state": prior_state,
            "to_state": master.tin_verification_state,
            "found": bool(found_tin),
            "environment": creds.environment,
            # Per the same convention as tin_verification: the TIN
            # itself is excluded from the audit payload (PII-adjacent).
        },
    )

    return {
        "state": master.tin_verification_state,
        "reason": "lhdn_hit" if found_tin else "lhdn_miss",
    }
