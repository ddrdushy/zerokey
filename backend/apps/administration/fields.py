"""Encrypted-at-rest Django field subclasses (Slice 95).

Apply these in place of ``CharField`` / ``TextField`` on columns that
hold PII (phone numbers, addresses, SST numbers, secondary-ID values).
The wire-level behaviour is transparent: model code reads / writes
plaintext, the DB sees ciphertext.

Why a field subclass and not a serializer-level transform:

  - It enforces the contract at the model layer — every code path
    that talks to the column (admin, raw queryset, signals,
    arbitrary services) gets the encryption automatically. A
    serializer-level transform leaks plaintext to anything that
    bypasses the serializer.
  - The migration that converts existing rows can call the same
    field class via ``model.objects.iterator()`` + ``save()``, so
    we don't maintain two encrypt-paths.

What we do NOT encrypt (deliberate):

  - TINs — public; printed on every invoice; matched on for
    CustomerMaster lookup.
  - Legal names — public; printed; matched on for fuzzy customer
    matching.
  - Email addresses — login + audit identity; equality lookups
    everywhere.
  - Currency codes, MSIC codes, classification codes, country
    codes — public reference data.

Querying note:

  - These fields cannot be used in equality / LIKE / icontains
    filters — Fernet is randomized so the same plaintext encrypts
    to different ciphertext each call. Application-level logic
    must read-then-compare, not query-then-equal.
  - The columns ARE indexable on the ciphertext (PRIMARY KEY +
    FK targets are unaffected) but the index is useless for value-
    matching.

Pattern:

    from apps.administration.fields import EncryptedCharField, EncryptedTextField

    class Invoice(...):
        supplier_phone = EncryptedCharField(max_length=128, blank=True, default="")
        supplier_address = EncryptedTextField(blank=True, default="")
"""

from __future__ import annotations

from django.db import models

from .crypto import decrypt_value, encrypt_value


class _EncryptedFieldMixin:
    """Shared encrypt-on-save / decrypt-on-load behaviour.

    ``from_db_value`` runs every time the ORM hydrates a row.
    ``get_prep_value`` runs every time we hand a value to the DB.
    Both call into the existing ``apps.administration.crypto``
    envelope so the same Fernet/SECRET_KEY-derived key is used.
    """

    description_suffix: str = " (encrypted at rest)"

    def from_db_value(self, value, expression, connection):  # type: ignore[no-untyped-def]
        # ``decrypt_value`` is pass-through for legacy plaintext, so
        # rows written before this field was applied still read
        # cleanly. Empty / None stays empty / None.
        if value is None:
            return None
        return decrypt_value(value)

    def to_python(self, value):  # type: ignore[no-untyped-def]
        # Called on assignment + model_form clean. We treat plain
        # strings as plaintext here — the encryption only happens
        # when the value heads to the DB (``get_prep_value``).
        if value is None:
            return None
        if not isinstance(value, str):
            return str(value)
        # Defensive: if a caller hands us an already-encrypted
        # string (e.g. raw paste from the DB), return the plaintext.
        return decrypt_value(value)

    def get_prep_value(self, value):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        # ``encrypt_value`` is idempotent on already-encrypted input,
        # so re-saving a row that came back from the DB doesn't add
        # an encryption layer.
        return encrypt_value(value)


class EncryptedCharField(_EncryptedFieldMixin, models.CharField):
    """``CharField`` with transparent at-rest encryption.

    The DB column is ``VARCHAR(max_length)`` — pick a max_length
    generous enough to hold the ciphertext. Fernet output is
    ~150% the size of plaintext + the 5-char ``enc1:`` marker;
    a 128-char plaintext encrypts to ~220 chars. When unsure,
    pick double the plaintext budget + 32.
    """

    description = "Encrypted character field"


class EncryptedTextField(_EncryptedFieldMixin, models.TextField):
    """``TextField`` with transparent at-rest encryption.

    Use for variable-length PII — addresses, free-form notes —
    where the plaintext can be hundreds of characters. The
    underlying TEXT column has no length cap so the ciphertext
    bloat doesn't matter.
    """

    description = "Encrypted text field"
