"""Tests for the email delivery surface (Slice 52)."""

from __future__ import annotations

import json
import smtplib
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client

from apps.administration.models import SystemSetting
from apps.audit.models import AuditEvent
from apps.identity.models import (
    NotificationPreference,
    Organization,
    OrganizationMembership,
    Role,
    User,
)
from apps.notifications.email import is_email_configured, send_email
from apps.notifications.services import (
    deliver_for_event,
    render_email_template,
    send_test_email,
)


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def smtp_configured(db) -> SystemSetting:
    return SystemSetting.objects.create(
        namespace="email",
        values={
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_user": "AKIA",
            "smtp_password": "secret",
            "from_address": "no-reply@symprio.com",
            "from_name": "ZeroKey",
            "use_tls": "true",
        },
    )


@pytest.fixture
def staff_user(seeded) -> User:
    return User.objects.create_user(
        email="staff@symprio.com", password="x", is_staff=True
    )


@pytest.fixture
def org_owner(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme", tin="C10000000001", contact_email="o@a"
    )
    user = User.objects.create_user(email="o@a.test", password="x")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


@pytest.mark.django_db
class TestEmailConfigured:
    def test_returns_false_without_smtp(self) -> None:
        assert is_email_configured() is False

    def test_returns_true_with_smtp(self, smtp_configured) -> None:
        assert is_email_configured() is True


@pytest.mark.django_db
class TestSendEmail:
    def test_no_smtp_returns_failure(self) -> None:
        result = send_email(
            to="someone@example.com", subject="Hi", body="Test"
        )
        assert result.ok is False
        assert "not configured" in result.detail.lower()

    def test_invalid_recipient_returns_failure(self, smtp_configured) -> None:
        result = send_email(to="not-an-email", subject="Hi", body="Test")
        assert result.ok is False
        assert "invalid recipient" in result.detail.lower()

    def test_successful_send_uses_smtp(self, smtp_configured) -> None:
        fake_smtp = MagicMock()
        with patch("smtplib.SMTP", return_value=_smtp_context(fake_smtp)) as smtp_cls:
            result = send_email(
                to="recipient@example.com",
                subject="Test",
                body="Body",
            )
        assert result.ok is True
        # Connected to the right host/port + TLS + login + send.
        smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=20)
        fake_smtp.starttls.assert_called_once()
        fake_smtp.login.assert_called_once_with("AKIA", "secret")
        fake_smtp.send_message.assert_called_once()

    def test_smtp_error_does_not_raise(self, smtp_configured) -> None:
        fake_smtp = MagicMock()
        fake_smtp.send_message.side_effect = smtplib.SMTPException("nope")
        with patch("smtplib.SMTP", return_value=_smtp_context(fake_smtp)):
            result = send_email(
                to="recipient@example.com",
                subject="Test",
                body="Body",
            )
        assert result.ok is False
        assert "SMTPException" in result.detail
        # The message text "nope" must NOT be in the detail — SMTP
        # servers can echo credentials in error strings.
        assert "nope" not in result.detail

    def test_html_alternative_when_provided(self, smtp_configured) -> None:
        fake_smtp = MagicMock()
        with patch("smtplib.SMTP", return_value=_smtp_context(fake_smtp)):
            result = send_email(
                to="recipient@example.com",
                subject="Test",
                body="Plain",
                html_body="<p>Rich</p>",
            )
        assert result.ok is True
        # Inspect the EmailMessage that was sent.
        sent = fake_smtp.send_message.call_args[0][0]
        assert sent.is_multipart() is True


def _smtp_context(target):
    """Helper: smtplib.SMTP returns a context manager. Wrap a mock."""

    class _Ctx:
        def __enter__(self):
            return target

        def __exit__(self, *args):
            return False

    return _Ctx()


@pytest.mark.django_db
class TestSendTestEmail:
    def test_renders_test_template_and_audits(
        self, smtp_configured, staff_user
    ) -> None:
        fake_smtp = MagicMock()
        with patch("smtplib.SMTP", return_value=_smtp_context(fake_smtp)):
            result = send_test_email(
                to="ops@example.com", actor_user_id=staff_user.id
            )
        assert result["ok"] is True
        # Audit event recorded.
        event = (
            AuditEvent.objects.filter(action_type="notifications.email.test_sent")
            .order_by("-sequence")
            .first()
        )
        assert event is not None
        assert event.payload["ok"] is True

    def test_failure_audited_distinctly(self, smtp_configured) -> None:
        fake_smtp = MagicMock()
        fake_smtp.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"Bad creds"
        )
        with patch("smtplib.SMTP", return_value=_smtp_context(fake_smtp)):
            result = send_test_email(to="ops@example.com")
        assert result["ok"] is False
        event = (
            AuditEvent.objects.filter(
                action_type="notifications.email.test_failed"
            )
            .order_by("-sequence")
            .first()
        )
        assert event is not None


@pytest.mark.django_db
class TestDeliverForEvent:
    def test_no_template_returns_no_template_flag(self, org_owner) -> None:
        org, _ = org_owner
        result = deliver_for_event(
            organization_id=org.id,
            event_key="never.heard.of.this",
            context={},
        )
        assert result["no_template"] is True
        assert result["recipients_email_queued"] == 0

    def test_queues_email_for_active_member(
        self, smtp_configured, org_owner
    ) -> None:
        org, _user = org_owner
        with patch(
            "apps.notifications.tasks.send_email_task.delay"
        ) as queued:
            result = deliver_for_event(
                organization_id=org.id,
                event_key="invoice.validated",
                context={
                    "invoice_number": "INV-001",
                    "filename": "test.pdf",
                    "invoice_url": "https://app/x",
                },
            )
        assert result["recipients_email_queued"] == 1
        queued.assert_called_once()
        kwargs = queued.call_args.kwargs
        assert kwargs["to"] == "o@a.test"
        assert "INV-001" in kwargs["subject"]
        assert "test.pdf" in kwargs["body"]

    def test_skips_user_who_opted_out(
        self, smtp_configured, org_owner
    ) -> None:
        org, user = org_owner
        NotificationPreference.objects.create(
            organization=org,
            user=user,
            preferences={
                "invoice.validated": {"in_app": True, "email": False}
            },
        )
        with patch(
            "apps.notifications.tasks.send_email_task.delay"
        ) as queued:
            result = deliver_for_event(
                organization_id=org.id,
                event_key="invoice.validated",
                context={"invoice_number": "X", "filename": "x.pdf"},
            )
        assert result["recipients_email_queued"] == 0
        queued.assert_not_called()

    def test_skips_inactive_member(self, smtp_configured, seeded) -> None:
        org = Organization.objects.create(
            legal_name="A", tin="C10000000001", contact_email="o@a"
        )
        user = User.objects.create_user(email="x@a", password="x")
        OrganizationMembership.objects.create(
            user=user,
            organization=org,
            role=Role.objects.get(name="owner"),
            is_active=False,
        )
        with patch(
            "apps.notifications.tasks.send_email_task.delay"
        ) as queued:
            deliver_for_event(
                organization_id=org.id,
                event_key="invoice.validated",
                context={"invoice_number": "X", "filename": "y"},
            )
        queued.assert_not_called()


@pytest.mark.django_db
class TestAdminTestEmailEndpoint:
    def test_unauthenticated_rejected(self) -> None:
        response = Client().post(
            "/api/v1/admin/system-settings/email/test/",
            data=json.dumps({"to": "x@y.com"}),
            content_type="application/json",
        )
        assert response.status_code in (401, 403)

    def test_customer_403(self, seeded) -> None:
        u = User.objects.create_user(email="cust@x", password="x")
        client = Client()
        client.force_login(u)
        response = client.post(
            "/api/v1/admin/system-settings/email/test/",
            data=json.dumps({"to": "x@y.com"}),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_invalid_to_400(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.post(
            "/api/v1/admin/system-settings/email/test/",
            data=json.dumps({"to": "not-an-email"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_staff_test_send_returns_smtp_outcome(
        self, smtp_configured, staff_user
    ) -> None:
        client = Client()
        client.force_login(staff_user)
        fake_smtp = MagicMock()
        with patch("smtplib.SMTP", return_value=_smtp_context(fake_smtp)):
            response = client.post(
                "/api/v1/admin/system-settings/email/test/",
                data=json.dumps({"to": "ops@example.com"}),
                content_type="application/json",
            )
        assert response.status_code == 200
        assert response.json()["ok"] is True


@pytest.mark.django_db
class TestRenderTemplate:
    def test_missing_context_does_not_raise(self) -> None:
        # Template uses {invoice_number} but caller forgot to pass it.
        # Should fall through to empty string, not crash.
        result = render_email_template("invoice.validated", {})
        assert result is not None
        subject, body = result
        # The placeholder yields an empty value, leaving "Invoice  is..."
        assert "is ready to submit" in subject
