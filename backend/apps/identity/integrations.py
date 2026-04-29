"""Per-tenant integration credentials service (Slice 57).

Customer-side surface so the org's owner / admin configures
integration credentials for their own tenant. Two slots per
integration (sandbox + production) with an active-environment
toggle so going live is a one-click gesture.

Schema registry
---------------
``INTEGRATION_SCHEMAS`` declares the fields per integration. Each
field has:
  - ``key``: dict key in the credentials blob.
  - ``label``: UI label.
  - ``kind``: ``"credential"`` (write-only, returned as presence
    boolean) or ``"config"`` (plaintext config like base URLs,
    organization TIN that the integration needs).
  - ``placeholder``: shown in the input, optional.
  - ``required``: whether the integration's "test" can run without it.

Adding a new integration is a one-entry change here. Today: only
``lhdn_myinvois`` is wired; Slice 58 builds the LHDN client that
consumes these creds, and Slice 59 may register Stripe similarly
if we want per-tenant Stripe keys (likely platform-level instead).

Encryption
----------
Credential values are encrypted at rest via the Slice 55 helpers
in ``apps.administration.crypto``. The schema registry decides
which fields are credentials so the read surface returns
presence-only booleans for those.

Test-connection
---------------
Each integration has a ``test_connection`` callable in
``_INTEGRATION_TESTERS`` that exercises the credentials. Today
the LHDN tester does a connectivity probe (DNS + HEAD on
``base_url``). Slice 58 swaps it for a real OAuth2 token request
so the operator gets a true "creds are working" verdict.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from django.db import transaction
from django.utils import timezone

from apps.administration.crypto import (
    decrypt_dict_values,
    encrypt_dict_values,
)
from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import OrganizationIntegration


# --- Schema registry ---------------------------------------------------------

INTEGRATION_SCHEMAS: list[dict[str, Any]] = [
    {
        "key": "lhdn_myinvois",
        "label": "LHDN MyInvois",
        "description": (
            "Malaysia's e-invoice clearance API. Sandbox is the "
            "pre-production environment for integration testing; "
            "Production is the live LHDN endpoint that issues real "
            "Invoice UUIDs + QR codes."
        ),
        "fields": [
            {
                "key": "client_id",
                "label": "Client ID",
                "kind": "credential",
                "placeholder": "Issued by LHDN",
                "required": True,
            },
            {
                "key": "client_secret",
                "label": "Client Secret",
                "kind": "credential",
                "placeholder": "Issued by LHDN",
                "required": True,
            },
            {
                "key": "base_url",
                "label": "Base URL",
                "kind": "config",
                "placeholder": "https://preprod-api.myinvois.hasil.gov.my",
                "required": True,
            },
            {
                "key": "tin",
                "label": "Your TIN",
                "kind": "config",
                "placeholder": "C1234567890",
                "required": True,
            },
        ],
        "default_sandbox": {
            "base_url": "https://preprod-api.myinvois.hasil.gov.my",
        },
        "default_production": {
            "base_url": "https://api.myinvois.hasil.gov.my",
        },
    },
]


def _schema_for(integration_key: str) -> dict[str, Any] | None:
    return next(
        (s for s in INTEGRATION_SCHEMAS if s["key"] == integration_key),
        None,
    )


class IntegrationConfigError(Exception):
    """Raised when a credential update or test-call request is invalid."""


# --- Service functions -------------------------------------------------------


def list_integrations_for_org(
    *, organization_id: uuid.UUID | str
) -> list[dict[str, Any]]:
    """Settings → Integrations readout.

    Returns one card per registered integration. Existing rows are
    surfaced; integrations the org hasn't configured yet appear with
    empty credential dicts so the form renders at the correct shape.
    """
    rows = {
        r.integration_key: r
        for r in OrganizationIntegration.objects.filter(
            organization_id=organization_id
        )
    }
    out: list[dict[str, Any]] = []
    for schema in INTEGRATION_SCHEMAS:
        row = rows.get(schema["key"])
        out.append(_integration_dict(schema=schema, row=row))
    return out


def upsert_credentials(
    *,
    organization_id: uuid.UUID | str,
    integration_key: str,
    environment: str,
    field_updates: dict[str, str],
    actor_user_id: uuid.UUID | str,
) -> dict[str, Any]:
    """Patch one environment's credential set.

    Empty-string values delete the key (matching the SystemSetting
    semantics). Audit chain records WHICH fields changed by name;
    values never enter the chain.
    """
    schema = _schema_for(integration_key)
    if schema is None:
        raise IntegrationConfigError(
            f"Unknown integration {integration_key!r}."
        )
    if environment not in {"sandbox", "production"}:
        raise IntegrationConfigError(
            "environment must be 'sandbox' or 'production'."
        )

    allowed_keys = {f["key"] for f in schema["fields"]}
    invalid = set(field_updates) - allowed_keys
    if invalid:
        raise IntegrationConfigError(
            f"Unknown fields for {integration_key}: {sorted(invalid)}. "
            f"Allowed: {sorted(allowed_keys)}"
        )

    with transaction.atomic():
        row, _ = OrganizationIntegration.objects.select_for_update().get_or_create(
            organization_id=organization_id,
            integration_key=integration_key,
            defaults={
                "active_environment": "sandbox",
                "created_by_user_id": actor_user_id,
                # Seed defaults (e.g. preset base_url for sandbox)
                # so first-time configurators don't have to copy
                # the URL out of LHDN docs.
                "sandbox_credentials": encrypt_dict_values(
                    schema.get("default_sandbox", {})
                ),
                "production_credentials": encrypt_dict_values(
                    schema.get("default_production", {})
                ),
            },
        )

        column_attr = f"{environment}_credentials"
        current_plain = decrypt_dict_values(getattr(row, column_attr) or {})
        changed: list[str] = []
        for key, value in field_updates.items():
            value_str = "" if value is None else str(value)
            if value_str == "":
                if key in current_plain:
                    del current_plain[key]
                    changed.append(key)
            else:
                if current_plain.get(key) != value_str:
                    current_plain[key] = value_str
                    changed.append(key)

        if changed:
            setattr(row, column_attr, encrypt_dict_values(current_plain))
            row.updated_by_user_id = actor_user_id
            row.save(
                update_fields=[
                    column_attr,
                    "updated_by_user_id",
                    "updated_at",
                ]
            )

            record_event(
                action_type="identity.integration.credentials_updated",
                actor_type=AuditEvent.ActorType.USER,
                actor_id=str(actor_user_id),
                organization_id=str(organization_id),
                affected_entity_type="OrganizationIntegration",
                affected_entity_id=str(row.id),
                payload={
                    "integration_key": integration_key,
                    "environment": environment,
                    "fields_changed": sorted(changed),
                    # No values. Credentials never enter the audit log.
                },
            )

    return _integration_dict(schema=schema, row=row)


def set_active_environment(
    *,
    organization_id: uuid.UUID | str,
    integration_key: str,
    environment: str,
    actor_user_id: uuid.UUID | str,
    reason: str = "",
) -> dict[str, Any]:
    """Flip the active environment (the go-live gesture).

    Audit-loud — going from sandbox to production is the moment
    where an operator's intent matters most. Reason is captured but
    not required (we may want to require it via UI later; today the
    audit trail is enough).
    """
    schema = _schema_for(integration_key)
    if schema is None:
        raise IntegrationConfigError(
            f"Unknown integration {integration_key!r}."
        )
    if environment not in {"sandbox", "production"}:
        raise IntegrationConfigError(
            "environment must be 'sandbox' or 'production'."
        )

    with transaction.atomic():
        row, _ = OrganizationIntegration.objects.select_for_update().get_or_create(
            organization_id=organization_id,
            integration_key=integration_key,
            defaults={
                "active_environment": environment,
                "created_by_user_id": actor_user_id,
            },
        )
        if row.active_environment == environment:
            return _integration_dict(schema=schema, row=row)

        previous = row.active_environment
        row.active_environment = environment
        row.updated_by_user_id = actor_user_id
        row.save(
            update_fields=["active_environment", "updated_by_user_id", "updated_at"]
        )

        record_event(
            action_type="identity.integration.environment_switched",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(actor_user_id),
            organization_id=str(organization_id),
            affected_entity_type="OrganizationIntegration",
            affected_entity_id=str(row.id),
            payload={
                "integration_key": integration_key,
                "from_environment": previous,
                "to_environment": environment,
                "reason": reason[:255],
            },
        )

    return _integration_dict(schema=schema, row=row)


@dataclass(frozen=True)
class TestOutcome:
    ok: bool
    detail: str
    duration_ms: int


def test_connection(
    *,
    organization_id: uuid.UUID | str,
    integration_key: str,
    environment: str,
    actor_user_id: uuid.UUID | str,
) -> TestOutcome:
    """Run the integration's test-connection probe + record outcome.

    Today's LHDN tester is a connectivity probe (DNS + HEAD on the
    base URL). Slice 58 swaps in a real OAuth2 token request once
    the LHDN client lands. Either way this function persists the
    outcome on the row so the UI shows "last tested 5 min ago"
    without polling.
    """
    schema = _schema_for(integration_key)
    if schema is None:
        raise IntegrationConfigError(
            f"Unknown integration {integration_key!r}."
        )
    if environment not in {"sandbox", "production"}:
        raise IntegrationConfigError(
            "environment must be 'sandbox' or 'production'."
        )

    row = OrganizationIntegration.objects.filter(
        organization_id=organization_id, integration_key=integration_key
    ).first()
    if row is None:
        raise IntegrationConfigError(
            "No credentials configured yet. Save credentials first."
        )

    plain = decrypt_dict_values(
        getattr(row, f"{environment}_credentials") or {}
    )

    tester = _INTEGRATION_TESTERS.get(integration_key)
    if tester is None:
        raise IntegrationConfigError(
            f"No test-connection wired for {integration_key}."
        )

    outcome = tester(plain)

    # Persist the outcome on the row (per environment).
    setattr(row, f"last_test_{environment}_at", timezone.now())
    setattr(row, f"last_test_{environment}_ok", outcome.ok)
    setattr(
        row,
        f"last_test_{environment}_detail",
        outcome.detail[:512],
    )
    row.save(
        update_fields=[
            f"last_test_{environment}_at",
            f"last_test_{environment}_ok",
            f"last_test_{environment}_detail",
            "updated_at",
        ]
    )

    record_event(
        action_type="identity.integration.test_connection",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="OrganizationIntegration",
        affected_entity_id=str(row.id),
        payload={
            "integration_key": integration_key,
            "environment": environment,
            "ok": outcome.ok,
            "duration_ms": outcome.duration_ms,
        },
    )
    return outcome


# --- Per-integration tester registry ----------------------------------------


def _test_lhdn_myinvois(plain: dict[str, Any]) -> TestOutcome:
    """LHDN MyInvois test (Slice 58 — real OAuth2 probe).

    Performs a real OAuth2 client_credentials token request against
    the configured LHDN base URL. Catches:

      - Typos in base_url (DNS / connect errors).
      - Wrong scheme on the URL (still validated up front).
      - Invalid client_id / client_secret (LHDN returns 401 with
        an OAuth2-style error_code).
      - Missing required fields (client_id / secret / tin).

    Slice 57 shipped a connectivity-only probe; that path is gone.
    The new tester is the one Slice 58 uses for real submissions
    too — same code path means "Test connection passes" actually
    means "real submissions will auth".
    """
    started = time.perf_counter()
    base_url = (plain.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        return TestOutcome(
            ok=False,
            detail="base_url not configured",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return TestOutcome(
            ok=False,
            detail=f"invalid base_url: {base_url!r}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    missing = [
        k for k in ("client_id", "client_secret", "tin") if not plain.get(k)
    ]
    if missing:
        return TestOutcome(
            ok=False,
            detail=f"credentials missing: {missing}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    # Real OAuth2 token request.
    token_url = base_url + "/connect/token"
    try:
        response = httpx.post(
            token_url,
            data={
                "client_id": plain["client_id"],
                "client_secret": plain["client_secret"],
                "grant_type": "client_credentials",
                "scope": "InvoicingAPI",
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        return TestOutcome(
            ok=False,
            detail=f"connection failed: {type(exc).__name__}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    if response.status_code == 200:
        try:
            access_token = response.json().get("access_token")
        except (json.JSONDecodeError, ValueError):
            access_token = None
        if access_token:
            return TestOutcome(
                ok=True,
                detail="OAuth2 token issued — credentials valid",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        return TestOutcome(
            ok=False,
            detail="200 response but no access_token in body",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    # Failure path. LHDN returns OAuth2-style {error, error_description}.
    # Surface error code only — descriptions occasionally echo the
    # client_id which is fine, but never the secret.
    try:
        body = response.json()
        error_code = body.get("error", f"HTTP {response.status_code}")
    except (json.JSONDecodeError, ValueError):
        error_code = f"HTTP {response.status_code}"
    return TestOutcome(
        ok=False,
        detail=f"LHDN rejected: {error_code}",
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


_INTEGRATION_TESTERS: dict[str, Callable[[dict[str, Any]], TestOutcome]] = {
    "lhdn_myinvois": _test_lhdn_myinvois,
}


# --- Read-shape helpers -----------------------------------------------------


def _integration_dict(
    *, schema: dict[str, Any], row: OrganizationIntegration | None
) -> dict[str, Any]:
    """Settings card payload.

    For credentials: presence-only booleans (write-only contract).
    For config (URLs / TIN / etc.): plaintext values round-trip so
    the form can show what's currently saved.
    """
    cred_keys = {f["key"] for f in schema["fields"] if f["kind"] == "credential"}

    def _summarise(stored: dict[str, Any]) -> dict[str, Any]:
        plain = decrypt_dict_values(stored or {})
        values: dict[str, Any] = {}
        present: dict[str, bool] = {}
        for f in schema["fields"]:
            key = f["key"]
            if f["kind"] == "credential":
                present[key] = bool(plain.get(key))
            else:
                values[key] = str(plain.get(key, ""))
        return {"values": values, "credential_present": present}

    if row is None:
        empty: dict[str, Any] = {}
        return {
            "integration_key": schema["key"],
            "label": schema["label"],
            "description": schema["description"],
            "fields": schema["fields"],
            "active_environment": "sandbox",
            "sandbox": {"values": {}, "credential_present": {}},
            "production": {"values": {}, "credential_present": {}},
            "last_test_sandbox": None,
            "last_test_production": None,
            "configured": False,
        }

    return {
        "integration_key": schema["key"],
        "label": schema["label"],
        "description": schema["description"],
        "fields": schema["fields"],
        "active_environment": row.active_environment,
        "sandbox": _summarise(row.sandbox_credentials),
        "production": _summarise(row.production_credentials),
        "last_test_sandbox": _last_test_dict(
            row.last_test_sandbox_at,
            row.last_test_sandbox_ok,
            row.last_test_sandbox_detail,
        ),
        "last_test_production": _last_test_dict(
            row.last_test_production_at,
            row.last_test_production_ok,
            row.last_test_production_detail,
        ),
        "configured": True,
    }


def _last_test_dict(at, ok, detail) -> dict[str, Any] | None:
    if at is None:
        return None
    return {
        "at": at.isoformat(),
        "ok": bool(ok),
        "detail": detail or "",
    }
