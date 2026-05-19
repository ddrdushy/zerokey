"""DRF authentication for the desktop sidecar.

The sidecar's clients are the Electron renderer and the Electron main
process — both on the same machine, both holding the cached
entitlement that activate / heartbeat returned. They authenticate by
including the entitlement in the ``X-ZK-Entitlement`` request header.

A successful auth:
  1. Verifies the entitlement's Ed25519 signature.
  2. Resolves (or creates) the local Organization that the entitlement
     describes.
  3. Resolves (or creates) the local synthetic User used as the audit
     actor.
  4. Pins the org id on the tenancy shim's thread-local for the
     duration of the request.

DRF's request.user becomes the synthetic User; request.auth becomes
the VerifiedEntitlement. The single user is intentional — the desktop
is single-tenant, and the audit log records every action against the
license's owner email (or "desktop-user" if no email is on file).

Phase 4 will harden this:
  - Reject if entitlement.status != "active" for mutating methods.
  - Reject if entitlement.expires_at < now for mutating methods.
  - Allow read methods even when expired (read-only mode).
  - Reject if entitlement.machine_fingerprint_hash != current machine.
"""

from __future__ import annotations

import logging
import uuid

from rest_framework import authentication, exceptions

from zk_desktop import entitlement_verify, remote_signer, tenancy

LOG = logging.getLogger("zerokey.sidecar.auth")


class EntitlementAuthentication(authentication.BaseAuthentication):
    """Bind a verified entitlement to every authenticated request."""

    header = "HTTP_X_ZK_ENTITLEMENT"

    def authenticate(self, request):
        raw = request.META.get(self.header, "").strip()
        if not raw:
            # Returning None tells DRF "I don't apply" — falls through
            # to the next authenticator (we have none) and the
            # endpoint's permission_classes (AllowAny by default on
            # the sidecar) decide what to do.
            return None
        try:
            ent = entitlement_verify.verify(raw)
        except entitlement_verify.EntitlementVerifyError as exc:
            LOG.warning("zerokey.sidecar.auth.entitlement_invalid: %s", exc)
            raise exceptions.AuthenticationFailed(str(exc)) from exc

        user = self._ensure_local_user_and_org(ent)
        # Pin the org for any code that calls current_tenant_id().
        # The TenantContextMiddleware also sets this on each request;
        # we set it here so authentication happens before the middleware
        # has finished resolving the user.
        tenancy.set_tenant(self._org_id_from_user(user))
        # Pin the raw entitlement so the remote signer (intermediary
        # mode) can pick it up without threading it through every call
        # site. ContextVar is request-scoped under DRF's sync stack.
        remote_signer.set_active_entitlement(raw)
        return (user, ent)

    @staticmethod
    def authenticate_header(request) -> str:
        # Lets DRF return WWW-Authenticate on a 401.
        return "ZK-Entitlement"

    # --- bootstrap helpers ---

    def _ensure_local_user_and_org(self, ent: entitlement_verify.VerifiedEntitlement):
        """Create-on-first-sight Organization + synthetic User."""
        # Lazy imports — these modules go through the cloud's app
        # registry which boot.py wires up.
        from apps.identity.models import Organization, OrganizationMembership, Role, User

        org = Organization.objects.filter(tin=ent.organization_tin).first()
        if org is None:
            org = Organization.objects.create(
                legal_name=ent.organization_legal_name,
                tin=ent.organization_tin,
                contact_email="",
                # Apps that scope by signing_mode honour 'self_signed'
                # by default; the desktop reads the active mode from
                # the entitlement.signing_modes_allowed list and picks
                # the right branch at signing time.
            )
            LOG.info(
                "zerokey.sidecar.auth.bootstrapped_org tin=%s name=%s",
                ent.organization_tin,
                ent.organization_legal_name,
            )

        # Synthetic desktop user. The email is derived from the license_id
        # so it's stable across heartbeats. One real human owns the
        # license; their actions all land under this one User row, which
        # is good enough for the local audit trail.
        synth_email = f"desktop-{ent.license_id}@local.zerokey"
        user = User.objects.filter(email=synth_email).first()
        if user is None:
            user = User.objects.create_user(
                email=synth_email,
                # Long random password — the user never enters this; the
                # OS user IS the desktop user. We just need a value
                # AbstractBaseUser can store.
                password=str(uuid.uuid4()),
            )
            # Make sure they have an Owner membership in the org so
            # cloud code that checks roles finds the right one.
            owner_role, _ = Role.objects.get_or_create(name="owner")
            OrganizationMembership.objects.get_or_create(
                user=user,
                organization=org,
                defaults={"role": owner_role},
            )
            LOG.info("zerokey.sidecar.auth.bootstrapped_user email=%s", synth_email)
        # Stash the org id on the user so views that read it from
        # request.user can find it without a DB hit.
        user._desktop_org_id = str(org.id)
        return user

    @staticmethod
    def _org_id_from_user(user) -> str | None:
        return getattr(user, "_desktop_org_id", None)
