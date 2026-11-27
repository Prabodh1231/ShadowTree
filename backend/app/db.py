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
MEDIA = "Screenshots & Media"  # decided by file type (image or audio), never by the classifier

SEED_FOLDERS = [
    # Descriptions are the NLI hypothesis "This text is about {name}: {description}." Short "or"
    # lists score far better with DeBERTa than long lists (see reports/shadowtree/step3.md).
    ("Finance & Receipts", "\U0001F9FE", "money, payments, bills or receipts", "default"),
    ("Work & Research", "\U0001F4BC", "work or research, such as meeting notes or research questions", "default"),
    ("Personal & Notes", "\U0001F4D3", "personal life, feelings or a diary", "default"),
    ("Screenshots & Media", "\U0001F5BC\uFE0F", "screenshots, images, photos, audio recordings and media", "default"),
    (UNSORTED, "\U0001F4E5", "Files that match no folder", "smart"),
    (SENSITIVE, "\U0001F512", "Files with personal data, computed from the privacy scan", "smart"),
]
OLD_SEED_DESCRIPTIONS = {  # Phase 1 text, replaced on start only if the user did not change it
    "Finance & Receipts": "invoices, receipts, bills, payments and money spent",
    "Work & Research": "work documents, meeting notes, projects and research",
    "Personal & Notes": "personal journal, diary, feelings and private notes",
}

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


def migrate(conn: sqlite3.Connection) -> None:
    """Add columns that older DBs lack. Safe to run on every start."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(files)")}
    if "vec" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN vec BLOB")  # float32 potion vector, 256 * 4 bytes
    if "cls_ver" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN cls_ver TEXT")  # classifier version that wrote the links
    if "ext_ver" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN ext_ver TEXT")  # extractor version (OCR) that read the file
    if "server_pii" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN server_pii TEXT")  # JSON list from extractors.detect_pii
    conn.commit()
    backfill_server_pii(conn)


def backfill_server_pii(conn: sqlite3.Connection) -> int:
    """Rows indexed before the server-side check: run it on the stored text (a regex, fast)."""
    from .extractors import detect_pii
    rows = conn.execute("SELECT id, title, summary, keywords, text_excerpt FROM files WHERE server_pii IS NULL").fetchall()
    for r in rows:
        kws = " ".join(json.loads(r["keywords"] or "[]"))
        found = detect_pii("\n".join([r["text_excerpt"] or "", r["title"] or "", r["summary"] or "", kws]))
        conn.execute("UPDATE files SET server_pii=? WHERE id=?", (json.dumps(found), r["id"]))
    conn.commit()
    return len(rows)


# A file is personal (the Sensitive (PII) folder) when the browser's Redact model or the
# server-side check found personal data. The browser can add to this, never take it away.
PII_SQL = ("(json_extract({t}client_meta, '$.has_pii') = 1 "
           "OR ({t}server_pii IS NOT NULL AND {t}server_pii != '[]'))")


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    migrate(conn)
    for name, emoji, desc, kind in SEED_FOLDERS:
        conn.execute(
            "INSERT OR IGNORE INTO virtual_folders(name, emoji, description, kind) VALUES (?,?,?,?)",
            (name, emoji, desc, kind))
    for name, old in OLD_SEED_DESCRIPTIONS.items():  # Step 3 re-tuned these for DeBERTa; keep user edits
        new = next(d for n, _, d, _ in SEED_FOLDERS if n == name)
        conn.execute("UPDATE virtual_folders SET description=? WHERE name=? AND description=?", (new, name, old))
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
            "text_excerpt", "ai_status", "ai_error", "indexed_at", "ext_ver", "server_pii")
    vals = [rec.get(c) for c in cols]
    if "server_pii" in rec:
        vals[cols.index("server_pii")] = json.dumps(rec["server_pii"] or [])
    if row:
        fid = row["id"]
        conn.execute(
            "UPDATE files SET " + ", ".join(f"{c}=?" for c in cols) + ", keywords=?, vec=NULL WHERE id=?",
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


def clear_index(conn: sqlite3.Connection) -> int:
    """Forget every indexed file: rows, folder links, search text, vectors and the scan root.
    Folders stay. The FTS table is dropped and rebuilt and the file is vacuumed, so the old text
    is not left behind in free pages or the WAL. Returns how many files were removed."""
    n = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.execute("DELETE FROM file_folder_links")
    conn.execute("DELETE FROM files")
    conn.execute("DROP TABLE IF EXISTS files_fts")
    conn.execute("DELETE FROM app_meta WHERE key='scan_root'")
    conn.commit()
    conn.executescript(SCHEMA)          # recreates files_fts, empty
    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return n


# ---- API views ------------------------------------------------------------------

def file_cards(conn: sqlite3.Connection, rows, full: bool = False) -> list[dict]:
    """Rows of `files` -> JSON-ready dicts with folder links. `full` adds the excerpt and the
    browser's redacted excerpt (lists leave both out: they are the bulk of the payload)."""
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
        meta = json.loads(r["client_meta"] or "{}")
        if not full:
            meta.pop("redacted_excerpt", None)
        server_pii = r["server_pii"] if "server_pii" in r.keys() else None
        d = {"id": r["id"], "path": r["path"], "name": r["name"], "ext": r["ext"], "kind": r["kind"],
             "size": r["size"], "mtime": r["mtime"], "title": r["title"], "summary": r["summary"],
             "keywords": json.loads(r["keywords"] or "[]"), "ai_status": r["ai_status"],
             "ai_error": r["ai_error"], "sha256": r["sha256"], "client_meta": meta,
             "server_pii": json.loads(server_pii or "[]"),
             "indexed_at": r["indexed_at"], "folders": links[r["id"]]}
        if full:
            d["text_excerpt"] = r["text_excerpt"]
        out.append(d)
    return out
