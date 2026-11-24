"""SQLite schema, seeds and a per-thread connection helper. Stdlib sqlite3 + FTS5."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  ext TEXT NOT NULL,
  kind TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  sha256 TEXT,
  title TEXT,
  summary TEXT,
  keywords TEXT NOT NULL DEFAULT '[]',
  text_excerpt TEXT,
  ai_status TEXT NOT NULL DEFAULT 'fallback',
  ai_error TEXT,
  client_meta TEXT NOT NULL DEFAULT '{}',
  indexed_at TEXT
);
CREATE TABLE IF NOT EXISTS virtual_folders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  emoji TEXT,
  description TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('default','custom','smart')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS file_folder_links (
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  folder_id INTEGER NOT NULL REFERENCES virtual_folders(id) ON DELETE CASCADE,
  score REAL,
  PRIMARY KEY (file_id, folder_id)
);
CREATE INDEX IF NOT EXISTS idx_links_folder ON file_folder_links(folder_id);
CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
  name, title, summary, keywords, text_excerpt, tokenize='unicode61'
);
"""

UNSORTED = "Unsorted"
SENSITIVE = "Sensitive (PII)"

SEED_FOLDERS = [
    ("Finance & Receipts", "\U0001F9FE", "invoices, receipts, bills, payments and money spent", "default"),
    ("Work & Research", "\U0001F4BC", "work documents, meeting notes, projects and research", "default"),
    ("Personal & Notes", "\U0001F4D3", "personal journal, diary, feelings and private notes", "default"),
    ("Screenshots & Media", "\U0001F5BC\uFE0F", "screenshots, images, photos, audio recordings and media", "default"),
    (UNSORTED, "\U0001F4E5", "Files that match no folder", "smart"),
    (SENSITIVE, "\U0001F512", "Files with personal data, computed from the privacy scan", "smart"),
]

_local = threading.local()


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a new connection (FKs on, WAL, busy timeout)."""
    path = Path(db_path or get_settings().db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def get_conn() -> sqlite3.Connection:
    """One connection per (thread, db path). Never share across threads."""
    path = str(get_settings().db_path)
    conns = getattr(_local, "conns", None)
    if conns is None:
        conns = _local.conns = {}
    conn = conns.get(path)
    if conn is None:
        conn = conns[path] = connect(Path(path))
    return conn


def close_thread_conns() -> None:
    for c in getattr(_local, "conns", {}).values():
        try:
            c.close()
        except sqlite3.Error:
            pass
    _local.conns = {}


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    for name, emoji, desc, kind in SEED_FOLDERS:
        conn.execute(
            "INSERT OR IGNORE INTO virtual_folders(name, emoji, description, kind) VALUES (?,?,?,?)",
            (name, emoji, desc, kind))
    conn.commit()


def folder_id(name: str) -> int:
    return get_conn().execute("SELECT id FROM virtual_folders WHERE name=?", (name,)).fetchone()["id"]


# ---- files + FTS (files_fts rowid == files.id, synced here) -------------------

def _fts_row(conn: sqlite3.Connection, file_id: int) -> None:
    r = conn.execute("SELECT name, title, summary, keywords, text_excerpt FROM files WHERE id=?",
                     (file_id,)).fetchone()
    conn.execute("DELETE FROM files_fts WHERE rowid=?", (file_id,))
    kws = " ".join(json.loads(r["keywords"] or "[]"))
    conn.execute(
        "INSERT INTO files_fts(rowid, name, title, summary, keywords, text_excerpt) VALUES (?,?,?,?,?,?)",
        (file_id, r["name"], r["title"] or "", r["summary"] or "", kws, r["text_excerpt"] or ""))


def upsert_file(conn: sqlite3.Connection, rec: dict) -> int:
    """Insert or update by path. Keeps client_meta on update. Returns file id."""
    keywords = json.dumps(rec.get("keywords") or [], ensure_ascii=False)
    row = conn.execute("SELECT id FROM files WHERE path=?", (rec["path"],)).fetchone()
    cols = ("name", "ext", "kind", "size", "mtime", "sha256", "title", "summary",
            "text_excerpt", "ai_status", "ai_error", "indexed_at")
    vals = [rec.get(c) for c in cols]
    if row:
        fid = row["id"]
        conn.execute(
            "UPDATE files SET " + ", ".join(f"{c}=?" for c in cols) + ", keywords=? WHERE id=?",
            (*vals, keywords, fid))
    else:
        cur = conn.execute(
            "INSERT INTO files(path, " + ", ".join(cols) + ", keywords) VALUES (?" + ",?" * (len(cols) + 1) + ")",
            (rec["path"], *vals, keywords))
        fid = cur.lastrowid
    _fts_row(conn, fid)
    conn.commit()
    return fid


def delete_file(conn: sqlite3.Connection, file_id: int) -> None:
    conn.execute("DELETE FROM files_fts WHERE rowid=?", (file_id,))
    conn.execute("DELETE FROM files WHERE id=?", (file_id,))  # links cascade
    conn.commit()


# ---- API views ------------------------------------------------------------------

def file_cards(conn: sqlite3.Connection, rows, full: bool = False) -> list[dict]:
    """Rows of `files` -> JSON-ready dicts with folder links. `full` adds the excerpt."""
    rows = list(rows)
    ids = [r["id"] for r in rows]
    links: dict[int, list[dict]] = {i: [] for i in ids}
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        q = ("SELECT l.file_id, l.folder_id, l.score, v.name, v.emoji FROM file_folder_links l "
             "JOIN virtual_folders v ON v.id=l.folder_id WHERE l.file_id IN (%s) ORDER BY l.score DESC"
             % ",".join("?" * len(part)))
        for l in conn.execute(q, part):
            links[l["file_id"]].append({"folder_id": l["folder_id"], "name": l["name"],
                                        "emoji": l["emoji"], "score": l["score"]})
    out = []
    for r in rows:
        d = {"id": r["id"], "path": r["path"], "name": r["name"], "ext": r["ext"], "kind": r["kind"],
             "size": r["size"], "mtime": r["mtime"], "title": r["title"], "summary": r["summary"],
             "keywords": json.loads(r["keywords"] or "[]"), "ai_status": r["ai_status"],
             "ai_error": r["ai_error"], "sha256": r["sha256"], "client_meta": json.loads(r["client_meta"] or "{}"),
             "indexed_at": r["indexed_at"], "folders": links[r["id"]]}
        if full:
            d["text_excerpt"] = r["text_excerpt"]
        out.append(d)
    return out
