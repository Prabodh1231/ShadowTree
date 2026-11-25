"""Step 2: stored vectors, the vec migration, the background re-embed, rerank fallback and cut-off.
No model and no network: embed and rerank are the stubs from conftest."""
import sqlite3

import pytest
from conftest import run_scan

from app import ai_classify, ai_embed, db, search, vectors
from app.search import MIN_MATCH, match_percent


def test_scan_stores_unit_vectors(client, sample_root):
    run_scan(client, sample_root)
    rows = db.get_conn().execute("SELECT vec FROM files").fetchall()
    assert len(rows) == 4 and all(r["vec"] and len(r["vec"]) % 4 == 0 for r in rows)
    assert abs(float((ai_embed.from_blob(rows[0]["vec"]) ** 2).sum()) - 1.0) < 1e-4


def test_migration_adds_vec_to_an_old_db(tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    c = sqlite3.connect(old)
    c.executescript("""CREATE TABLE files (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL, ext TEXT NOT NULL, kind TEXT NOT NULL, size INTEGER NOT NULL, mtime REAL NOT NULL,
        sha256 TEXT, title TEXT, summary TEXT, keywords TEXT NOT NULL DEFAULT '[]', text_excerpt TEXT,
        ai_status TEXT NOT NULL DEFAULT 'fallback', ai_error TEXT, client_meta TEXT NOT NULL DEFAULT '{}', indexed_at TEXT);
        INSERT INTO files(path, name, ext, kind, size, mtime, title) VALUES ('/x/a.txt','a.txt','.txt','text',1,1.0,'Old row');""")
    c.commit()
    c.close()
    monkeypatch.setenv("VEILFS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VEILFS_DB_PATH", str(old))
    db.close_thread_conns()
    db.init_db()
    db.init_db()  # idempotent
    conn = db.get_conn()
    assert "vec" in {r["name"] for r in conn.execute("PRAGMA table_info(files)")}
    row = conn.execute("SELECT title, vec FROM files").fetchone()
    assert row["title"] == "Old row" and row["vec"] is None
    db.close_thread_conns()


def test_missing_vectors_are_embedded_in_the_background(client, sample_root):
    run_scan(client, sample_root)
    conn = db.get_conn()
    conn.execute("UPDATE files SET vec=NULL")
    conn.commit()
    t = vectors.start_backfill()
    t.join(10)
    assert conn.execute("SELECT count(*) c FROM files WHERE vec IS NULL").fetchone()["c"] == 0


def test_embed_missing_survives_a_missing_model(client, sample_root, monkeypatch):
    run_scan(client, sample_root)
    conn = db.get_conn()
    conn.execute("UPDATE files SET vec=NULL")
    conn.commit()

    def not_ready(texts, wait=None):
        raise ai_classify.NotReady("no potion")
    monkeypatch.setattr(ai_embed, "embed", not_ready)
    assert vectors.embed_missing(conn) == 0
    assert conn.execute("SELECT count(*) c FROM files WHERE vec IS NULL").fetchone()["c"] == 4


def test_changed_file_loses_its_old_vector(client, sample_root):
    run_scan(client, sample_root)
    (sample_root / "invoice.txt").write_text("Invoice INV-9 totally new words zebra giraffe.", encoding="utf-8")
    conn = db.get_conn()
    old = conn.execute("SELECT vec FROM files WHERE name='invoice.txt'").fetchone()["vec"]
    run_scan(client, sample_root)
    new = conn.execute("SELECT vec FROM files WHERE name='invoice.txt'").fetchone()["vec"]
    assert new is not None and new != old


def test_rerank_missing_falls_back_to_cosine_order(client, sample_root, monkeypatch):
    run_scan(client, sample_root)

    def gone(*a, **k):
        raise ai_classify.NotReady("FlashRank is not downloaded")
    monkeypatch.setattr(ai_classify, "rerank", gone)
    body = client.get("/search", params={"q": "diary lake dog"}).json()
    assert body["rerank"] is False and "re-ranker" in body["note"]
    assert body["results"][0]["name"] == "diary.md" and body["results"][0]["score"] is None


def test_no_vectors_and_no_reranker_is_plain_text_search(client, sample_root, monkeypatch):
    run_scan(client, sample_root)

    def gone(*a, **k):
        raise ai_classify.NotReady("not downloaded")
    monkeypatch.setattr(ai_classify, "rerank", gone)
    monkeypatch.setattr(ai_embed, "embed", gone)
    body = client.get("/search", params={"q": "Northwind"}).json()
    assert body["rerank"] is False and "Plain text" in body["note"]
    assert body["results"][0]["name"] == "invoice.txt"


def test_nonsense_query_lands_in_weak(client, sample_root):
    run_scan(client, sample_root)
    body = client.get("/search", params={"q": "volcano penguin"}).json()
    assert body["results"] == [] and 1 <= len(body["weak"]) <= 3
    assert all(w["match"] < MIN_MATCH for w in body["weak"])


def test_real_match_is_strong_and_first(client, sample_root):
    run_scan(client, sample_root)
    body = client.get("/search", params={"q": "invoice"}).json()
    assert body["results"][0]["name"] == "invoice.txt" and body["results"][0]["match"] >= 80


def test_match_percent_modes():
    # reranker agrees: its sigmoid dominates
    assert match_percent(3.0, 0.5, 1.0, True) >= 90
    # weak agreement (z about 0) with a decent cosine and no keyword match stays below the cut-off
    assert match_percent(0.1, 0.345, 0.0, True) < MIN_MATCH
    # reranker sees only noise: never reaches the cut-off, even with a perfect cosine and a lone FTS hit
    assert match_percent(-10.8, 0.9, 1.0, True) < MIN_MATCH
    assert match_percent(-11.5, 0.05, 0.0, False) < match_percent(-10.8, 0.3, 0.0, False)
    # no reranker: cosine decides, 0.35 is a full match
    assert match_percent(None, 0.35, 0.0, False) == 100
    assert match_percent(None, 0.05, 0.0, False) < MIN_MATCH
    assert match_percent(None, None, 0.0, False) == 0

def test_real_rerank_and_embed_never_download(tmp_path, monkeypatch):
    """With an empty data dir the real functions say NotReady and touch no network (sockets are blocked)."""
    monkeypatch.setenv("VEILFS_DATA_DIR", str(tmp_path))
    ai_classify.close()
    ai_embed.close()
    from test_step1 import _ORIG, _ORIG_E
    with pytest.raises(ai_classify.NotReady, match="not downloaded"):
        _ORIG["rerank"]("q", ["p"])
    with pytest.raises(ai_classify.NotReady, match="not downloaded"):
        _ORIG_E(["x"])
