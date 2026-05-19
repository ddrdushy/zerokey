"""Tests for the licensing service + HTTP surface.

Covers:
  - Issue → validate → heartbeat happy path.
  - Fingerprint binding + mismatch detection.
  - Status gates (revoked / expired / suspended).
  - Duplicate-TIN refusal.
  - Entitlement signature verification.
  - Super admin permission gate.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.licensing import services
from apps.licensing.entitlements import _b64url_decode, verify_entitlement
from apps.licensing.models import License, LicenseHeartbeat


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def customer(seeded) -> User:
    """A buyer — the user that owns one or more licenses."""
    org = Organization.objects.create(
        legal_name="Acme Sdn Bhd", tin="C10000000001", contact_email="ops@acme"
    )
    user = User.objects.create_user(
        email="buyer@acme.example", password="long-enough-password"
    )
    OrganizationMembership.objects.create(
        user=user,
        organization=org,
        role=Role.objects.get(name="owner"),
    )
    return user


@pytest.fixture
def staff(seeded) -> User:
    return User.objects.create_user(
        email="staff@symprio.com",
        password="long-enough-password",
        is_staff=True,
    )


# --- service layer -----------------------------------------------------------------


@pytest.mark.django_db
class TestIssueLicense:
    def test_issues_with_plaintext_key_only_once(self, customer) -> None:
        result = services.issue_license(
            owner_user_id=customer.id,
            organization_legal_name="Acme Sdn Bhd",
            organization_tin="C1234567890",
            plan=License.Plan.STARTER,
        )
        assert result.plaintext_key.startswith("ZK-")
        # The plaintext key is not stored; only the SHA-256 hash is.
        lic = License.objects.get(id=result.license_id)
        assert lic.key_hash != result.plaintext_key
        assert len(lic.key_hash) == 64  # SHA-256 hex
        assert lic.status == License.Status.ACTIVE

    def test_rejects_duplicate_tin(self, customer) -> None:
        services.issue_license(
            owner_user_id=customer.id,
            organization_legal_name="Acme",
            organization_tin="C9999999999",
            plan=License.Plan.STARTER,
        )
        with pytest.raises(services.DuplicateTinError):
            services.issue_license(
                owner_user_id=customer.id,
                organization_legal_name="Acme Round Two",
                organization_tin="C9999999999",
                plan=License.Plan.PROFESSIONAL,
            )

    def test_rejects_unknown_plan(self, customer) -> None:
        with pytest.raises(services.LicensingError):
            services.issue_license(
                owner_user_id=customer.id,
                organization_legal_name="Acme",
                organization_tin="C2222222222",
                plan="ultraplan",
            )


@pytest.mark.django_db
class TestValidateLicense:
    def _issue(self, customer):
        return services.issue_license(
            owner_user_id=customer.id,
            organization_legal_name="Acme",
            organization_tin="C3333333333",
            plan=License.Plan.PROFESSIONAL,
        )

    def test_first_validate_binds_fingerprint(self, customer) -> None:
        issued = self._issue(customer)
        activation = services.validate_license(
            key=issued.plaintext_key,
            machine_fingerprint="machine-A",
            desktop_version="0.1.0",
        )
        assert activation.license_id == issued.license_id
        # Entitlement is a valid signed wire-format blob.
        payload = verify_entitlement(activation.entitlement_wire)
        assert payload["license_id"] == str(issued.license_id)
        assert payload["organization_tin"] == "C3333333333"
        assert "submission.lhdn" in payload["features"]
        assert "self_signed" in payload["signing_modes_allowed"]
        # Binding persisted.
        lic = License.objects.get(id=issued.license_id)
        assert lic.bound_fingerprint_hash != ""
        assert lic.bound_at is not None

    def test_second_validate_from_other_machine_rejected(self, customer) -> None:
        issued = self._issue(customer)
        services.validate_license(
            key=issued.plaintext_key, machine_fingerprint="machine-A"
        )
        with pytest.raises(services.FingerprintMismatchError):
            services.validate_license(
                key=issued.plaintext_key, machine_fingerprint="machine-B"
            )

    def test_unknown_key_rejected(self, customer) -> None:
        with pytest.raises(services.UnknownLicenseKeyError):
            services.validate_license(
                key="ZK-NONE-NONE-NONE-NONE-NONE-NONE-NONE",
                machine_fingerprint="machine-A",
            )

    def test_revoked_license_rejected(self, customer) -> None:
        issued = self._issue(customer)
        services.revoke_license(
            license_id=issued.license_id, reason="test revoke"
        )
        with pytest.raises(services.LicenseNotActiveError) as exc:
            services.validate_license(
                key=issued.plaintext_key, machine_fingerprint="machine-A"
            )
        assert exc.value.status == License.Status.REVOKED

    def test_expired_license_auto_flips_and_rejected(self, customer) -> None:
        issued = self._issue(customer)
        License.objects.filter(id=issued.license_id).update(
            expires_at=timezone.now() - timedelta(days=1)
        )
        with pytest.raises(services.LicenseNotActiveError) as exc:
            services.validate_license(
                key=issued.plaintext_key, machine_fingerprint="machine-A"
            )
        assert exc.value.status == License.Status.EXPIRED
        # Auto-flip persisted.
        lic = License.objects.get(id=issued.license_id)
        assert lic.status == License.Status.EXPIRED


@pytest.mark.django_db
class TestHeartbeat:
    def test_heartbeat_refreshes_entitlement(self, customer) -> None:
        issued = services.issue_license(
            owner_user_id=customer.id,
            organization_legal_name="Acme",
            organization_tin="C4444444444",
            plan=License.Plan.STARTER,
        )
        services.validate_license(
            key=issued.plaintext_key, machine_fingerprint="machine-A"
        )
        result = services.heartbeat_license(
            license_id=issued.license_id, machine_fingerprint="machine-A"
        )
        payload = verify_entitlement(result.entitlement_wire)
        assert payload["status"] == License.Status.ACTIVE

    def test_heartbeat_from_other_machine_rejected(self, customer) -> None:
        issued = services.issue_license(
            owner_user_id=customer.id,
            organization_legal_name="Acme",
            organization_tin="C5555555555",
            plan=License.Plan.STARTER,
        )
        services.validate_license(
            key=issued.plaintext_key, machine_fingerprint="machine-A"
        )
        with pytest.raises(services.FingerprintMismatchError):
            services.heartbeat_license(
                license_id=issued.license_id, machine_fingerprint="machine-B"
            )


@pytest.mark.django_db
class TestRegenerateAndRenew:
    def test_regenerate_returns_new_key_and_clears_binding(self, customer) -> None:
        issued = services.issue_license(
            owner_user_id=customer.id,
            organization_legal_name="Acme",
            organization_tin="C6666666666",
            plan=License.Plan.STARTER,
        )
        services.validate_license(
            key=issued.plaintext_key, machine_fingerprint="machine-A"
        )
        regen = services.regenerate_license_key(license_id=issued.license_id)
        assert regen.plaintext_key != issued.plaintext_key
        # Old key dead.
        with pytest.raises(services.UnknownLicenseKeyError):
            services.validate_license(
                key=issued.plaintext_key, machine_fingerprint="machine-A"
            )
        # New key works.
        activation = services.validate_license(
            key=regen.plaintext_key, machine_fingerprint="machine-A"
        )
        assert activation.license_id == issued.license_id

    def test_renew_extends_expiry(self, customer) -> None:
        issued = services.issue_license(
            owner_user_id=customer.id,
            organization_legal_name="Acme",
            organization_tin="C7777777777",
            plan=License.Plan.STARTER,
            validity_days=30,
        )
        lic = License.objects.get(id=issued.license_id)
        original_expiry = lic.expires_at
        services.renew_license(license_id=issued.license_id, days=365)
        lic.refresh_from_db()
        assert lic.expires_at > original_expiry + timedelta(days=300)


# --- HTTP surface ------------------------------------------------------------------


@pytest.mark.django_db
class TestAdminEndpoints:
    def test_issue_endpoint_returns_key_once(self, customer, staff) -> None:
        client = Client()
        client.force_login(staff)
        response = client.post(
            "/api/v1/licenses/admin/issue/",
            data=json.dumps(
                {
                    "owner_user_id": str(customer.id),
                    "organization_legal_name": "Acme",
                    "organization_tin": "C8888888888",
                    "plan": "starter",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 201
        body = response.json()
        assert body["plaintext_key"].startswith("ZK-")
        assert "license" in body
        assert body["license"]["organization_tin"] == "C8888888888"

    def test_issue_requires_staff(self, customer) -> None:
        client = Client()
        client.force_login(customer)  # not staff
        response = client.post(
            "/api/v1/licenses/admin/issue/",
            data=json.dumps(
                {
                    "owner_user_id": str(customer.id),
                    "organization_legal_name": "Acme",
                    "organization_tin": "C8888888889",
                    "plan": "starter",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_list_endpoint(self, customer, staff) -> None:
        services.issue_license(
            owner_user_id=customer.id,
            organization_legal_name="Acme",
            organization_tin="C1111111110",
            plan=License.Plan.STARTER,
        )
        client = Client()
        client.force_login(staff)
        response = client.get("/api/v1/licenses/admin/")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] >= 1


@pytest.mark.django_db
class TestDesktopEndpoints:
    def test_validate_then_heartbeat(self, customer) -> None:
        issued = services.issue_license(
            owner_user_id=customer.id,
            organization_legal_name="Acme",
            organization_tin="C1111111111",
            plan=License.Plan.STARTER,
        )
        client = Client()
        v = client.post(
            "/api/v1/licenses/validate/",
            data=json.dumps(
                {
                    "key": issued.plaintext_key,
                    "machine_fingerprint": "machine-A",
                    "desktop_version": "0.1.0",
                }
            ),
            content_type="application/json",
        )
        assert v.status_code == 200
        ent = v.json()["entitlement"]
        # Wire format = <b64>.<b64>.
        assert "." in ent

        # Heartbeat returns fresh entitlement.
        h = client.post(
            "/api/v1/licenses/heartbeat/",
            data=json.dumps(
                {
                    "license_id": v.json()["license_id"],
                    "machine_fingerprint": "machine-A",
                }
            ),
            content_type="application/json",
        )
        assert h.status_code == 200

    def test_public_key_endpoint(self) -> None:
        response = Client().get("/api/v1/licenses/public-key/")
        assert response.status_code == 200
        body = response.json()
        assert "BEGIN PUBLIC KEY" in body["public_key_pem"]


@pytest.mark.django_db
def test_entitlement_payload_is_valid_canonical_json(customer) -> None:
    """The payload half of the wire format must round-trip JSON cleanly."""
    issued = services.issue_license(
        owner_user_id=customer.id,
        organization_legal_name="Acme",
        organization_tin="C9999999000",
        plan=License.Plan.STARTER,
    )
    activation = services.validate_license(
        key=issued.plaintext_key, machine_fingerprint="machine-A"
    )
    payload_b64, _ = activation.entitlement_wire.split(".")
    payload = json.loads(_b64url_decode(payload_b64))
    assert payload["organization_tin"] == "C9999999000"


@pytest.mark.django_db
def test_heartbeat_logs_recorded(customer) -> None:
    issued = services.issue_license(
        owner_user_id=customer.id,
        organization_legal_name="Acme",
        organization_tin="C9999999001",
        plan=License.Plan.STARTER,
    )
    services.validate_license(
        key=issued.plaintext_key, machine_fingerprint="machine-A"
    )
    services.heartbeat_license(
        license_id=issued.license_id, machine_fingerprint="machine-A"
    )
    rows = LicenseHeartbeat.objects.filter(license_id=issued.license_id).order_by("at")
    events = [(r.event_type, r.result) for r in rows]
    assert (LicenseHeartbeat.EventType.VALIDATE, LicenseHeartbeat.Result.OK) in events
    assert (LicenseHeartbeat.EventType.HEARTBEAT, LicenseHeartbeat.Result.OK) in events
