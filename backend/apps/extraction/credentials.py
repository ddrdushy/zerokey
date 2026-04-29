"""Per-engine credential resolver.

Adapters call ``engine_credential(...)`` instead of ``os.environ.get(...)``.
The resolver checks the ``Engine.credentials`` JSONField first so the
super-admin can rotate or replace a vendor key from the operations console
without touching ``.env`` or restarting the service. The env var remains
the fallback so a fresh deployment still boots before the super-admin has
populated anything.

Why this lives in the extraction app rather than administration: the
``Engine`` row is the natural per-engine identity, and routing rules already
attach metadata to it. Platform-wide integrations (LHDN, Stripe) go through
``apps.administration.services.system_setting`` instead; that's the single-
namespace surface, this is the per-engine surface.

At-rest encryption (Slice 55): values are stored as ciphertext via
``apps.administration.crypto`` and decrypted transparently here on
read. Legacy plaintext rows pass through unchanged so the migration
to encrypted storage is gradual; the migration that ships with
Slice 55 walks existing rows and rewrites them. The redaction
filter still excludes ``Engine.credentials`` so even decrypted
values never reach logs.
"""

from __future__ import annotations

import os

from .capabilities import EngineUnavailable
from .models import Engine


def engine_credential(
    *,
    engine_name: str,
    key: str,
    env_fallback: str | None = None,
) -> str | None:
    """Resolve a single credential value for an engine adapter.

    Lookup order:
      1. ``Engine.credentials[key]`` for the row whose ``name == engine_name``
      2. ``os.environ[env_fallback]`` if provided
      3. ``None``

    Empty strings are treated as "not set" so an editor that cleared a
    field falls through to env, matching the SystemSetting resolver.
    Returns ``None`` rather than raising — adapter ``__init__`` paths
    typically want to inspect both an api key and an endpoint and raise
    a single ``EngineUnavailable`` summarizing what's missing.
    """
    engine = Engine.objects.filter(name=engine_name).first()
    if engine is not None:
        # Slice 55: credentials live as ciphertext at rest.
        # decrypt_value passes legacy plaintext through unchanged.
        from apps.administration.crypto import decrypt_value

        raw = engine.credentials.get(key) if isinstance(engine.credentials, dict) else None
        if raw not in (None, ""):
            value = decrypt_value(raw) if isinstance(raw, str) else raw
            if value not in (None, ""):
                return str(value)

    if env_fallback:
        env_value = os.environ.get(env_fallback, "").strip()
        if env_value:
            return env_value

    return None


def require_engine_credential(
    *,
    engine_name: str,
    key: str,
    env_fallback: str | None = None,
) -> str:
    """Same as ``engine_credential`` but raises ``EngineUnavailable`` if missing.

    This matches the existing graceful-degrade contract: when an adapter
    can't run because credentials aren't configured, the calling pipeline
    records the reason and surfaces it in the UI rather than crashing.
    """
    value = engine_credential(engine_name=engine_name, key=key, env_fallback=env_fallback)
    if value is None:
        sources = [f"Engine({engine_name}).credentials[{key}]"]
        if env_fallback:
            sources.append(f"env {env_fallback}")
        raise EngineUnavailable(
            f"Credential {engine_name}.{key} not configured "
            f"(looked in {', '.join(sources)})"
        )
    return value
