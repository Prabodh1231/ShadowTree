"""Tests for the Phase 1 review fixes (C1 and the MUST/SHOULD items)."""
import pytest

from conftest import run_scan


def _inv(client):
    return next(c for c in client.get("/files").json() if c["name"] == "invoice.txt")


def test_c1_cards_have_sha256_and_patch_checks_it(client, sample_root):
    run_scan(client, sample_root)
    cards = client.get("/files").json()
    assert all(len(c["sha256"]) == 64 for c in cards)
    inv = _inv(client)
    url = f"/files/{inv['id']}/client-meta"
    body = {"has_pii": True, "pii_types": ["EMAIL"]}
    assert client.patch(url, json=body).status_code == 422                      # sha256 is required
    assert client.patch(url, json={**body, "sha256": "abc"}).status_code == 422  # not 64 hex chars
    r = client.patch(url, json={**body, "sha256": "0" * 64})
    assert r.status_code == 409                                                  # differs from the DB row
    assert client.get(f"/files/{inv['id']}").json()["client_meta"] == {}         # nothing stored
    r = client.patch(url, json={**body, "sha256": inv["sha256"].upper()})
    assert r.status_code == 200 and r.json()["sha256"] == inv["sha256"]
    assert _inv(client)["client_meta"]["sha256"] == inv["sha256"]