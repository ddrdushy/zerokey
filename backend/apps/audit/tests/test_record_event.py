"""Integration tests for ``record_event`` and ``verify_chain`` (DB)."""

from __future__ import annotations

import pytest

from apps.audit.chain import ChainIntegrityError
from apps.audit.models import AuditEvent
from apps.audit.services import record_event, verify_chain


@pytest.mark.django_db
class TestRecordEvent:
    def test_first_event_starts_at_sequence_one(self) -> None:
        event = record_event(
            action_type="auth.login_success",
            actor_type=AuditEvent.ActorType.USER,
            actor_id="user-1",
        )
        assert event.sequence == 1

    def test_sequences_are_gap_free_and_monotonic(self) -> None:
        for i in range(5):
            record_event(
                action_type="auth.login_success",
                actor_type=AuditEvent.ActorType.USER,
                actor_id=f"user-{i}",
            )
        sequences = list(AuditEvent.objects.order_by("sequence").values_list("sequence", flat=True))
        assert sequences == [1, 2, 3, 4, 5]

    def test_each_event_links_to_the_previous_chain_hash(self) -> None:
        e1 = record_event(action_type="x", actor_type=AuditEvent.ActorType.SERVICE)
        e2 = record_event(action_type="x", actor_type=AuditEvent.ActorType.SERVICE)
        # e2's chain hash must include e1's chain hash; if e1 changed, e2 would too.
        assert bytes(e2.chain_hash) != bytes(e1.chain_hash)

    def test_verify_chain_passes_for_clean_log(self) -> None:
        for i in range(3):
            record_event(action_type=f"x.{i}", actor_type=AuditEvent.ActorType.SERVICE)
        assert verify_chain() == 3

    def test_verify_chain_detects_payload_tampering(self) -> None:
        e1 = record_event(
            action_type="invoice.created",
            actor_type=AuditEvent.ActorType.USER,
            actor_id="u1",
            payload={"amount": "100.00"},
        )
        # Tamper with the stored payload AFTER the chain hash was computed.
        AuditEvent.objects.filter(pk=e1.pk).update(payload={"amount": "9000.00"})
        with pytest.raises(ChainIntegrityError, match="content_hash"):
            verify_chain()

    def test_record_event_refuses_float_payloads(self) -> None:
        from apps.audit.canonical import FloatNotAllowedError

        with pytest.raises(FloatNotAllowedError):
            record_event(
                action_type="x",
                actor_type=AuditEvent.ActorType.SERVICE,
                payload={"amount": 12.5},  # forbidden — must be Decimal or string
            )

    def test_audit_events_are_immutable_at_application_layer(self) -> None:
        event = record_event(action_type="x", actor_type=AuditEvent.ActorType.SERVICE)
        with pytest.raises(RuntimeError, match="immutable"):
            event.action_type = "y"
            event.save()

    def test_audit_events_cannot_be_deleted_at_application_layer(self) -> None:
        event = record_event(action_type="x", actor_type=AuditEvent.ActorType.SERVICE)
        with pytest.raises(RuntimeError, match="cannot be deleted"):
            event.delete()
