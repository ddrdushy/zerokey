"""Ingestion context views.

Phase 1/2 surface:
  POST /api/v1/ingestion/jobs/upload/    — multipart upload (web)
  GET  /api/v1/ingestion/jobs/           — list recent jobs for the active org
  GET  /api/v1/ingestion/jobs/<id>/      — detail with pre-signed download URL
  POST /api/v1/ingestion/jobs/api-upload/ — JSON+base64 upload (Slice 78, APIKey-only)
"""

from __future__ import annotations

import base64
import binascii
import io

from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    parser_classes,
    permission_classes,
)
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.identity.api_key_auth import APIKeyAuthentication
from apps.identity.models import APIKey

from . import services
from .serializers import IngestionJobSerializer


def _active_org(request: Request) -> str | None:
    session = getattr(request, "session", None)
    return session.get("organization_id") if session is not None else None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def upload(request: Request) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization. Switch organization first."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    upload_file = request.FILES.get("file")
    if upload_file is None:
        return Response(
            {"detail": "Field 'file' is required (multipart/form-data)."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = services.upload_web_file(
            organization_id=organization_id,
            actor_user_id=request.user.id,
            file_obj=upload_file,
            original_filename=upload_file.name,
            mime_type=upload_file.content_type or "application/octet-stream",
            size=upload_file.size,
        )
    except services.IngestionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        IngestionJobSerializer(result.job, context={"request": request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_jobs(request: Request) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"results": []})
    jobs = services.list_jobs_for_organization(organization_id=organization_id)
    return Response(
        {"results": IngestionJobSerializer(jobs, many=True, context={"request": request}).data}
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def throughput(request: Request) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization. Switch organization first."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        days = int(request.query_params.get("days", "7"))
    except ValueError:
        return Response({"detail": "days must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
    days = max(1, min(days, 90))
    return Response(
        services.throughput_for_organization(organization_id=organization_id, days=days)
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def job_detail(request: Request, job_id: str) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)
    job = services.get_job(organization_id=organization_id, job_id=job_id)
    if job is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(
        IngestionJobSerializer(job, context={"request": request, "include_download_url": True}).data
    )


# --- Slice 78: Public API ingestion --------------------------------------


# Bytes ceiling for the base64-decoded body — same 25 MB ceiling
# as the web upload path. The base64-encoded payload arriving on
# the wire is ~33% larger; we apply the limit to the decoded
# bytes so the customer-visible contract matches the web upload.
_API_MAX_DECODED_BYTES = services.MAX_UPLOAD_BYTES


@api_view(["POST"])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def api_upload(request: Request) -> Response:
    """Public API ingestion endpoint (Slice 78).

    Body shape (JSON):

        {
          "filename": "INV-2026-001.pdf",
          "mime_type": "application/pdf",
          "body_b64": "<base64-encoded file>",
          "source_identifier": "vendor-row-12345"   // optional
        }

    Auth: ``Authorization: Bearer <APIKey>`` only — no session
    auth allowed on this endpoint (the
    ``authentication_classes`` decorator pins it to APIKey-only).
    Returns the IngestionJob payload so the integrator can poll
    its status via the standard ``GET /jobs/<id>/`` route using
    the same key.

    Multipart isn't supported here intentionally: integrators
    overwhelmingly prefer one content-type to negotiate, and
    JSON+base64 is the cheapest path to ship in any HTTP
    client. The web upload path remains multipart (it's
    browser-driven).
    """
    # request.auth is the APIKey row (set by APIKeyAuthentication).
    api_key: APIKey = request.auth  # type: ignore[assignment]
    if api_key is None or not isinstance(api_key, APIKey):
        return Response(
            {"detail": "API key authentication required."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    body = request.data or {}
    filename = str(body.get("filename") or "").strip()
    mime_type = str(body.get("mime_type") or "").strip()
    body_b64 = body.get("body_b64") or ""
    source_identifier = str(body.get("source_identifier") or "").strip()

    if not filename or not mime_type or not body_b64:
        return Response(
            {"detail": ("filename, mime_type, and body_b64 are all required.")},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        decoded = base64.b64decode(body_b64, validate=True)
    except (binascii.Error, ValueError):
        return Response(
            {"detail": "body_b64 is not valid base64."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(decoded) == 0:
        return Response(
            {"detail": "body_b64 decoded to zero bytes."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(decoded) > _API_MAX_DECODED_BYTES:
        return Response(
            {
                "detail": (
                    f"File exceeds the "
                    f"{_API_MAX_DECODED_BYTES // (1024 * 1024)} MB upload "
                    f"limit (decoded size {len(decoded)} bytes)."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = services.upload_api_file(
            organization_id=api_key.organization_id,
            actor_api_key_id=api_key.id,
            file_obj=io.BytesIO(decoded),
            original_filename=filename,
            mime_type=mime_type,
            size=len(decoded),
            source_identifier=source_identifier,
        )
    except services.IngestionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        IngestionJobSerializer(result.job, context={"request": request}).data,
        status=status.HTTP_201_CREATED,
    )


# --- Slice 64: Email-forward ingestion ----------------------------------


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def inbox_address_view(request: Request) -> Response:
    """Return the per-tenant magic email-forward address.

    Generates the inbox token on first call so the customer
    immediately gets a working address without an explicit
    "enable email forwarding" gesture.
    """
    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    from apps.identity import services as identity_services

    if not identity_services.can_user_act_for_organization(request.user, organization_id):
        return Response(
            {"detail": "You are not a member of that organization."},
            status=status.HTTP_403_FORBIDDEN,
        )

    from . import email_forward

    address = email_forward.inbox_address_for_org(organization_id)
    return Response({"address": address})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def rotate_inbox_token_view(request: Request) -> Response:
    """Rotate the per-tenant inbox token (Slice 80).

    Owner / admin only. Old token stops resolving immediately;
    customer is responsible for updating any forwarding rules
    pointed at the old address. Returns the new full magic
    address so the FE can render it without a follow-up GET.

    Optional body: ``{"reason": "..."}`` — recorded on the audit
    chain alongside the actor + token prefixes.
    """
    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    from apps.identity import services as identity_services
    from apps.identity.models import OrganizationMembership

    if not identity_services.can_user_act_for_organization(request.user, organization_id):
        return Response(
            {"detail": "You are not a member of that organization."},
            status=status.HTTP_403_FORBIDDEN,
        )

    role = (
        OrganizationMembership.objects.filter(user=request.user, organization_id=organization_id)
        .values_list("role__name", flat=True)
        .first()
    )
    if role not in ("owner", "admin"):
        return Response(
            {"detail": "Only owners and admins can rotate the inbox token."},
            status=status.HTTP_403_FORBIDDEN,
        )

    reason = str((request.data or {}).get("reason") or "").strip()
    from . import email_forward

    try:
        address = email_forward.rotate_inbox_token(
            organization_id=organization_id,
            actor_user_id=request.user.id,
            reason=reason,
        )
    except email_forward.EmailForwardError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"address": address})


from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import authentication_classes


@csrf_exempt
@api_view(["GET", "POST"])
@permission_classes([])
@authentication_classes([])
def whatsapp_webhook_view(request: Request) -> Response:
    """WhatsApp Cloud API webhook endpoint (Slice 82).

    GET — Meta's subscription handshake. Returns ``hub.challenge``
    iff ``hub.verify_token`` matches the platform's configured
    verify token (SystemSetting ``whatsapp.verify_token``).

    POST — inbound message events. Verifies ``X-Hub-Signature-256``
    against the App Secret, parses Meta's batched payload, fetches
    media bytes per item, and creates one IngestionJob per
    supported attachment.

    Both halves fail closed (401/503) when the platform secrets
    are not configured — Meta retries on 5xx so a misconfigured
    deployment doesn't silently swallow customer messages.
    """
    from apps.administration.services import system_setting

    from . import whatsapp

    if request.method == "GET":
        expected = system_setting(
            namespace="whatsapp",
            key="verify_token",
            env_fallback="WHATSAPP_VERIFY_TOKEN",
        )
        if not expected:
            return Response(
                {"detail": "WhatsApp ingestion is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        if mode == "subscribe" and token and token == expected and challenge:
            # Meta wants the raw challenge string echoed verbatim.
            from django.http import HttpResponse

            return HttpResponse(challenge, content_type="text/plain")
        return Response({"detail": "Verification failed."}, status=status.HTTP_403_FORBIDDEN)

    # POST: signed inbound event.
    app_secret = system_setting(
        namespace="whatsapp",
        key="app_secret",
        env_fallback="WHATSAPP_APP_SECRET",
    )
    access_token = system_setting(
        namespace="whatsapp",
        key="access_token",
        env_fallback="WHATSAPP_ACCESS_TOKEN",
    )
    if not app_secret or not access_token:
        return Response(
            {"detail": "WhatsApp ingestion is not configured."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    raw_body = request.body or b""
    presented = request.headers.get("X-Hub-Signature-256", "")
    if not whatsapp.verify_meta_signature(
        app_secret=app_secret, body=raw_body, signature_header=presented
    ):
        return Response(
            {"detail": "Invalid signature."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    body = request.data or {}

    # Production media fetcher — short-circuits for tests via the
    # ``WHATSAPP_MEDIA_FETCHER`` SystemSetting hook (kept opt-in; the
    # default is a real Cloud-API call). Tests bypass via the
    # ``MediaFetcher``-injected variant of ``parse_meta_webhook_payload``.
    def _fetch(media_id: str) -> tuple[bytes, str, str]:
        return _fetch_meta_media(media_id, access_token=access_token)

    try:
        messages = whatsapp.parse_meta_webhook_payload(body, media_fetcher=_fetch)
    except Exception as exc:
        return Response({"detail": f"Invalid payload: {exc}"}, status=status.HTTP_400_BAD_REQUEST)

    results = []
    for message in messages:
        try:
            results.append(whatsapp.process_inbound_whatsapp_message(message))
        except whatsapp.PhoneNumberNotFoundError as exc:
            # Per-message — one unknown number doesn't drop the rest
            # of the batch. We log + continue so Meta gets a 200 and
            # doesn't retry the whole payload.
            results.append({"error": str(exc), "message_id": message.message_id})
        except whatsapp.WhatsAppForwardError as exc:
            results.append({"error": str(exc), "message_id": message.message_id})

    return Response({"results": results})


def _fetch_meta_media(media_id: str, *, access_token: str) -> tuple[bytes, str, str]:
    """Fetch media bytes from Meta Cloud API by media id.

    Two-step: ``GET /v18.0/{id}`` returns a signed URL + mime;
    ``GET <url>`` returns the bytes. Bearer-auth on both.
    Kept module-private — the webhook view injects this into the
    parser as ``media_fetcher``.
    """
    import urllib.request

    meta_url = f"https://graph.facebook.com/v18.0/{media_id}"
    req = urllib.request.Request(  # noqa: S310 — fixed https graph host
        meta_url, headers={"Authorization": f"Bearer {access_token}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — fixed https graph host
        import json as _json

        descriptor = _json.loads(resp.read().decode("utf-8"))
    media_url = descriptor.get("url") or ""
    mime = str(descriptor.get("mime_type") or "")
    if not media_url:
        raise RuntimeError(f"Meta media descriptor missing url for {media_id!r}")
    req2 = urllib.request.Request(  # noqa: S310 — Meta-issued https URL
        media_url, headers={"Authorization": f"Bearer {access_token}"}
    )
    with urllib.request.urlopen(req2, timeout=30) as resp:  # noqa: S310 — Meta-issued https URL
        body = resp.read()
    # Meta doesn't include a filename — the message-level ``filename``
    # (when present, on document) is preferred; we hand back an empty
    # hint here so the parser falls back to the declared name.
    return body, mime, ""


@csrf_exempt
@api_view(["POST"])
@permission_classes([])
@authentication_classes([])
def email_forward_webhook_view(request: Request) -> Response:
    """Inbound email webhook receiver.

    Provider-agnostic: accepts a JSON body with the parsed email +
    attachments. Today we accept the minimal shape a Mailgun /
    SendGrid / SES + Lambda integration produces. Bearer-token auth
    via the ``X-ZeroKey-Inbound-Token`` header (operator-managed
    in SystemSetting('email_inbound')).

    Body:
        {
          "to": "invoices+abc123@inbox.zerokey.symprio.com",
          "from": "billing@vendor.com",
          "subject": "Invoice INV-001 attached",
          "message_id": "<msgid@vendor.com>",
          "attachments": [
            {
              "filename": "invoice.pdf",
              "mime_type": "application/pdf",
              "body_b64": "<base64>"
            }, ...
          ]
        }
    """
    # Auth: shared bearer token, configured in SystemSetting.
    from apps.administration.services import system_setting

    expected_token = system_setting(
        namespace="email_inbound",
        key="webhook_token",
        env_fallback="EMAIL_INBOUND_WEBHOOK_TOKEN",
    )
    presented = request.headers.get("X-ZeroKey-Inbound-Token", "")
    if not expected_token or not presented or presented != expected_token:
        return Response(
            {"detail": "Unauthorized."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    body = request.data or {}
    from . import email_forward

    try:
        attachments = []
        for raw in body.get("attachments") or []:
            if not isinstance(raw, dict):
                continue
            try:
                decoded = base64.b64decode(raw.get("body_b64") or "")
            except (binascii.Error, ValueError):
                continue
            attachments.append(
                email_forward.InboundAttachment(
                    filename=str(raw.get("filename") or "attachment"),
                    mime_type=str(raw.get("mime_type") or "application/octet-stream"),
                    body=decoded,
                )
            )
        email = email_forward.InboundEmail(
            to=str(body.get("to") or "").strip(),
            sender=str(body.get("from") or "").strip(),
            subject=str(body.get("subject") or "")[:255],
            message_id=str(body.get("message_id") or "")[:255],
            attachments=attachments,
        )
        result = email_forward.process_inbound_email(email)
    except email_forward.InboxNotFoundError as exc:
        # 404 so the provider can mark the bounce / dead-letter the
        # forward — it'll never resolve by retrying.
        return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
    except email_forward.EmailForwardError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)
