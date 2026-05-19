"""Desktop release feed.

Phase 5 of DESKTOP_PIVOT_PLAN.md.

Two audiences:

  - **Customers** call ``GET /api/v1/licenses/desktop-release/`` from
    the marketing /download page (session-authenticated). The endpoint
    returns the latest release for each platform with a short-lived
    signed S3 URL.
  - **The desktop app itself** uses electron-updater pointed at
    ``releases.zerokey.symprio.com`` directly — it doesn't go through
    this endpoint. (electron-updater needs a fixed URL pattern for
    its update protocol; we serve latest.yml + the asset directly
    from a public CloudFront distribution.)

So this view is *only* for the human "I want to download the
installer" flow. It returns enough metadata for the /download page to
render plus a one-shot URL the customer's browser follows.

The signed-URL minting is currently a stub: we return the public
CloudFront URL directly. The S3 + CloudFront setup (with signed-URL
keypair) is real-world ops work tracked in DESKTOP_PIVOT_PLAN.md
Phase 5 — wire the real signer when the bucket exists. Until then
the cloud at least serves the right shape.
"""

from __future__ import annotations

import os
from typing import Any

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from .models import License


# Release feed configuration. In production these come from env;
# locally we expose the same shape with stub URLs so the /download
# page can render end-to-end.
RELEASE_FEED_BASE = os.environ.get(
    "ZK_RELEASE_FEED_BASE", "https://releases.zerokey.symprio.com"
)
LATEST_VERSION = os.environ.get("ZK_DESKTOP_LATEST_VERSION", "0.1.0")
RELEASE_CHANNEL = os.environ.get("ZK_DESKTOP_RELEASE_CHANNEL", "stable")


def _platform_assets(version: str) -> dict[str, dict[str, Any]]:
    """Per-platform download metadata for the given version."""
    base = f"{RELEASE_FEED_BASE.rstrip('/')}/{RELEASE_CHANNEL}"
    return {
        "windows": {
            "url": f"{base}/ZeroKey-Setup-{version}.exe",
            "filename": f"ZeroKey-Setup-{version}.exe",
            "size_bytes": None,
            "sha256": "",
        },
        "mac": {
            "url": f"{base}/ZeroKey-{version}.dmg",
            "filename": f"ZeroKey-{version}.dmg",
            "size_bytes": None,
            "sha256": "",
        },
        "linux": {
            "url": f"{base}/ZeroKey-{version}.AppImage",
            "filename": f"ZeroKey-{version}.AppImage",
            "size_bytes": None,
            "sha256": "",
        },
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def desktop_release_view(request: Request) -> Response:
    """Return the latest release info if the caller has an active license.

    Customers without an active license see a 403 — the /download
    page surfaces that as "you need to buy a license first".
    """
    has_active = License.objects.filter(
        owner_user=request.user, status=License.Status.ACTIVE
    ).exists()
    if not has_active:
        return Response(
            {
                "detail": (
                    "You don't have an active ZeroKey license. "
                    "Buy one from the pricing page first."
                ),
                "code": "no_active_license",
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    return Response(
        {
            "version": LATEST_VERSION,
            "channel": RELEASE_CHANNEL,
            "platforms": _platform_assets(LATEST_VERSION),
            "release_notes_url": f"{RELEASE_FEED_BASE.rstrip('/')}/{RELEASE_CHANNEL}/notes-{LATEST_VERSION}.md",
            # Single signed URL per platform — short-lived in
            # production (10 min); here it's the same as the unsigned
            # CloudFront URL because we don't have the keypair yet.
            "expires_in_seconds": 600,
        }
    )
