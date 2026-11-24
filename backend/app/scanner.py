"""Read-only folder walk, hashing and change detection.

Nothing here writes inside the scanned root. Files are opened with open(path, "rb") only.
"""
from __future__ import annotations

import hashlib
import os
import stat as stat_mod
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from . import ai_cactus, ai_classify, db
from .config import SKIP_DIR_NAMES, SUPPORTED_EXTS, get_settings, is_inside

_HIDDEN = getattr(stat_mod, "FILE_ATTRIBUTE_HIDDEN", 0x2)
_SYSTEM = getattr(stat_mod, "FILE_ATTRIBUTE_SYSTEM", 0x4)
_REPARSE = getattr(stat_mod, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _skip_attrs(st: os.stat_result) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & (_HIDDEN | _SYSTEM | _REPARSE))


def walk(root: Path, data_dir: Path, errors: list[str]) -> Iterator[tuple[Path, os.stat_result]]:
    """Yield (path, stat) for supported files. Skips hidden/system items, reparse points
    and junctions, node_modules, .git, files over the size limit and the app data dir."""
    max_bytes = get_settings().max_file_bytes
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name.lower())
        except OSError as exc:
            errors.append(f"{d}: cannot list folder: {exc}")
            continue
        for e in entries:
            p = Path(e.path)
            try:
                st = e.stat(follow_symlinks=False)
                if e.is_symlink() or _skip_attrs(st):
                    continue
                if e.is_dir(follow_symlinks=False):
                    if e.name.lower() in SKIP_DIR_NAMES or is_inside(p, data_dir):
                        continue
                    stack.append(p)
                elif e.is_file(follow_symlinks=False):
                    if p.suffix.lower() not in SUPPORTED_EXTS or st.st_size > max_bytes:
                        continue
                    yield p, st
            except OSError as exc:
                errors.append(f"{p}: {exc}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def classify_file(conn, file_id: int, folders: list, rec: dict) -> str:
    """Link the file to every folder scoring >= threshold, else Unsorted.
    Returns an error note ('' when fine). Never raises."""
    thr = get_settings().classify_threshold
    unsorted = db.folder_id(db.UNSORTED)
    links: list[tuple[int, float]] = []
    note = ""
    if folders:
        labels = ai_classify.unique_labels(folders)
        text = ai_classify.classifier_text(rec["title"], rec["summary"], rec["keywords"], rec["text_excerpt"])
        try:
            scores = ai_classify.classify(text, [l for _, l in labels])
            links = [(fid, s) for (fid, _), s in zip(labels, scores) if s >= thr]
        except Exception as exc:
            note = f"{type(exc).__name__}: {exc}"
    if not links:
        links = [(unsorted, 0.0)]
    conn.execute("DELETE FROM file_folder_links WHERE file_id=?", (file_id,))
    conn.executemany("INSERT INTO file_folder_links(file_id, folder_id, score) VALUES (?,?,?)",
                     [(file_id, f, s) for f, s in links])
    conn.commit()
    return note


def classifiable_folders(conn) -> list[tuple[int, str, str | None]]:
    rows = conn.execute("SELECT id, name, description FROM virtual_folders WHERE kind!='smart' ORDER BY id")
    return [(r["id"], r["name"], r["description"]) for r in rows]


def set_classify_note(conn, file_id: int, note: str) -> None:
    row = conn.execute("SELECT ai_error FROM files WHERE id=?", (file_id,)).fetchone()
    cur = row["ai_error"] or ""
    cur = cur.split(" [classify:")[0]
    if note:
        cur += f" [classify: {note}]"
    conn.execute("UPDATE files SET ai_error=? WHERE id=?", (cur, file_id))
    conn.commit()


def scan(root: Path, progress: Callable[..., None], errors: list[str],
         should_stop: Callable[[], bool] = lambda: False) -> dict:
    """Index `root`. Skips unchanged files without hashing; removes rows (only) for
    files that no longer exist under root."""
    cfg = get_settings()
    conn = db.get_conn()
    root = root.resolve()
    found = list(walk(root, cfg.data_dir, errors))
    progress(total=len(found), processed=0)
    seen: set[str] = set()
    stats = {"new": 0, "changed": 0, "skipped": 0, "removed": 0}
    folders = classifiable_folders(conn)

    for i, (p, st) in enumerate(found, 1):
        if should_stop():
            break
        path_s = str(p.resolve())
        seen.add(os.path.normcase(path_s))
        progress(current_file=p.name)
        try:
            row = conn.execute("SELECT id, size, mtime, sha256 FROM files WHERE path=?", (path_s,)).fetchone()
            if row and row["size"] == st.st_size and row["mtime"] == st.st_mtime:
                stats["skipped"] += 1
            else:
                digest = sha256_file(p)
                if row and row["sha256"] == digest:
                    conn.execute("UPDATE files SET size=?, mtime=? WHERE id=?", (st.st_size, st.st_mtime, row["id"]))
                    conn.commit()
                    stats["skipped"] += 1
                else:
                    kind = SUPPORTED_EXTS[p.suffix.lower()]
                    card = ai_cactus.build_card(p, kind, p.name)
                    rec = {**card, "path": path_s, "name": p.name, "ext": p.suffix.lower(), "kind": kind,
                           "size": st.st_size, "mtime": st.st_mtime, "sha256": digest, "indexed_at": _now()}
                    fid = db.upsert_file(conn, rec)
                    if row:  # content changed: the browser-side privacy scan is stale
                        conn.execute("UPDATE files SET client_meta='{}' WHERE id=?", (fid,))
                        conn.commit()
                    note = classify_file(conn, fid, folders, rec)
                    if note:
                        set_classify_note(conn, fid, note)
                    stats["changed" if row else "new"] += 1
        except OSError as exc:  # locked file, permission denied, vanished mid-scan
            errors.append(f"{p}: {type(exc).__name__}: {exc}")
        except Exception as exc:
            errors.append(f"{p}: unexpected {type(exc).__name__}: {exc}")
        progress(processed=i)

    if not should_stop():
        for r in conn.execute("SELECT id, path FROM files").fetchall():
            n = os.path.normcase(r["path"])
            if is_inside(Path(r["path"]), root) and n not in seen:
                db.delete_file(conn, r["id"])  # DB rows only, never the disk
                stats["removed"] += 1
    return stats


def reclassify_all(progress: Callable[..., None], errors: list[str],
                   should_stop: Callable[[], bool] = lambda: False) -> dict:
    """Re-link every file from stored title/summary/keywords/excerpt. Never runs Cactus."""
    conn = db.get_conn()
    folders = classifiable_folders(conn)
    rows = conn.execute("SELECT id, title, summary, keywords, text_excerpt FROM files ORDER BY id").fetchall()
    progress(total=len(rows), processed=0)
    import json
    for i, r in enumerate(rows, 1):
        if should_stop():
            break
        progress(current_file=r["title"])
        rec = {"title": r["title"] or "", "summary": r["summary"] or "",
               "keywords": json.loads(r["keywords"] or "[]"), "text_excerpt": r["text_excerpt"] or ""}
        note = classify_file(conn, r["id"], folders, rec)
        set_classify_note(conn, r["id"], note)
        if note and len(errors) < 20:
            errors.append(f"file {r['id']}: classify: {note}")
        progress(processed=i)
    return {"reclassified": len(rows)}
