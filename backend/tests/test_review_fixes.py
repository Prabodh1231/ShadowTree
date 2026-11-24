"""Tests for the Phase 1 review fixes (C1 and the MUST/SHOULD items)."""
import pytest

from app import ai_classify
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


# ---- L1: search cut-off, weak list, name boost, candidate cap, batches --------------

def test_l1_name_boost_rules():
    from app.search import name_boost
    assert name_boost("invoice", "invoice INV-3307.pdf", "") == 20
    assert name_boost("INVOI", "x.pdf", "Quarterly invoice") == 20              # prefix, title, any case
    assert name_boost("the invoice", "invoice.txt", "") == 20                    # stopword ignored
    assert name_boost("money I spent", "coffee receipt.txt", "Corner cafe") == 0
    assert name_boost("invoice march", "invoice.txt", "") == 0                   # every token must match
    assert name_boost("the", "the.txt", "") == 0                                 # nothing left after stopwords


def test_l1_cutoff_weak_and_shape(client, sample_root, monkeypatch):
    run_scan(client, sample_root)
    monkeypatch.setattr(ai_classify, "rerank", lambda q, p, wait=None: [0.05] * len(p))
    body = client.get("/search", params={"q": "zzqx"}).json()
    assert body["results"] == [] and 1 <= len(body["weak"]) <= 3
    files_keys = set(client.get("/files").json()[0])
    for w in body["weak"]:
        assert set(w) == files_keys | {"score", "match"} and w["match"] < 35
    monkeypatch.setattr(ai_classify, "rerank",
                        lambda q, p, wait=None: [0.9 if "invoice" in x.lower() else 0.05 for x in p])
    ok = client.get("/search", params={"q": "invoice"}).json()
    assert ok["weak"] == [] and ok["results"] and all(r["match"] >= 35 for r in ok["results"])
    assert set(ok["results"][0]) == files_keys | {"score", "match"}


def test_l1_invoice_name_boost_ranks_it_first(client, sample_root, monkeypatch):
    run_scan(client, sample_root)
    # voice.wav's text also says "invoice" and the model likes it slightly better
    monkeypatch.setattr(ai_classify, "rerank",
                        lambda q, p, wait=None: [0.62 if "electricity" in x.lower() else 0.60 for x in p])
    body = client.get("/search", params={"q": "invoice"}).json()
    assert body["results"][0]["name"] == "invoice.txt"


def test_l1_candidates_capped_and_batched(client, tmp_path, monkeypatch):
    from app.ai_cactus import MODEL_LOCK
    root = tmp_path / "many"
    root.mkdir()
    for n in range(80):
        (root / f"note{n:02d}.txt").write_text(f"Note number {n} about zeppelins and balloons for the test.")
    run_scan(client, root)
    sizes = []

    def rerank(q, passages, wait=None):
        assert not MODEL_LOCK.locked()      # the search itself never holds the model lock
        sizes.append(len(passages))
        return [0.5] * len(passages)
    monkeypatch.setattr(ai_classify, "rerank", rerank)
    client.get("/search", params={"q": "zeppelins"})
    assert sum(sizes) == 60 and max(sizes) == 16 and len(sizes) == 4   # 40 FTS + 20 recent


# ---- L2: ungrounded model text is rejected ---------------------------------------------

def test_l2_is_grounded_digitale_migration():
    from app import extractors as ex
    src = "Weekly sync. Sam owns the API migration and will report on Friday."
    assert not ex.is_grounded("Sam owns the API migration digitale migration", src)   # 6 of 7 = 86%
    assert ex.is_grounded("Sam owns the API migration", src)
    assert not ex.is_grounded("", src)


def test_l2_build_card_uses_fallback_for_ungrounded_summary(tmp_path, monkeypatch):
    from app import ai_cactus
    f = tmp_path / "meeting notes.md"
    f.write_text("Weekly sync.\nSam owns the API migration and will report on Friday.\n", encoding="utf-8")
    monkeypatch.setattr(ai_cactus, "structured", lambda text: {
        "title": "Migration meeting", "summary": "Sam owns the API migration digitale migration",
        "keywords": ["api"]})
    card = ai_cactus.build_card(f, "text", f.name)
    assert "digitale" not in card["summary"] and "Sam owns the API migration" in card["summary"]
    assert "summary:fallback(ungrounded)" in card["ai_error"]
    assert "title:fallback(ungrounded)" in card["ai_error"]      # "Migration meeting" is not in the text either


# ---- N3: an unreadable folder must not shrink the index ---------------------------------

def test_n3_unreadable_folder_keeps_its_rows(client, sample_root, monkeypatch):
    import os
    run_scan(client, sample_root)
    assert len(client.get("/files").json()) == 4
    real = os.scandir

    def flaky(path="."):
        if os.path.basename(str(path)) == "sub dir":
            raise PermissionError("denied (test)")
        return real(path)
    monkeypatch.setattr(os, "scandir", flaky)
    (sample_root / "shot.png").unlink()                       # a real removal still happens
    st = run_scan(client, sample_root)
    names = {c["name"] for c in client.get("/files").json()}
    assert "diary.md" in names                                # inside the unreadable folder: kept
    assert "shot.png" not in names and st["stats"]["removed"] == 1
    assert any("sub dir" in e and "cannot list" in e for e in st["errors"])
