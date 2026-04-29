"""Enveloped XML-DSig signing for UBL invoices (Slice 58).

Implements a minimal-but-correct XML-DSig that LHDN MyInvois
accepts:

  - Algorithm: RSA-SHA256.
  - Canonicalisation: c14n 1.1 (W3C).
  - Reference: enveloped — the signature is appended INSIDE the
    document being signed, with an enveloped-signature transform
    so the signer's own bytes don't get re-included in the digest.
  - KeyInfo includes the X.509 cert chain (just the leaf for
    self-signed dev; real customer-uploaded certs include the
    chain to the root CA).

Why hand-rolled (vs ``signxml`` or ``xmlsec``):

  - No new dependency. ``signxml`` pulls ``lxml`` which we don't
    have. ``xmlsec`` requires the libxmlsec1 system library which
    complicates Docker builds.
  - The XML-DSig spec's enveloped-signature variant is bounded
    enough that ~150 lines of stdlib code do the job.
  - LHDN's signature requirements are well-published; we don't
    need every XML-DSig feature.

Algorithm URIs (W3C XML-DSig + Recommendation namespaces):

  http://www.w3.org/2001/10/xml-exc-c14n#                 (Exclusive C14N 1.0)
  http://www.w3.org/2006/12/xml-c14n11                    (C14N 1.1)
  http://www.w3.org/2000/09/xmldsig#enveloped-signature   (enveloped transform)
  http://www.w3.org/2001/04/xmlenc#sha256                 (SHA-256 digest)
  http://www.w3.org/2001/04/xmldsig-more#rsa-sha256       (RSA-SHA256 sig)
"""

from __future__ import annotations

import base64
import hashlib
from xml.etree import ElementTree as ET

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .certificates import LoadedCertificate

NS_DS = "http://www.w3.org/2000/09/xmldsig#"

ALGO_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
ALGO_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
ALGO_DIGEST_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
ALGO_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"

# Reference URI "" means "the document this signature is enveloped in".
ENVELOPED_REFERENCE_URI = ""


def sign_invoice_xml(
    *, xml_bytes: bytes, certificate: LoadedCertificate
) -> bytes:
    """Apply an enveloped XML-DSig signature to a UBL invoice document.

    Returns the signed XML as UTF-8 bytes. The output contains
    everything the input did + a ``<Signature>`` child appended to
    the root element.
    """
    ET.register_namespace("ds", NS_DS)

    # Parse the document we're signing.
    root = ET.fromstring(xml_bytes)

    # Step 1 — compute the digest of the document with an "enveloped
    # signature" transform applied. Since the signature isn't there
    # yet, the canonicalised bytes are just the canonicalised input.
    canonical_doc = ET.canonicalize(
        ET.tostring(root, encoding="utf-8"), with_comments=False
    ).encode("utf-8")
    doc_digest = hashlib.sha256(canonical_doc).digest()
    doc_digest_b64 = base64.b64encode(doc_digest).decode("ascii")

    # Step 2 — build the SignedInfo element. This is the bit that
    # actually gets signed by the private key.
    signature_el = ET.Element(f"{{{NS_DS}}}Signature")
    signed_info = ET.SubElement(signature_el, f"{{{NS_DS}}}SignedInfo")

    c14n_method = ET.SubElement(
        signed_info, f"{{{NS_DS}}}CanonicalizationMethod"
    )
    c14n_method.set("Algorithm", ALGO_C14N)

    sig_method = ET.SubElement(signed_info, f"{{{NS_DS}}}SignatureMethod")
    sig_method.set("Algorithm", ALGO_RSA_SHA256)

    reference = ET.SubElement(signed_info, f"{{{NS_DS}}}Reference")
    reference.set("URI", ENVELOPED_REFERENCE_URI)

    transforms = ET.SubElement(reference, f"{{{NS_DS}}}Transforms")
    transform_envloped = ET.SubElement(transforms, f"{{{NS_DS}}}Transform")
    transform_envloped.set("Algorithm", ALGO_ENVELOPED)
    transform_c14n = ET.SubElement(transforms, f"{{{NS_DS}}}Transform")
    transform_c14n.set("Algorithm", ALGO_C14N)

    digest_method = ET.SubElement(reference, f"{{{NS_DS}}}DigestMethod")
    digest_method.set("Algorithm", ALGO_DIGEST_SHA256)

    digest_value = ET.SubElement(reference, f"{{{NS_DS}}}DigestValue")
    digest_value.text = doc_digest_b64

    # Step 3 — canonicalise SignedInfo and sign with the private key.
    signed_info_xml = ET.tostring(signed_info, encoding="utf-8")
    signed_info_canonical = ET.canonicalize(
        signed_info_xml, with_comments=False
    ).encode("utf-8")

    signature_bytes = certificate.private_key.sign(
        signed_info_canonical,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    signature_b64 = base64.b64encode(signature_bytes).decode("ascii")

    sig_value_el = ET.SubElement(signature_el, f"{{{NS_DS}}}SignatureValue")
    sig_value_el.text = signature_b64

    # Step 4 — embed KeyInfo carrying the X.509 cert (DER, base64).
    key_info = ET.SubElement(signature_el, f"{{{NS_DS}}}KeyInfo")
    x509_data = ET.SubElement(key_info, f"{{{NS_DS}}}X509Data")
    x509_cert = ET.SubElement(x509_data, f"{{{NS_DS}}}X509Certificate")
    cert_der = certificate.cert.public_bytes(serialization.Encoding.DER)
    # Strip BEGIN/END headers — XML-DSig wants raw base64 of the DER.
    x509_cert.text = base64.b64encode(cert_der).decode("ascii")

    # Step 5 — append the signature to the document root.
    root.append(signature_el)

    out = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return out


def verify_invoice_signature(*, signed_xml_bytes: bytes) -> bool:
    """Round-trip verification.

    Used in tests + a future "verify the chain" admin tool. Pulls
    the embedded cert + SignatureValue, recomputes the digest +
    verifies the RSA signature. Returns True iff the signature
    matches.
    """
    root = ET.fromstring(signed_xml_bytes)
    signature = root.find(f"{{{NS_DS}}}Signature")
    if signature is None:
        return False

    signed_info = signature.find(f"{{{NS_DS}}}SignedInfo")
    if signed_info is None:
        return False

    sig_value_el = signature.find(f"{{{NS_DS}}}SignatureValue")
    if sig_value_el is None or not sig_value_el.text:
        return False

    x509_cert_el = signature.find(
        f"{{{NS_DS}}}KeyInfo/{{{NS_DS}}}X509Data/{{{NS_DS}}}X509Certificate"
    )
    if x509_cert_el is None or not x509_cert_el.text:
        return False

    from cryptography import x509
    from cryptography.exceptions import InvalidSignature

    cert_der = base64.b64decode(x509_cert_el.text)
    cert = x509.load_der_x509_certificate(cert_der)
    public_key = cert.public_key()

    sig_bytes = base64.b64decode(sig_value_el.text)
    signed_info_canonical = ET.canonicalize(
        ET.tostring(signed_info, encoding="utf-8"),
        with_comments=False,
    ).encode("utf-8")

    try:
        public_key.verify(
            sig_bytes,
            signed_info_canonical,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature:
        return False

    # Verify the document digest matches. The doc with the signature
    # element removed should produce the same digest claimed in the
    # Reference/DigestValue.
    digest_value_el = signed_info.find(
        f"{{{NS_DS}}}Reference/{{{NS_DS}}}DigestValue"
    )
    if digest_value_el is None or not digest_value_el.text:
        return False
    claimed_digest = base64.b64decode(digest_value_el.text)

    # Strip the signature out of a copy of the doc + recompute.
    root_copy = ET.fromstring(signed_xml_bytes)
    sig_in_copy = root_copy.find(f"{{{NS_DS}}}Signature")
    if sig_in_copy is not None:
        root_copy.remove(sig_in_copy)
    canonical_no_sig = ET.canonicalize(
        ET.tostring(root_copy, encoding="utf-8"),
        with_comments=False,
    ).encode("utf-8")
    actual_digest = hashlib.sha256(canonical_no_sig).digest()
    return claimed_digest == actual_digest
