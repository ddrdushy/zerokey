"""Customer signing-certificate management (Slice 58).

Two paths today:

  - **Self-signed dev cert**: when an org has no certificate uploaded
    yet, the first signing attempt auto-generates an RSA-2048
    self-signed cert (1-year validity). Stored inline on the
    Organization row, private key encrypted via Slice 55. This is
    sufficient for LHDN sandbox testing + the entire end-to-end
    signing pipeline — but NOT acceptable for LHDN production
    submissions, where LHDN requires a cert chained to a recognized
    Malaysian CA (MSC Trustgate, Pos Digicert, Telekom Applied
    Business).

  - **Customer-uploaded cert**: when the customer obtains a real
    cert from a recognized CA, they upload it (UI lands in Slice
    59). The same encrypted-private-key field stores the upload;
    ``certificate_kind="uploaded"`` distinguishes it from the dev
    cert.

Production swap point: when ZeroKey deploys to AWS, the
inline-encrypted private key field gets replaced by a KMS-encrypted
S3 blob URL. Call sites in this module are stable across that swap.

Why store the private key in the database at all (vs HSM): for
the SME-tier product, an HSM is overkill — customers have
LHDN-issued certificates that get rotated annually, used for
~hundreds of signatures per day. Database storage with KMS
envelope encryption matches the threat model + ops cost. The
signing service decrypts in-memory only for the duration of one
signing operation.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.utils import timezone

from apps.administration.crypto import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)


# Self-signed dev-cert validity. 1 year is long enough that ops
# doesn't constantly re-mint, short enough that a misuse window is
# bounded. Customers should upload a real LHDN-issued cert before
# this expires.
DEV_CERT_VALIDITY_DAYS = 365

# RSA key size. 2048 is the LHDN-required minimum + universal default.
RSA_KEY_SIZE_BITS = 2048


class CertificateError(Exception):
    """Raised when certificate load / generation fails."""


@dataclass(frozen=True)
class LoadedCertificate:
    """Decrypted cert + private key in-memory.

    Used only inside one signing call; never persisted. The caller
    is responsible for not logging this struct (the redaction
    filter doesn't know about ad-hoc dataclasses).
    """

    cert: x509.Certificate
    private_key: rsa.RSAPrivateKey
    cert_pem: bytes
    kind: str  # "self_signed_dev" | "uploaded"


def ensure_certificate(*, organization_id) -> LoadedCertificate:
    """Load the org's signing cert; generate a self-signed dev one if missing.

    Idempotent — calling repeatedly for the same org returns the
    same cert (no churn). The first call when no cert exists takes
    a couple of seconds (RSA key gen); subsequent calls are
    sub-millisecond.
    """
    from apps.identity.models import Organization
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason="submission.cert.load"):
        org = Organization.objects.filter(id=organization_id).first()
        if org is None:
            raise CertificateError(
                f"Organization {organization_id} not found."
            )

        if not org.certificate_uploaded or not org.certificate_pem:
            _generate_and_store_self_signed(org)
            org.refresh_from_db()

        return _load(org)


def _generate_and_store_self_signed(org) -> None:
    """Mint an RSA-2048 self-signed cert for the org + persist it."""
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=RSA_KEY_SIZE_BITS
    )

    common_name = (
        org.legal_name[:60] + " (ZeroKey dev cert)"
        if len(org.legal_name) <= 60
        else org.legal_name[:60] + "… (ZeroKey dev cert)"
    )
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "MY"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, org.legal_name[:60]),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            # The TIN goes into the OU so signing-time inspection can
            # tie a cert to a tenant without an external lookup.
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, f"TIN={org.tin}"),
        ]
    )

    serial = x509.random_serial_number()
    now = timezone.now()
    not_after = now + datetime.timedelta(days=DEV_CERT_VALIDITY_DAYS)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(serial)
        .not_valid_before(now)
        .not_valid_after(not_after)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")

    org.certificate_pem = cert_pem
    org.certificate_private_key_pem_encrypted = encrypt_value(key_pem)
    org.certificate_kind = "self_signed_dev"
    org.certificate_uploaded = True  # "We have one to use" — see the
    # docstring caveat about LHDN production acceptance.
    org.certificate_expiry_date = not_after.date()
    org.certificate_subject_common_name = common_name
    org.certificate_serial_hex = format(serial, "x")
    org.save(
        update_fields=[
            "certificate_pem",
            "certificate_private_key_pem_encrypted",
            "certificate_kind",
            "certificate_uploaded",
            "certificate_expiry_date",
            "certificate_subject_common_name",
            "certificate_serial_hex",
            "updated_at",
        ]
    )

    # Audit the auto-mint as a system event so operators see when
    # self-signed certs were generated. The PEM itself never
    # enters the audit log.
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    record_event(
        action_type="submission.cert.self_signed_minted",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="submission.cert",
        organization_id=str(org.id),
        affected_entity_type="Organization",
        affected_entity_id=str(org.id),
        payload={
            "subject_common_name": common_name,
            "serial_hex": format(serial, "x"),
            "expires_at": not_after.date().isoformat(),
            "kind": "self_signed_dev",
        },
    )

    logger.info(
        "submission.cert.self_signed_minted",
        extra={
            "organization_id": str(org.id),
            "serial_hex": format(serial, "x"),
        },
    )


def _load(org) -> LoadedCertificate:
    """Decrypt + parse an org's stored cert."""
    if not org.certificate_pem:
        raise CertificateError("Organization has no certificate stored.")

    key_pem_plain = decrypt_value(
        org.certificate_private_key_pem_encrypted or ""
    )
    if not key_pem_plain:
        raise CertificateError(
            "Certificate private key is empty or could not be decrypted."
        )

    try:
        cert = x509.load_pem_x509_certificate(
            org.certificate_pem.encode("ascii")
        )
        private_key = serialization.load_pem_private_key(
            key_pem_plain.encode("ascii"), password=None
        )
    except (ValueError, TypeError) as exc:
        raise CertificateError(
            f"Failed to parse stored certificate: {type(exc).__name__}"
        ) from exc

    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise CertificateError(
            "Stored private key is not an RSA key. "
            "LHDN signing requires RSA-2048 or larger."
        )

    return LoadedCertificate(
        cert=cert,
        private_key=private_key,
        cert_pem=org.certificate_pem.encode("ascii"),
        kind=org.certificate_kind or "",
    )


def upload_certificate(
    *,
    organization_id: uuid.UUID | str,
    cert_pem: str,
    private_key_pem: str,
    actor_user_id: uuid.UUID | str,
) -> dict:
    """Replace the org's signing certificate with an uploaded one.

    Used by the customer-facing "Upload my LHDN cert" flow (UI
    lands in Slice 59). Validates the cert + key are a matched
    pair before persisting + audits the swap.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.identity.models import Organization
    from apps.identity.tenancy import super_admin_context

    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode("ascii"))
        key = serialization.load_pem_private_key(
            private_key_pem.encode("ascii"), password=None
        )
    except (ValueError, TypeError) as exc:
        raise CertificateError(
            f"Could not parse certificate or private key: {type(exc).__name__}"
        ) from exc

    if not isinstance(key, rsa.RSAPrivateKey):
        raise CertificateError("Only RSA private keys are supported.")

    # Matched-pair check: the cert's public key must come from the
    # same RSA key as the private key. Otherwise we'd happily save
    # mismatched material that fails at signing time with a
    # confusing error.
    cert_pubkey_numbers = cert.public_key().public_numbers()
    key_pubkey_numbers = key.public_key().public_numbers()
    if cert_pubkey_numbers != key_pubkey_numbers:
        raise CertificateError(
            "Certificate and private key are not a matched pair."
        )

    common_name = ""
    for attr in cert.subject:
        if attr.oid == NameOID.COMMON_NAME:
            common_name = attr.value
            break
    serial_hex = format(cert.serial_number, "x")

    with super_admin_context(reason="submission.cert.upload"):
        org = Organization.objects.filter(id=organization_id).first()
        if org is None:
            raise CertificateError(
                f"Organization {organization_id} not found."
            )
        org.certificate_pem = cert_pem
        org.certificate_private_key_pem_encrypted = encrypt_value(
            private_key_pem
        )
        org.certificate_kind = "uploaded"
        org.certificate_uploaded = True
        org.certificate_expiry_date = cert.not_valid_after_utc.date()
        org.certificate_subject_common_name = common_name[:255]
        org.certificate_serial_hex = serial_hex[:64]
        org.save()

    record_event(
        action_type="submission.cert.uploaded",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="Organization",
        affected_entity_id=str(organization_id),
        payload={
            "subject_common_name": common_name,
            "serial_hex": serial_hex,
            "expires_at": cert.not_valid_after_utc.date().isoformat(),
            "kind": "uploaded",
        },
    )

    return {
        "kind": "uploaded",
        "subject_common_name": common_name,
        "serial_hex": serial_hex,
        "expires_at": cert.not_valid_after_utc.date().isoformat(),
    }


def pfx_to_pem(*, pfx_bytes: bytes, password: str) -> tuple[str, str]:
    """Convert a PFX/P12 bundle to (cert_pem, private_key_pem).

    Some Malaysian CAs (notably Pos Digicert) deliver the
    issued certificate as a single ``.pfx`` / ``.p12`` file —
    a PKCS#12 bundle that wraps the cert + private key behind
    a passphrase. Customers shouldn't have to learn the
    ``openssl pkcs12 -in cert.pfx -nodes ...`` incantation
    just to onboard.

    The bundle's password is used only to unlock the bundle —
    we don't persist it. The unwrapped private key is then
    stored encrypted via Slice 55's at-rest encryption,
    matched-pair-checked + persisted via the standard
    ``upload_certificate`` path (caller composes).

    Raises ``CertificateError`` on any parse / wrong-password /
    missing-cert / missing-key failure with a message that
    points at the most likely cause (so the customer doesn't
    keep trying the same wrong password against a corrupt file).
    """
    from cryptography.hazmat.primitives.serialization import pkcs12

    try:
        key, cert, _additional = pkcs12.load_key_and_certificates(
            pfx_bytes, password.encode("utf-8") if password else None
        )
    except ValueError as exc:
        # cryptography raises ValueError for both wrong-password
        # and corrupt-file. We can't reliably distinguish from
        # the message, so we surface a helpful both-cases hint.
        raise CertificateError(
            "Couldn't open the PFX/P12 file — the password may be "
            "wrong or the file may be corrupted. "
            f"({type(exc).__name__})"
        ) from exc

    if cert is None:
        raise CertificateError(
            "PFX/P12 bundle did not contain a certificate."
        )
    if key is None:
        raise CertificateError(
            "PFX/P12 bundle did not contain a private key."
        )
    if not isinstance(key, rsa.RSAPrivateKey):
        raise CertificateError(
            "Only RSA private keys are supported (LHDN requirement)."
        )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return cert_pem, key_pem
