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

# ---- L4: creating a folder keeps every existing link ---------------------------------

def _links(client):
    return {(c["name"], f["name"]) for c in client.get("/files").json() for f in c["folders"]}


def test_l4_new_folder_keeps_existing_links(client, sample_root, monkeypatch):
    from app import ai_classify, jobs
    run_scan(client, sample_root)
    inv = _inv(client)
    assert client.patch(f"/files/{inv['id']}/client-meta",
                        json={"sha256": inv["sha256"], "has_pii": True}).status_code == 200
    before = _links(client)
    assert ("shot.png", "Unsorted") in before and ("invoice.txt", "Finance & Receipts") in before
    real = ai_classify.classify

    def relative(text, labels):
        # A label set with the new folder shifts the old scores down (the bug L4 describes).
        out = real(text, labels)
        has_new = any("lake" in l for l in labels)
        t = text.lower()
        return [(0.9 if ("shot" in t or "invoice" in t) else 0.1) if "lake" in l
                else (0.1 if has_new else s) for l, s in zip(labels, out)]
    monkeypatch.setattr(ai_classify, "classify", relative)
    fid = client.post("/folders", json={"name": "Lake", "description": "lake photos"}).json()["folder_id"]
    assert jobs.wait_idle(60)
    after = _links(client)
    assert (before - {("shot.png", "Unsorted")}) <= after            # nothing else was removed
    assert ("shot.png", "Unsorted") not in after                     # gained a link: Unsorted goes
    assert ("shot.png", "Lake") in after and ("invoice.txt", "Lake") in after
    assert ("diary.md", "Personal & Notes") in after and ("diary.md", "Lake") not in after
    inv_folders = {f["name"] for f in _inv(client)["folders"]}
    assert {"Finance & Receipts", "Lake"} <= inv_folders and "Unsorted" not in inv_folders
    # Sensitive is computed from client_meta and never gets links
    sens = next(f for f in client.get("/folders").json() if f["name"] == "Sensitive (PII)")
    assert sens["file_count"] == 1
    assert [c["id"] for c in client.get("/files", params={"folder_id": sens["id"]}).json()] == [inv["id"]]
    assert all(l[1] != "Sensitive (PII)" for l in after)
    assert any(f["id"] == fid for f in client.get("/folders").json())
