import hashlib
import json
import threading

import pytest

from app import ai_cactus, ai_classify, db, jobs
from app.config import get_settings
from conftest import run_scan


def fingerprint(root):
    out = {}
    for p in sorted(root.rglob("*")):
        st = p.stat()
        out[str(p.relative_to(root))] = (
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None, st.st_size, st.st_mtime_ns)
    return out


def test_read_only_guarantee(client, sample_root):
    before = fingerprint(sample_root)
    st = run_scan(client, sample_root)
    assert st["state"] == "done" and st["errors"] == []
    assert client.post("/folders", json={"name": "Lake walks", "description": "walks by the lake"}).status_code == 201
    assert jobs.wait_idle(60)
    assert fingerprint(sample_root) == before
    assert len(client.get("/files").json()) == 4


def test_rescan_skips_unchanged(client, sample_root, calls):
    run_scan(client, sample_root)
    first = (calls.structured, calls.describe, calls.transcribe, calls.classify)
    assert first[0] >= 3 and first[1] == 1 and first[2] == 1
    st = run_scan(client, sample_root)
    assert (calls.structured, calls.describe, calls.transcribe, calls.classify) == first
    assert st["stats"]["skipped"] == 4


def test_changed_file_is_reindexed_and_missing_removed(client, sample_root, calls):
    run_scan(client, sample_root)
    (sample_root / "invoice.txt").write_text("Invoice INV-9999 changed content for the test file.", encoding="utf-8")
    (sample_root / "shot.png").unlink()
    st = run_scan(client, sample_root)
    assert st["stats"]["changed"] == 1 and st["stats"]["removed"] == 1
    assert len(client.get("/files").json()) == 3


def test_reveal_rejects_unknown_and_paths(client, sample_root, monkeypatch):
    run_scan(client, sample_root)
    ran = []
    monkeypatch.setattr("app.main.subprocess.run", lambda *a, **k: ran.append((a, k)))
    assert client.post("/reveal", json={"file_id": 99999}).status_code == 404
    assert client.post("/reveal", json={"path": "C:\\Windows\\notepad.exe"}).status_code == 422
    assert client.post("/reveal", json={"file_id": 1, "path": "x"}).status_code == 422
    assert ran == []
    card = client.get("/files").json()[0]
    assert client.post("/reveal", json={"file_id": card["id"]}).status_code == 200
    args, kw = ran[0]
    assert args[0] == ["explorer", "/select,", card["path"]] and not kw.get("shell") and not kw.get("check")


def test_below_threshold_goes_to_unsorted(client, sample_root):
    run_scan(client, sample_root)
    cards = {c["name"]: c for c in client.get("/files").json()}
    assert [f["name"] for f in cards["shot.png"]["folders"]] == ["Unsorted"]
    assert "Finance & Receipts" in [f["name"] for f in cards["invoice.txt"]["folders"]]


def test_cactus_error_gives_fallback(client, sample_root, monkeypatch):
    def boom(text):
        raise RuntimeError("engine exploded")
    monkeypatch.setattr(ai_cactus, "structured", boom)
    run_scan(client, sample_root)
    inv = next(c for c in client.get("/files").json() if c["name"] == "invoice.txt")
    assert inv["ai_status"] == "fallback" and "engine exploded" in inv["ai_error"]
    assert inv["title"] == "Invoice" and inv["summary"]


def test_fk_cascade(client, sample_root):
    run_scan(client, sample_root)
    conn = db.get_conn()
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    fid = conn.execute("SELECT id FROM files LIMIT 1").fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM file_folder_links WHERE file_id=?", (fid,)).fetchone()[0] > 0
    conn.execute("DELETE FROM files WHERE id=?", (fid,))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM file_folder_links WHERE file_id=?", (fid,)).fetchone()[0] == 0


def test_fts_sync_update_and_delete(client, sample_root):
    run_scan(client, sample_root)
    conn = db.get_conn()
    q = "SELECT COUNT(*) FROM files_fts WHERE files_fts MATCH ?"
    assert conn.execute(q, ('"Northwind"',)).fetchone()[0] == 1
    (sample_root / "invoice.txt").write_text("Totally different words about zeppelins and balloons.", encoding="utf-8")
    run_scan(client, sample_root)
    assert conn.execute(q, ('"Northwind"',)).fetchone()[0] == 0
    assert conn.execute(q, ('"zeppelins"',)).fetchone()[0] == 1
    (sample_root / "invoice.txt").unlink()
    run_scan(client, sample_root)
    assert conn.execute(q, ('"zeppelins"',)).fetchone()[0] == 0
    n_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM files_fts WHERE files_fts MATCH 'a* OR b* OR d* OR s* OR v*'").fetchone()[0] <= n_files


@pytest.mark.parametrize("q", ["INV-2041", '"', 'it"s', "NEAR(a b)", "a:b", "money I spent", "*"])
def test_search_does_not_error(client, sample_root, q):
    run_scan(client, sample_root)
    r = client.get("/search", params={"q": q})
    assert r.status_code == 200
    body = r.json()
    assert body["rerank"] is True
    if q == "INV-2041":
        assert body["results"][0]["name"] == "invoice.txt" and body["results"][0]["match"] >= 70
    for x in body["results"]:
        assert 0 <= x["match"] <= 100


def test_search_falls_back_to_bm25_when_rerank_fails(client, sample_root, monkeypatch):
    run_scan(client, sample_root)

    def busy(*a, **k):
        raise ai_classify.Busy("busy")
    monkeypatch.setattr(ai_classify, "rerank", busy)
    body = client.get("/search", params={"q": "Northwind"}).json()
    assert body["rerank"] is False and body["results"][0]["name"] == "invoice.txt"
    assert body["results"][0]["score"] is None and body["results"][0]["match"] >= 60 and body["note"]


def test_post_folders_during_running_job(client, sample_root, monkeypatch):
    gate = threading.Event()
    real = ai_classify.classify

    def slow(text, labels):
        gate.wait(10)
        return real(text, labels)
    monkeypatch.setattr(ai_classify, "classify", slow)
    assert client.post("/scan", json={"root": str(sample_root)}).status_code == 200
    assert client.post("/scan", json={"root": str(sample_root)}).status_code == 409
    r = client.post("/folders", json={"name": "Lake", "description": "lake walks"})
    assert r.status_code == 201 and r.json()["job"] == "queued"
    assert client.post("/folders", json={"name": "lake"}).status_code == 409  # duplicate, case-insensitive
    gate.set()
    assert jobs.wait_idle(60)
    st = client.get("/scan/status").json()
    assert st["kind"] == "reclassify" and st["state"] == "done"


def test_scan_root_validation(client, tmp_path):
    assert client.post("/scan", json={"root": str(tmp_path / "nope")}).status_code == 400
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert client.post("/scan", json={"root": str(f)}).status_code == 400
    assert client.post("/scan", json={"root": str(get_settings().data_dir)}).status_code == 400
    assert client.post("/scan", json={"root": str(get_settings().data_dir / "sub")}).status_code == 400
    assert client.post("/scan", json={"root": str(tmp_path), "extra": 1}).status_code == 422


def test_bad_host_and_origin_rejected(client):
    assert client.get("/health", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/health", headers={"origin": "http://evil.example"}).status_code == 403
    r = client.get("/health", headers={"origin": "http://localhost:5173"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in r.headers


def test_health_loads_nothing(client):
    h = client.get("/health").json()
    assert h["classifier"]["loaded"] is False
    assert set(h["cactus"]["files_present"]) == {"needle3", "whistle", "mirage"}


def test_sensitive_counts_and_client_meta(client, sample_root):
    run_scan(client, sample_root)
    card = next(c for c in client.get("/files").json() if c["name"] == "invoice.txt")
    fid, sha = card["id"], card["sha256"]
    r = client.patch(f"/files/{fid}/client-meta",
                     json={"sha256": sha, "has_pii": True, "pii_types": ["EMAIL"], "topics": ["finance"]})
    assert r.status_code == 200
    sens = next(f for f in client.get("/folders").json() if f["name"] == "Sensitive (PII)")
    assert sens["file_count"] == 1
    assert [c["id"] for c in client.get("/files", params={"folder_id": sens["id"]}).json()] == [fid]
    assert client.patch(f"/files/{fid}/client-meta", json={"sha256": sha, "has_pii": True, "x": 1}).status_code == 422
    assert client.get(f"/files/{fid}").json()["text_excerpt"]


def test_snapshot_uses_relative_paths(client, sample_root):
    run_scan(client, sample_root)
    snap = client.get("/export/snapshot").json()
    paths = {f["path"] for f in snap["files"]}
    assert "invoice.txt" in paths and "sub dir/diary.md" in paths
    assert all(":" not in p and "text_excerpt" not in f for p, f in ((f["path"], f) for f in snap["files"]))
    assert str(sample_root) not in json.dumps(snap)
    absolute = client.get("/export/snapshot", params={"relative_paths": "false"}).json()
    assert all(f["path"].startswith(str(sample_root.resolve())) for f in absolute["files"])


def test_scanner_skips_hidden_big_and_junk(client, sample_root, monkeypatch):
    import ctypes
    (sample_root / "node_modules").mkdir()
    (sample_root / "node_modules" / "x.txt").write_text("skip me please, I am in node_modules")
    (sample_root / ".git").mkdir()
    (sample_root / ".git" / "y.txt").write_text("skip me please, I am in git")
    hidden = sample_root / "hidden.txt"
    hidden.write_text("hidden file content that should be skipped")
    if hasattr(ctypes, "windll"):
        ctypes.windll.kernel32.SetFileAttributesW(str(hidden), 2)
    monkeypatch.setenv("MAX_FILE_MB", "0")  # everything is "too big" except empty files
    st = run_scan(client, sample_root)
    assert client.get("/files").json() == [] and st["state"] == "done"
    monkeypatch.setenv("MAX_FILE_MB", "25")
    run_scan(client, sample_root)
    names = {c["name"] for c in client.get("/files").json()}
    assert names == {"invoice.txt", "diary.md", "shot.png", "voice.wav"}


def test_socket_guard_blocks_external():
    import socket
    s = socket.socket()
    with pytest.raises(AssertionError):
        s.connect(("93.184.216.34", 80))
    s.close()


def test_tauri_origins_allowed_and_health_names_app(client):
    for origin in ("http://tauri.localhost", "tauri://localhost"):
        r = client.get("/health", headers={"origin": origin})
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == origin
    assert client.get("/health").json()["app"] == "ShadowTree"
