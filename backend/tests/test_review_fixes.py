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
    assert ("shot.png", "Screenshots & Media") in before and ("invoice.txt", "Finance & Receipts") in before
    monkeypatch.setenv("NEWFOLDER_COSINE", "-1")   # L4 is about which links get written: no pre-filter here
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
    assert before <= after                                           # nothing was removed
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
    monkeypatch.setattr(ai_classify, "rerank", lambda q, p, wait=None: [-11.0] * len(p))
    body = client.get("/search", params={"q": "zzqx"}).json()
    assert body["results"] == [] and 1 <= len(body["weak"]) <= 3
    files_keys = set(client.get("/files").json()[0])
    for w in body["weak"]:
        assert set(w) == files_keys | {"score", "match"} and w["match"] < 25
    monkeypatch.setattr(ai_classify, "rerank",
                        lambda q, p, wait=None: [3.0 if "invoice" in x.lower() else -11.0 for x in p])
    ok = client.get("/search", params={"q": "invoice"}).json()
    assert ok["weak"] == [] and ok["results"] and all(r["match"] >= 25 for r in ok["results"])
    assert set(ok["results"][0]) == files_keys | {"score", "match"}


def test_l1_invoice_name_boost_ranks_it_first(client, sample_root, monkeypatch):
    run_scan(client, sample_root)
    # voice.wav's text also says "invoice" and the model likes it slightly better
    monkeypatch.setattr(ai_classify, "rerank",
                        lambda q, p, wait=None: [1.0 if "electricity" in x.lower() else 0.0 for x in p])
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
        return [0.0] * len(passages)
    monkeypatch.setattr(ai_classify, "rerank", rerank)
    client.get("/search", params={"q": "zeppelins"})
    assert 50 <= sum(sizes) <= 90 and max(sizes) == 16   # 40 FTS hits + up to 50 closest vectors, in batches of 16


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


# ---- S1: skipped-file counts ---------------------------------------------------------------

def test_s1_skip_counts_with_fake_attributes(client, sample_root, monkeypatch):
    import os
    from types import SimpleNamespace
    (sample_root / "big.txt").write_text("a tiny file that pretends to be huge for the size check")
    attrs = {"invoice.txt": 0x400000, "diary.md": 0x1000, "voice.wav": 0x400,  # cloud, offline, reparse
             "shot.png": 0x20}                                # hydrated: archive only
    real = os.scandir

    class Entry:
        def __init__(self, e):
            self._e = e
            self.name, self.path = e.name, e.path

        def stat(self, follow_symlinks=True):
            st = self._e.stat(follow_symlinks=follow_symlinks)
            size = 26 * 1024 * 1024 if self.name == "big.txt" else st.st_size
            return SimpleNamespace(st_size=size, st_mtime=st.st_mtime,
                                   st_file_attributes=attrs.get(self.name, 0x20 if self._e.is_file() else 0x10))

        def __getattr__(self, n):
            return getattr(self._e, n)

    monkeypatch.setattr(os, "scandir", lambda path=".": [Entry(e) for e in real(path)])
    st = run_scan(client, sample_root)["stats"]
    assert st["skipped_too_large"] == 1
    assert st["skipped_cloud_only"] == 2           # 0x400000 and 0x1000
    assert st["skipped_hidden_or_link"] == 1       # the reparse point is still skipped
    assert all(isinstance(st[k], int) for k in ("skipped_too_large", "skipped_cloud_only", "skipped_hidden_or_link"))
    assert {c["name"] for c in client.get("/files").json()} == {"shot.png"}


def test_s1_keys_present_without_skips(client, sample_root):
    st = run_scan(client, sample_root)["stats"]
    assert (st["skipped_too_large"], st["skipped_cloud_only"], st["skipped_hidden_or_link"]) == (0, 0, 0)


# ---- N2: a refused scan keeps the old scan_root ------------------------------------------

def test_n2_refused_scan_does_not_change_scan_root(client, sample_root, tmp_path, monkeypatch):
    import threading
    from app import db, jobs
    gate = threading.Event()
    real = ai_classify.classify
    monkeypatch.setattr(ai_classify, "classify", lambda t, l: (gate.wait(10), real(t, l))[1])
    assert client.post("/scan", json={"root": str(sample_root)}).status_code == 200
    other = tmp_path / "other"
    other.mkdir()
    assert client.post("/scan", json={"root": str(other)}).status_code == 409
    row = db.get_conn().execute("SELECT value FROM app_meta WHERE key='scan_root'").fetchone()
    assert row["value"] == str(sample_root.resolve())
    gate.set()
    assert jobs.wait_idle(60)


# ---- L3 / L5: one-line ai_error, consistent with ai_status ---------------------------------

def test_l3_ai_error_is_one_short_line(tmp_path, monkeypatch):
    from app import ai_cactus
    f = tmp_path / "invoice.txt"
    f.write_text("Invoice INV-2041 from Northwind Supplies. Total due $960 by 15 December.", encoding="utf-8")

    def boom(text):
        raise RuntimeError("Cannot find the model files\n" + "huggingface says no " * 50)
    monkeypatch.setattr(ai_cactus, "structured", boom)
    card = ai_cactus.build_card(f, "text", f.name)
    err = card["ai_error"]
    assert card["ai_status"] == "fallback" and "\n" not in err and len(err) <= 200
    assert "RuntimeError: Cannot find the model files" in err
    assert err.endswith("keywords:freq") and "\u2026" in err and "title:fallback" in err   # suffix kept


def test_l5_ok_status_has_only_provenance(tmp_path, monkeypatch):
    from PIL import Image
    from app import ai_cactus
    f = tmp_path / "shot.png"
    Image.new("RGB", (40, 30), (1, 2, 3)).save(f)
    monkeypatch.setattr(ai_cactus, "describe_image", lambda p: "Monthly Budget\nGroceries $120.50 today")
    monkeypatch.setattr(ai_cactus, "structured", lambda t: None)
    card = ai_cactus.build_card(f, "image", f.name)
    assert card["ai_status"] == "ok"
    assert card["ai_error"].startswith("title:") and "|" not in card["ai_error"]
    assert "needle empty" in card["ai_error"] and "note:" in card["ai_error"]


# ---- L6 / N10: /health files_present has one shape -------------------------------------------

def test_l6_files_present_shape_on_both_stacks(client, monkeypatch):
    h = client.get("/health").json()
    for stack in ("cactus", "classifier"):
        fp = h[stack]["files_present"]
        assert fp and all(isinstance(k, str) and isinstance(v, bool) for k, v in fp.items())
    assert set(h["cactus"]["files_present"]) == {"needle3", "whistle", "mirage"}
    assert set(h["classifier"]["files_present"]) == {"deberta", "potion", "flashrank", "ocr"}
    assert h["classifier"]["hint"] and h["cactus"]["hint"]          # nothing downloaded in the test data dir


def test_n10_cactus_needs_the_engine_dll(client):
    from app.config import get_settings
    root = get_settings().data_dir / "cache" / "cactus"
    (root / "models" / "needle3").mkdir(parents=True)
    (root / "models" / "needle3" / "w.cact").write_bytes(b"x")
    assert client.get("/health").json()["cactus"]["files_present"]["needle3"] is False   # no engine yet
    (root / "engine" / "4.1.4" / "rev").mkdir(parents=True)
    (root / "engine" / "4.1.4" / "rev" / "libcactus.dll").write_bytes(b"x")
    assert client.get("/health").json()["cactus"]["files_present"]["needle3"] is True


# ---- N5: any Whistle load error is cached -------------------------------------------------

def test_n5_whistle_load_error_is_cached(tmp_path, monkeypatch):
    import sys
    import types
    from app import ai_cactus
    monkeypatch.setenv("VEILFS_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setattr(ai_cactus, "_state", {"needle": None, "mirage": None, "failed": {}, "loaded": set()})
    calls = []

    def transcribe(path, language=None):
        calls.append(path)
        raise RuntimeError("weights missing")          # not an ImportError
    monkeypatch.setitem(sys.modules, "cactus", types.SimpleNamespace(transcribe=transcribe))
    for _ in range(3):
        with pytest.raises(Exception):
            ai_cactus.transcribe_audio(tmp_path / "a.wav")
    assert len(calls) == 1 and "weights missing" in ai_cactus._state["failed"]["whistle"]


# ---- N11 / C-2 ---------------------------------------------------------------------------------

def test_n11_numeric_lines_with_currency_symbols_are_skipped():
    from app import extractors as ex
    assert ex._ONLY_NUM_DATE.match("\u20ac 1,200.00 / \u00a3 30")
    assert not ex._ONLY_NUM_DATE.match("what? 12")          # no stray '?' in the class
    text = "\u20ac 1,200.00 \u00a3 3,000.00 1,500.00 1,500.00\nThe team shipped the release on time."
    assert ex.fallback_summary(text) == "The team shipped the release on time."


def test_c2_cut_summary_ends_with_ellipsis():
    from app import extractors as ex
    s = ex.cut_text("word " * 200, 300)
    assert len(s) == 300 and s.endswith("\u2026")
    assert ex.cut_text("short", 300) == "short"


# ---- N3 (stat path) and N5 (reset per job) -------------------------------------------------

def test_n3_stat_failure_keeps_rows(client, sample_root, monkeypatch):
    import os
    run_scan(client, sample_root)
    assert len(client.get("/files").json()) == 4
    real = os.scandir

    class Entry:
        def __init__(self, e):
            self._e = e
            self.name, self.path = e.name, e.path

        def stat(self, follow_symlinks=True):
            if self.name in ("invoice.txt", "sub dir"):
                raise PermissionError("stat denied (test)")
            return self._e.stat(follow_symlinks=follow_symlinks)

        def __getattr__(self, n):
            return getattr(self._e, n)
    monkeypatch.setattr(os, "scandir", lambda path=".": [Entry(e) for e in real(path)])
    (sample_root / "shot.png").unlink()
    st = run_scan(client, sample_root)
    names = {c["name"] for c in client.get("/files").json()}
    assert {"invoice.txt", "diary.md"} <= names          # file and subfolder rows stay
    assert "shot.png" not in names and st["stats"]["removed"] == 1


def test_n5_failure_cache_is_cleared_at_job_start(client, sample_root):
    from app import ai_cactus
    ai_cactus._state["failed"]["whistle"] = "RuntimeError: earlier job failed"
    run_scan(client, sample_root)
    assert ai_cactus._state["failed"] == {}
