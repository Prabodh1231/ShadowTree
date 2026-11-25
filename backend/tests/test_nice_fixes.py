"""Code-check NICE fixes 3, 5, 6, 8 (reports/shadowtree/check-backend-code.md). No models."""
import json

import numpy as np
from conftest import run_scan

from app import ai_ocr, db, search


def test_3_ocr_error_leaves_no_stamp_and_is_reread(client, sample_root, calls, monkeypatch):
    def boom(data):
        raise RuntimeError("onnx died")
    monkeypatch.setattr(ai_ocr, "ocr_image", boom)
    run_scan(client, sample_root)
    conn = db.get_conn()
    assert conn.execute("SELECT ext_ver FROM files WHERE name='shot.png'").fetchone()["ext_ver"] is None
    assert conn.execute("SELECT ext_ver FROM files WHERE name='invoice.txt'").fetchone()["ext_ver"] == "ocr-v1"
    monkeypatch.setattr(ai_ocr, "ocr_image", lambda data: ["Now readable"])
    before = calls.describe
    run_scan(client, sample_root)                      # unchanged file, but read again now OCR works
    assert calls.describe == before + 1
    row = conn.execute("SELECT ext_ver, text_excerpt FROM files WHERE name='shot.png'").fetchone()
    assert row["ext_ver"] == "ocr-v1" and row["text_excerpt"].startswith("Text in the image:\nNow readable")


def test_5_missing_ocr_models_is_skipped_not_a_fallback(client, sample_root, monkeypatch):
    def missing(data):
        raise ai_ocr.NotDownloaded("OCR models are not downloaded")
    monkeypatch.setattr(ai_ocr, "ocr_image", missing)
    run_scan(client, sample_root)
    shot = next(c for c in client.get("/files").json() if c["name"] == "shot.png")
    assert shot["ai_error"].startswith("ocr:skipped,") and "ocr: " not in shot["ai_error"]   # no failure note


def test_6_reread_of_unchanged_file_keeps_client_meta(client, sample_root):
    run_scan(client, sample_root)
    shot = next(c for c in client.get("/files").json() if c["name"] == "shot.png")
    assert client.patch(f"/files/{shot['id']}/client-meta",
                        json={"sha256": shot["sha256"], "has_pii": True}).status_code == 200
    conn = db.get_conn()
    conn.execute("UPDATE files SET ext_ver=NULL WHERE id=?", (shot["id"],))   # forces the one-time re-read
    conn.commit()
    st = run_scan(client, sample_root)
    assert st["stats"]["changed"] == 1
    meta = json.loads(conn.execute("SELECT client_meta FROM files WHERE id=?", (shot["id"],)).fetchone()["client_meta"])
    assert meta.get("has_pii") is True                 # same sha256: the privacy scan still applies
    (sample_root / "shot.png").write_bytes((sample_root / "shot.png").read_bytes() + b"\0")
    run_scan(client, sample_root)
    meta = json.loads(conn.execute("SELECT client_meta FROM files WHERE id=?", (shot["id"],)).fetchone()["client_meta"])
    assert meta == {}                                  # content changed: reset


def test_8_wrong_length_vector_is_skipped(client, sample_root):
    run_scan(client, sample_root)
    conn = db.get_conn()
    conn.execute("UPDATE files SET vec=? WHERE name='diary.md'", (np.zeros(10, np.float32).tobytes(),))
    conn.commit()
    q = np.zeros(256, np.float32)
    q[0] = 1.0
    out = search.cosine_top(conn, q, 50)
    did = conn.execute("SELECT id FROM files WHERE name='diary.md'").fetchone()["id"]
    assert did not in out and len(out) == 3
    r = client.get("/search", params={"q": "diary lake"})
    assert r.status_code == 200 and r.json()["results"][0]["name"] == "diary.md"   # still found by text
