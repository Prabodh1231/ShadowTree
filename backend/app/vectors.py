"""Stored potion vectors (files.vec, float32 x 256). Writes only to the app DB, never to the scanned folder.

`embed_rows` is called right after a file is indexed. `embed_missing` fills every row that has
no vector (old DBs after the migration, or an embed that failed): it runs at the end of a scan
and once at startup on a background thread, never inside a request.
"""
from __future__ import annotations

import threading

from . import ai_embed, db
from .ai_classify import NotReady

BATCH = 64
_backfill_lock = threading.Lock()


def passage_of(r) -> str:
    return ai_embed.passage_text(r["title"], r["summary"], r["keywords"], r["text_excerpt"])


def embed_rows(conn, ids: list[int]) -> int:
    """Embed and store vectors for these file ids. Raises NotReady/Busy when the model cannot run."""
    done = 0
    for i in range(0, len(ids), BATCH):
        part = ids[i:i + BATCH]
        rows = conn.execute(
            "SELECT id, title, summary, keywords, text_excerpt, indexed_at FROM files WHERE id IN (%s)"
            % ",".join("?" * len(part)), part).fetchall()
        if not rows:
            continue
        vecs = ai_embed.embed([passage_of(r) for r in rows])
        for r, v in zip(rows, vecs):
            # the indexed_at guard: a row re-indexed meanwhile keeps its NULL vec for the next pass
            conn.execute("UPDATE files SET vec=? WHERE id=? AND indexed_at IS ?",
                         (ai_embed.to_blob(v), r["id"], r["indexed_at"]))
            done += 1
        conn.commit()
    return done


def embed_missing(conn) -> int:
    """Embed every row without a vector. Returns how many were stored (0 when the model is not ready)."""
    ids = [r["id"] for r in conn.execute("SELECT id FROM files WHERE vec IS NULL ORDER BY id")]
    if not ids:
        return 0
    try:
        return embed_rows(conn, ids)
    except Exception:  # NotReady, Busy or a failing model: files stay searchable by text
        return 0


def start_backfill() -> threading.Thread | None:
    """One background thread at startup. Skips if one is already running."""
    if not _backfill_lock.acquire(blocking=False):
        return None

    def run():
        try:
            embed_missing(db.get_conn())
        finally:
            db.close_thread_conns()
            _backfill_lock.release()

    t = threading.Thread(target=run, name="veilfs-embed-backfill", daemon=True)
    t.start()
    return t
