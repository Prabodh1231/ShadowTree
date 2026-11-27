"""Read-only folder walk, hashing and change detection.

Nothing here writes inside the scanned root. Files are opened with open(path, "rb") only.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat as stat_mod
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from . import ai_cactus, ai_classify, ai_embed, db, vectors
from .config import CLASSIFIER_VERSION, SKIP_DIR_NAMES, SUPPORTED_EXTS, get_settings, is_inside

_HIDDEN = getattr(stat_mod, "FILE_ATTRIBUTE_HIDDEN", 0x2)
_SYSTEM = getattr(stat_mod, "FILE_ATTRIBUTE_SYSTEM", 0x4)
_REPARSE = getattr(stat_mod, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
# Reading a cloud-only file would trigger a download: RECALL_ON_DATA_ACCESS | OFFLINE. Hydrated files stay in.
_CLOUD_ONLY = 0x400000 | 0x1000
MEDIA_KINDS = ("image", "audio")  # these always join Screenshots & Media
SKIP_KEYS = ("skipped_too_large", "skipped_cloud_only", "skipped_hidden_or_link")
MAX_ERRORS = 100  # /scan/status sends the list on every poll; a scan of C:\Users can hit thousands
MORE_ERRORS = "more errors were not listed"


def add_error(errors: list[str], msg: str) -> None:
    """Keep the first MAX_ERRORS messages and one closing line; drop the rest."""
    if len(errors) < MAX_ERRORS:
        errors.append(msg)
    elif len(errors) == MAX_ERRORS:
        errors.append(MORE_ERRORS)


def _skip_attrs(st: os.stat_result) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & (_HIDDEN | _SYSTEM | _REPARSE))


def walk(root: Path, data_dir: Path, errors: list[str],
         unreadable: list[Path] | None = None,
         skips: dict | None = None) -> Iterator[tuple[Path, os.stat_result]]:
    """Yield (path, stat) for supported files. Skips hidden/system items, reparse points
    and junctions, node_modules, .git, files over the size limit and the app data dir.
    Paths that failed to list or stat are appended to `unreadable` (their content is unknown)."""
    if unreadable is None:
        unreadable = []
    if skips is None:
        skips = {}
    for k in SKIP_KEYS:
        skips.setdefault(k, 0)
    max_bytes = get_settings().max_file_bytes
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name.lower())
        except OSError as exc:
            add_error(errors, f"{d}: cannot list folder: {exc}")
            unreadable.append(d)
            continue
        for e in entries:
            p = Path(e.path)
            try:
                st = e.stat(follow_symlinks=False)
                is_dir = e.is_dir(follow_symlinks=False)
                counts = is_dir or p.suffix.lower() in SUPPORTED_EXTS  # only count what we would have indexed
                if not is_dir and getattr(st, "st_file_attributes", 0) & _CLOUD_ONLY:
                    if counts:
                        skips["skipped_cloud_only"] += 1
                    continue
                if e.is_symlink() or _skip_attrs(st):
                    if counts:
                        skips["skipped_hidden_or_link"] += 1
                    continue
                if is_dir:
                    if e.name.lower() in SKIP_DIR_NAMES or is_inside(p, data_dir):
                        continue
                    stack.append(p)
                elif e.is_file(follow_symlinks=False):
                    if p.suffix.lower() not in SUPPORTED_EXTS:
                        continue
                    if st.st_size > max_bytes:
                        skips["skipped_too_large"] += 1
                        continue
                    yield p, st
            except OSError as exc:
                add_error(errors, f"{p}: {exc}")
                unreadable.append(p)  # stat/is_dir failed: its rows (or the rows under it) must stay


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def needs_reread(row) -> bool:
    """Images, and PDFs with almost no text, read before OCR existed (no ext_ver stamp).
    Re-reading runs the whole card again, so Mirage runs again for those images."""
    if row["ext_ver"] == ai_cactus.EXTRACT_VERSION:
        return False
    if row["kind"] == "image":
        return True
    return row["kind"] == "pdf" and len((row["text_excerpt"] or "").strip()) < ai_cactus.OCR_PDF_MIN_CHARS + 20


def classify_file(conn, file_id: int, folders: list, rec: dict) -> str:
    """Link the file to every topic folder scoring >= threshold. If none does and the file has no type link,
    link its single best topic folder when that score >= soft_floor (a best guess); else Unsorted.
    Screenshots & Media is decided by file type (image or audio), not by the classifier.
    Returns an error note ('' when fine) and stamps files.cls_ver on success. Never raises."""
    cfg = get_settings()
    thr, soft = cfg.classify_threshold, cfg.soft_floor
    unsorted = db.folder_id(db.UNSORTED)
    media = db.folder_id(db.MEDIA)
    links: list[tuple[int, float]] = []
    note = ""
    topics = [f for f in folders if f[0] != media]
    if topics:
        labels = ai_classify.unique_labels(topics)
        text = ai_classify.classifier_text(rec["title"], rec["summary"], rec["keywords"], rec["text_excerpt"])
        try:
            scores = ai_classify.classify(text, [l for _, l in labels])
            links = [(fid, s) for (fid, _), s in zip(labels, scores) if s >= thr]
            if not links and len(scores) and rec.get("kind") not in MEDIA_KINDS:
                best = max(range(len(scores)), key=lambda i: scores[i])  # best guess, real score kept
                if scores[best] >= soft:
                    links = [(labels[best][0], float(scores[best]))]
        except Exception as exc:
            note = f"{type(exc).__name__}: {exc}"
    if rec.get("kind") in MEDIA_KINDS:
        links.append((media, 1.0))
    if not links:
        links = [(unsorted, 0.0)]
    conn.execute("DELETE FROM file_folder_links WHERE file_id=?", (file_id,))
    conn.executemany("INSERT INTO file_folder_links(file_id, folder_id, score) VALUES (?,?,?)",
                     [(file_id, f, s) for f, s in links])
    conn.execute("UPDATE files SET cls_ver=? WHERE id=?", (None if note else CLASSIFIER_VERSION, file_id))
    conn.commit()
    return note


def relink_stale(conn, folders: list, progress: Callable[..., None], errors: list[str],
                 should_stop: Callable[[], bool] = lambda: False) -> int:
    """Re-link files whose links came from an older classifier (e.g. GLiClass), using the stored
    text only: no hashing, no Cactus. If the classifier is not ready the old links are kept."""
    rows = conn.execute("SELECT * FROM files WHERE cls_ver IS NOT ? ORDER BY id", (CLASSIFIER_VERSION,)).fetchall()
    done = 0
    for r in rows:
        if should_stop():
            break
        rec = {"title": r["title"] or "", "summary": r["summary"] or "", "keywords": json.loads(r["keywords"] or "[]"),
               "text_excerpt": r["text_excerpt"] or "", "kind": r["kind"]}
        progress(current_file=r["name"])
        saved = conn.execute("SELECT folder_id, score FROM file_folder_links WHERE file_id=?", (r["id"],)).fetchall()
        note = classify_file(conn, r["id"], folders, rec)
        if note:  # classifier unavailable: put the old links back and try again on the next scan
            conn.execute("DELETE FROM file_folder_links WHERE file_id=?", (r["id"],))
            conn.executemany("INSERT INTO file_folder_links(file_id, folder_id, score) VALUES (?,?,?)",
                             [(r["id"], s["folder_id"], s["score"]) for s in saved])
            conn.commit()
            if len(errors) < 20:
                errors.append(f"file {r['id']}: re-link skipped: {note}")
            break  # the same error would repeat for every file
        done += 1
    return done


def classifiable_folders(conn) -> list[tuple[int, str, str | None]]:
    rows = conn.execute("SELECT id, name, description FROM virtual_folders WHERE kind!='smart' ORDER BY id")
    return [(r["id"], r["name"], r["description"]) for r in rows]


def set_classify_note(conn, file_id: int, note: str) -> None:
    row = conn.execute("SELECT ai_error FROM files WHERE id=?", (file_id,)).fetchone()
    cur = row["ai_error"] or ""
    cur = cur.split(" [classify:")[0]
    if note:
        cur += f" [classify: {ai_cactus.one_line(note, 60)}]"
    conn.execute("UPDATE files SET ai_error=? WHERE id=?", (ai_cactus.clip_error(cur, 200), file_id))
    conn.commit()


def scan(root: Path, progress: Callable[..., None], errors: list[str],
         should_stop: Callable[[], bool] = lambda: False) -> dict:
    """Index `root`. Skips unchanged files without hashing; removes rows (only) for
    files that no longer exist under root."""
    cfg = get_settings()
    conn = db.get_conn()
    root = root.resolve()
    unreadable: list[Path] = []
    skips: dict = {}
    found = list(walk(root, cfg.data_dir, errors, unreadable, skips))
    progress(total=len(found), processed=0)
    seen: set[str] = set()
    stats = {"new": 0, "changed": 0, "skipped": 0, "removed": 0, **skips}
    folders = classifiable_folders(conn)

    for i, (p, st) in enumerate(found, 1):
        if should_stop():
            break
        path_s = str(p.resolve())
        seen.add(os.path.normcase(path_s))
        progress(current_file=p.name)
        try:
            row = conn.execute("SELECT id, size, mtime, sha256, kind, ext_ver, text_excerpt FROM files WHERE path=?",
                               (path_s,)).fetchone()
            if row and needs_reread(row):  # read before OCR existed: index again (Cactus runs again)
                row_unchanged = False
            else:
                row_unchanged = bool(row) and row["size"] == st.st_size and row["mtime"] == st.st_mtime
            if row_unchanged:
                stats["skipped"] += 1
            else:
                digest = sha256_file(p)
                if row and row["sha256"] == digest and not needs_reread(row):
                    conn.execute("UPDATE files SET size=?, mtime=? WHERE id=?", (st.st_size, st.st_mtime, row["id"]))
                    conn.commit()
                    stats["skipped"] += 1
                else:
                    kind = SUPPORTED_EXTS[p.suffix.lower()]
                    card = ai_cactus.build_card(p, kind, p.name)
                    rec = {**card, "path": path_s, "name": p.name, "ext": p.suffix.lower(), "kind": kind,
                           "size": st.st_size, "mtime": st.st_mtime, "sha256": digest, "indexed_at": _now(),
                           "ext_ver": card.get("ext_ver", ai_cactus.EXTRACT_VERSION)}
                    fid = db.upsert_file(conn, rec)
                    if row and row["sha256"] != digest:  # content changed: the browser-side privacy scan is stale
                        conn.execute("UPDATE files SET client_meta='{}' WHERE id=?", (fid,))
                        conn.commit()
                    note = classify_file(conn, fid, folders, rec)
                    if note:
                        set_classify_note(conn, fid, note)
                    try:
                        vectors.embed_rows(conn, [fid])
                    except Exception:  # model missing or busy: embed_missing retries after the scan
                        pass
                    stats["changed" if row else "new"] += 1
        except OSError as exc:  # locked file, permission denied, vanished mid-scan
            add_error(errors, f"{p}: {type(exc).__name__}: {exc}")
        except Exception as exc:
            add_error(errors, f"{p}: unexpected {type(exc).__name__}: {exc}")
        progress(processed=i)

    if not should_stop():
        relink_stale(conn, folders, progress, errors, should_stop)  # links from an older classifier
        vectors.embed_missing(conn)  # rows still without a vector (old DBs, failed embeds)
        for r in conn.execute("SELECT id, path FROM files").fetchall():
            n = os.path.normcase(r["path"])
            if any(is_inside(Path(r["path"]), u) for u in unreadable):
                continue  # its folder could not be read this time: keep the row (N3)
            if is_inside(Path(r["path"]), root) and n not in seen:
                db.delete_file(conn, r["id"])  # DB rows only, never the disk
                stats["removed"] += 1
    return stats


def link_new_folders(folder_ids: list[int], progress: Callable[..., None], errors: list[str],
                     should_stop: Callable[[], bool] = lambda: False) -> dict:
    """Add links for newly created folders only (L4). Pre-filter: embed name + description with
    potion and keep files whose stored vector has cosine >= NEWFOLDER_COSINE (files without a
    vector, or no potion at all, skip the pre-filter). Only those files are scored by DeBERTa,
    against the new folders' hypotheses; the new links are written, a file that gains a link
    loses its Unsorted link, and every other link stays. Never runs Cactus."""
    conn = db.get_conn()
    cfg = get_settings()
    thr = cfg.classify_threshold
    unsorted = db.folder_id(db.UNSORTED)
    media = db.folder_id(db.MEDIA)
    marks = ",".join("?" * len(folder_ids))
    new = [(r["id"], r["name"], r["description"]) for r in conn.execute(
        f"SELECT id, name, description FROM virtual_folders WHERE id IN ({marks}) AND kind!='smart'", folder_ids)
        if r["id"] != media]
    labels = ai_classify.unique_labels(new)
    rows = conn.execute("SELECT id, title, summary, keywords, text_excerpt, vec FROM files ORDER BY id").fetchall()
    progress(total=len(rows), processed=0)
    cos: dict[int, np.ndarray] = {}
    try:  # one potion vector per new folder: name + description
        fv = ai_embed.embed([f"{n}. {d or ''}".strip() for _, n, d in new], wait=5.0)
        cos = {fid: fv[k] for k, (fid, _, _) in enumerate(new)}
    except Exception:
        cos = {}
    added = 0
    for i, r in enumerate(rows, 1):
        if should_stop():
            break
        progress(current_file=r["title"])
        todo = labels
        if cos and r["vec"] is not None:
            v = ai_embed.from_blob(r["vec"])
            todo = [(fid, l) for fid, l in labels if float(v @ cos[fid]) >= cfg.newfolder_cosine]
        note = ""
        if todo:
            text = ai_classify.classifier_text(r["title"] or "", r["summary"] or "",
                                               json.loads(r["keywords"] or "[]"), r["text_excerpt"] or "")
            try:
                scores = ai_classify.classify(text, [l for _, l in todo])
                gained = [(fid, s) for (fid, _), s in zip(todo, scores) if s >= thr]
                if gained:
                    conn.executemany("INSERT OR REPLACE INTO file_folder_links(file_id, folder_id, score) VALUES (?,?,?)",
                                     [(r["id"], f, s) for f, s in gained])
                    conn.execute("DELETE FROM file_folder_links WHERE file_id=? AND folder_id=?", (r["id"], unsorted))
                    conn.commit()
                    added += len(gained)
            except Exception as exc:
                note = f"{type(exc).__name__}: {exc}"
                if len(errors) < 20:
                    errors.append(f"file {r['id']}: classify: {note}")
            set_classify_note(conn, r["id"], note)
        progress(processed=i)
    return {"reclassified": len(rows), "links_added": added, **dict.fromkeys(SKIP_KEYS, 0)}
