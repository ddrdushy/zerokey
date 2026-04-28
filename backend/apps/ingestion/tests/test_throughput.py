"""Tests for ``throughput_for_organization`` + the GET /ingestion/throughput/ endpoint.

The bar chart on the dashboard reads from these. The test surface covers:

  - jobs are bucketed by their upload date and split into validated / review.
  - jobs older than the window are excluded.
  - other orgs' jobs are excluded.
  - the series is gap-filled to the requested length, oldest first.
  - the totals reconcile with the per-day series.
  - the endpoint requires authentication and an active organization.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.test import Client
from django.utils import timezone

from apps.identity.models import Organization, Role
from apps.ingestion.models import IngestionJob
from apps.ingestion.services import throughput_for_organization


def _make_org(legal_name: str, tin: str) -> Organization:
    return Organization.objects.create(
        legal_name=legal_name, tin=tin, contact_email=f"ops@{tin.lower()}.example"
    )


REGISTRATION_PAYLOAD = {
    "email": "owner@acme.example",
    "password": "long-enough-password",
    "organization_legal_name": "ACME Sdn Bhd",
    "organization_tin": "C20880050010",
    "contact_email": "ops@acme.example",
}


@pytest.fixture
def seeded_roles(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def authed_client(seeded_roles) -> tuple[Client, str]:
    client = Client()
    response = client.post(
        "/api/v1/identity/register/",
        data=REGISTRATION_PAYLOAD,
        content_type="application/json",
    )
    assert response.status_code == 201
    return client, response.json()["active_organization_id"]


def _make_job(
    *,
    organization_id: UUID | str,
    status: str,
    upload_timestamp=None,
    filename: str | None = None,
) -> IngestionJob:
    job = IngestionJob.objects.create(
        organization_id=organization_id,
        source_channel=IngestionJob.SourceChannel.WEB_UPLOAD,
        original_filename=filename or f"{uuid4().hex}.pdf",
        file_size=1024,
        file_mime_type="application/pdf",
        s3_object_key=f"tenants/{organization_id}/ingestion/{uuid4().hex}/x.pdf",
        status=status,
    )
    if upload_timestamp is not None:
        IngestionJob.objects.filter(pk=job.pk).update(upload_timestamp=upload_timestamp)
        job.refresh_from_db()
    return job


@pytest.mark.django_db
class TestThroughputService:
    def test_buckets_jobs_by_status(self) -> None:
        org = _make_org("ACME", "C20000000001")
        _make_job(organization_id=org.id, status=IngestionJob.Status.VALIDATED)
        _make_job(organization_id=org.id, status=IngestionJob.Status.READY_FOR_REVIEW)
        _make_job(organization_id=org.id, status=IngestionJob.Status.AWAITING_APPROVAL)
        _make_job(organization_id=org.id, status=IngestionJob.Status.ERROR)
        _make_job(organization_id=org.id, status=IngestionJob.Status.EXTRACTING)

        result = throughput_for_organization(organization_id=org.id, days=7)
        assert result["totals"]["validated"] == 1
        assert result["totals"]["review"] == 2
        assert result["totals"]["failed"] == 1
        assert result["totals"]["in_flight"] == 1
        assert result["totals"]["uploads"] == 5

    def test_other_orgs_jobs_are_excluded(self) -> None:
        mine = _make_org("Mine", "C20000000002")
        theirs = _make_org("Theirs", "C20000000003")

        _make_job(organization_id=mine.id, status=IngestionJob.Status.VALIDATED)
        _make_job(organization_id=theirs.id, status=IngestionJob.Status.VALIDATED)
        _make_job(organization_id=theirs.id, status=IngestionJob.Status.VALIDATED)

        assert throughput_for_organization(organization_id=mine.id)["totals"]["validated"] == 1
        assert throughput_for_organization(organization_id=theirs.id)["totals"]["validated"] == 2

    def test_jobs_older_than_window_are_excluded(self) -> None:
        org = _make_org("ACME", "C20000000004")
        now = timezone.now()
        _make_job(
            organization_id=org.id,
            status=IngestionJob.Status.VALIDATED,
            upload_timestamp=now - timedelta(days=30),
        )
        _make_job(organization_id=org.id, status=IngestionJob.Status.VALIDATED)

        assert (
            throughput_for_organization(organization_id=org.id, days=7)["totals"]["validated"] == 1
        )

    def test_series_is_gap_filled_oldest_first(self) -> None:
        org = _make_org("ACME", "C20000000005")
        _make_job(organization_id=org.id, status=IngestionJob.Status.VALIDATED)

        result = throughput_for_organization(organization_id=org.id, days=7)
        series = result["series"]
        assert len(series) == 7
        dates = [point["date"] for point in series]
        assert dates == sorted(dates)
        # Each point has the chart's expected shape.
        for point in series:
            assert {"date", "day", "validated", "review"} <= point.keys()
        # Today's bucket holds the validated job.
        assert series[-1]["validated"] == 1

    def test_per_day_series_matches_window_totals(self) -> None:
        org = _make_org("ACME", "C20000000006")
        for _ in range(3):
            _make_job(organization_id=org.id, status=IngestionJob.Status.VALIDATED)
        for _ in range(2):
            _make_job(organization_id=org.id, status=IngestionJob.Status.READY_FOR_REVIEW)

        result = throughput_for_organization(organization_id=org.id, days=7)
        validated_in_series = sum(p["validated"] for p in result["series"])
        review_in_series = sum(p["review"] for p in result["series"])
        assert validated_in_series == result["totals"]["validated"] == 3
        assert review_in_series == result["totals"]["review"] == 2


@pytest.mark.django_db
class TestThroughputEndpoint:
    def test_unauthenticated_is_rejected(self) -> None:
        response = Client().get("/api/v1/ingestion/throughput/")
        assert response.status_code in (401, 403)

    def test_returns_only_active_orgs_data(self, authed_client) -> None:
        client, org_id = authed_client
        _make_job(organization_id=org_id, status=IngestionJob.Status.VALIDATED)
        # Another tenant's job — must not appear in the response.
        other_org = _make_org("Other", "C29999999999")
        _make_job(organization_id=other_org.id, status=IngestionJob.Status.VALIDATED)

        response = client.get("/api/v1/ingestion/throughput/")
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["totals"]["validated"] == 1
        assert len(body["series"]) == 7

    def test_days_parameter_is_honored_and_clamped(self, authed_client) -> None:
        client, _ = authed_client
        response = client.get("/api/v1/ingestion/throughput/?days=14")
        assert response.status_code == 200
        assert len(response.json()["series"]) == 14

        # Out-of-range values clamp rather than 400 — the chart never breaks
        # because of a bad query string.
        response = client.get("/api/v1/ingestion/throughput/?days=999")
        assert response.status_code == 200
        assert len(response.json()["series"]) == 90

        response = client.get("/api/v1/ingestion/throughput/?days=0")
        assert response.status_code == 200
        assert len(response.json()["series"]) == 1

    def test_invalid_days_parameter_is_rejected(self, authed_client) -> None:
        client, _ = authed_client
        response = client.get("/api/v1/ingestion/throughput/?days=abc")
        assert response.status_code == 400
