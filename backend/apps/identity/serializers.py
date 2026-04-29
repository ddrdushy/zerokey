"""DRF serializers for the identity context."""

from __future__ import annotations

from rest_framework import serializers

from .models import Organization, OrganizationMembership, User


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True, min_length=12, style={"input_type": "password"}
    )
    organization_legal_name = serializers.CharField(max_length=255)
    organization_tin = serializers.CharField(max_length=32)
    contact_email = serializers.EmailField()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class OrganizationSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "legal_name", "tin", "subscription_state", "trial_state"]


class OrganizationDetailSerializer(serializers.ModelSerializer):
    """Full organization shape for the Settings → Organization page.

    Editable fields are tracked in
    ``apps.identity.services.EDITABLE_ORGANIZATION_FIELDS``; the view
    enforces the allowlist on PATCH. The serializer's ``read_only_fields``
    is for safety against an accidental writable Meta default — the actual
    write path is the ``update_organization`` service, never the
    serializer's ``.save()``.
    """

    class Meta:
        model = Organization
        fields = [
            "id",
            "legal_name",
            "tin",
            "sst_number",
            "registered_address",
            "contact_email",
            "contact_phone",
            "billing_currency",
            "trial_state",
            "subscription_state",
            "certificate_uploaded",
            "certificate_expiry_date",
            "logo_url",
            "language_preference",
            "timezone",
            "extraction_mode",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class MembershipSerializer(serializers.ModelSerializer):
    organization = OrganizationSummarySerializer(read_only=True)
    role = serializers.CharField(source="role.name", read_only=True)

    class Meta:
        model = OrganizationMembership
        fields = ["id", "organization", "role", "joined_date"]


class UserSerializer(serializers.ModelSerializer):
    memberships = serializers.SerializerMethodField()
    active_organization_id = serializers.SerializerMethodField()
    impersonation = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "preferred_language",
            "preferred_timezone",
            "two_factor_enabled",
            "is_staff",
            "memberships",
            "active_organization_id",
            "impersonation",
        ]

    def get_memberships(self, obj: User) -> list[dict]:
        from .services import memberships_for

        return MembershipSerializer(memberships_for(obj), many=True).data

    def get_active_organization_id(self, obj: User) -> str | None:
        request = self.context.get("request")
        if request is None:
            return None
        session = getattr(request, "session", None)
        return session.get("organization_id") if session is not None else None

    def get_impersonation(self, obj: User) -> dict | None:
        """If this session is in an active impersonation, return its details.

        The customer dashboard renders an impersonation banner when this
        is non-null. Auto-expires past TTL — the service auto-closes
        the row and returns None on the next request.
        """
        request = self.context.get("request")
        if request is None:
            return None
        session = getattr(request, "session", None)
        if session is None:
            return None
        sid = session.get("impersonation_session_id")
        if not sid:
            return None
        # Lazy import to avoid circular: administration imports identity.
        from apps.administration.services import (
            get_active_impersonation_for_session,
        )

        result = get_active_impersonation_for_session(session_id=sid)
        if result is None:
            # Auto-expired — clear the session keys so the next /me/ is fast.
            session.pop("impersonation_session_id", None)
            session.pop("organization_id", None)
        return result


class SwitchOrganizationSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField()
