"""Smoke tests for the global URL surface."""

import pytest
from django.test import Client


@pytest.mark.django_db
def test_healthz_returns_ok() -> None:
    client = Client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_identity_ping_returns_ok() -> None:
    client = Client()
    response = client.get("/api/v1/identity/ping/")
    assert response.status_code == 200
    body = response.json()
    assert body["context"] == "identity"
    assert body["status"] == "ok"
