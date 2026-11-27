"""ShadowTree FastAPI app. Binds to 127.0.0.1 only (see docs/review/phase-1.md for the run command)."""
from __future__ import annotations

import hmac
import json
import logging
import os
import sqlite3
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware

from . import (ai_cactus, ai_classify, ai_embed, db, extractors, instance, jobs, picker,
               search as search_mod, vectors)
from .config import (ALLOWED_HOSTS, ALLOWED_ORIGINS, SUPPORTED_EXTS, api_token, apply_env, get_settings,
                     is_inside, token_from_env)
from .previews import PreviewCache

apply_env()  # before anything can import cactus or a model package (they are imported lazily)
log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    apply_env()
    instance.acquire(get_settings().data_dir)  # one backend per data folder; raises AlreadyRunning
    try:
        db.init_db()
        vectors.start_backfill()  # background: embed rows that have no vector yet (old DBs)
        if not token_from_env():
            log.warning("Browser mode: open http://localhost:5173/#token=%s in your browser "
                        "(the link changes every time the backend starts).", api_token())
        yield
    finally:
        jobs.cancel()
        ai_cactus.close()
        ai_classify.close()
        ai_embed.close()
        instance.release()


app = FastAPI(title="ShadowTree", version="0.1.0", lifespan=lifespan)

OPEN_PATHS = {"/health"}  # the desktop shell probes this before it can talk to the backend


async def require_token(request: Request, call_next):
    """Every request but /health carries the per-launch token. Runs inside CORS, so a 401
    still has CORS headers and the page can tell "wrong token" from "backend down"."""
    if request.method == "OPTIONS" or request.url.path in OPEN_PATHS:
        return await call_next(request)
    sent = request.headers.get("authorization", "").encode()
    if not hmac.compare_digest(sent, f"Bearer {api_token()}".encode()):
        return JSONResponse({"detail": "missing or wrong access token"}, status_code=401)
    return await call_next(request)


# Added first = innermost. Order from the outside in: foreign-origin check, trusted host, CORS, token.
app.add_middleware(BaseHTTPMiddleware, dispatch=require_token)
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=False,
                   allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type", "Authorization"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.middleware("http")
async def reject_foreign_origin(request: Request, call_next):
    """CORS only hides responses. A hostile page can still send a POST, so refuse it."""
    origin = request.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        return JSONResponse({"detail": "origin not allowed"}, status_code=403)
    return await call_next(request)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScanBody(Body):
    root: str = Field(min_length=1, max_length=1024)


class FolderBody(Body):
    name: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    emoji: str | None = Field(default=None, max_length=16)


class RevealBody(Body):
    file_id: int


class ClientMetaBody(Body):
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")  # the content hash the browser scanned
    has_pii: bool
    pii_types: list[str] = Field(default_factory=list, max_length=40)
    topics: list[str] = Field(default_factory=list, max_length=40)
    redacted_excerpt: str | None = Field(default=None, max_length=5000)

    def model_post_init(self, _ctx) -> None:
        for lst in (self.pii_types, self.topics):
            if any(len(s) > 80 for s in lst):
                raise ValueError("list items must be at most 80 characters")


# ---- health -------------------------------------------------------------------------

@app.get("/health")
def health():
    """Never loads a model: flags come from memory, presence from a disk check."""
    cactus_files = ai_classify.cactus_files_present()
    present = ai_classify.model_files_present()
    fl = ai_cactus.loaded_flags()
    hint = "run scripts/download_models.py"
    return {
        "status": "ok",
        "app": "ShadowTree",  # lets the desktop shell tell this backend from another program on the port
        "cactus": {"loaded": fl["cactus"], "files_present": cactus_files,
                   "load_errors": fl["failed"],
                   "hint": None if all(cactus_files.values()) else hint},
        "classifier": {"loaded": ai_classify.is_loaded(), "files_present": present,
                       "load_error": ai_classify.load_error(),
                       "hint": None if all(present.values()) else hint},
        "job": jobs.status()["state"],
    }


# ---- scan / jobs --------------------------------------------------------------------

@app.post("/scan")
def scan(body: ScanBody):
    root = Path(body.root)
    try:
        root = root.resolve()
    except OSError:
        raise HTTPException(400, "invalid path")
    if not root.is_dir():
        raise HTTPException(400, "root is not a directory")
    if is_inside(root, get_settings().data_dir):
        raise HTTPException(400, "root must not be the app data folder or inside it")
    try:
        jid = jobs.start_scan(root)
    except jobs.JobRunning:
        raise HTTPException(409, "a job is already running")
    conn = db.get_conn()  # only after the job started: a refused scan must not change scan_root
    conn.execute("INSERT INTO app_meta(key, value) VALUES ('scan_root', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(root),))
    conn.commit()
    return {"job_id": jid}


@app.get("/scan/status")
def scan_status():
    s = jobs.status()
    return {k: s[k] for k in ("state", "job_id", "kind", "processed", "total", "current_file",
                              "errors", "stats", "queued_job_id")}


@app.post("/scan/cancel")
def scan_cancel():
    """Stop the running job after the file it is on. Files read so far stay in the index."""
    return {"cancelled": jobs.cancel()}


@app.post("/index/clear")
def clear_index():
    """Forget every indexed file (text, summaries, vectors, links). Virtual folders stay.
    Files on disk are never touched."""
    try:
        with jobs.exclusive():
            n = db.clear_index(db.get_conn())
    except jobs.JobRunning:
        raise HTTPException(409, "a job is running; stop it or wait, then clear the index")
    _previews.clear()
    return {"removed": n}


# ---- files --------------------------------------------------------------------------

def _folder_filter(conn, folder_id: int) -> tuple[str, list]:
    f = conn.execute("SELECT name, kind FROM virtual_folders WHERE id=?", (folder_id,)).fetchone()
    if not f:
        raise HTTPException(404, "folder not found")
    if f["name"] == db.SENSITIVE:  # the server-side check while indexing, or the browser privacy pass
        return db.PII_SQL.format(t="f."), []
    return "f.id IN (SELECT file_id FROM file_folder_links WHERE folder_id=?)", [folder_id]


@app.get("/files")
def list_files(folder_id: int | None = None, q: str | None = Query(default=None, max_length=200)):
    conn = db.get_conn()
    where, args = ["1=1"], []
    if folder_id is not None:
        w, a = _folder_filter(conn, folder_id)
        where.append(w)
        args += a
    if q:
        m = search_mod.build_match(q)
        if m is None:
            return []
        where.append("f.id IN (SELECT rowid FROM files_fts WHERE files_fts MATCH ?)")
        args.append(m)
    rows = conn.execute(f"SELECT f.* FROM files f WHERE {' AND '.join(where)} ORDER BY f.id", args).fetchall()
    return db.file_cards(conn, rows)


@app.get("/files/{file_id}")
def get_file(file_id: int):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
    if not row:
        raise HTTPException(404, "file not found")
    return db.file_cards(conn, [row], full=True)[0]


# Rendered previews, in memory only, bounded by bytes (PREVIEW_CACHE_MB). The disk mtime and
# size are part of the key, so an edited file renders again.
_previews = PreviewCache(get_settings().preview_cache_bytes)


@app.get("/files/{file_id}/preview")
def file_preview(file_id: int, size: int = Query(default=480, ge=64, le=1200)):
    """A PNG of an image or the first page of a PDF, rendered in memory from a read-only open."""
    row = db.get_conn().execute("SELECT path, kind FROM files WHERE id=?", (file_id,)).fetchone()
    if not row:
        raise HTTPException(404, "file not found")
    if row["kind"] not in ("image", "pdf"):
        raise HTTPException(415, "this kind of file has no visual preview")
    path = Path(row["path"])
    try:
        st = path.stat()
    except OSError:
        st = None
    if st is None or not path.is_file():
        raise HTTPException(410, "file no longer exists on disk")
    key = (str(path), row["kind"], size, st.st_mtime, st.st_size)
    png = _previews.get(key)
    if png is None:
        png = extractors.render_preview(path, row["kind"], size, limit=get_settings().max_file_bytes) or b""
        _previews.put(key, png)
    if not png:
        raise HTTPException(415, "no preview could be made for this file")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@app.patch("/files/{file_id}/client-meta")
def patch_client_meta(file_id: int, body: ClientMetaBody):
    conn = db.get_conn()
    row = conn.execute("SELECT client_meta, sha256 FROM files WHERE id=?", (file_id,)).fetchone()
    if not row:
        raise HTTPException(404, "file not found")
    if (row["sha256"] or "").lower() != body.sha256.lower():
        raise HTTPException(409, "file changed since it was scanned; reload and scan again")
    meta = json.loads(row["client_meta"] or "{}")
    meta.update(body.model_dump(exclude_none=True))
    meta["sha256"] = body.sha256.lower()
    conn.execute("UPDATE files SET client_meta=? WHERE id=?", (json.dumps(meta, ensure_ascii=False), file_id))
    conn.commit()
    return meta


# ---- folders ------------------------------------------------------------------------

@app.get("/folders")
def list_folders():
    conn = db.get_conn()
    counts = {r["folder_id"]: r["n"] for r in conn.execute(
        "SELECT folder_id, COUNT(*) AS n FROM file_folder_links GROUP BY folder_id")}
    pii = conn.execute("SELECT COUNT(*) FROM files WHERE " + db.PII_SQL.format(t="")).fetchone()[0]
    out = []
    for r in conn.execute("SELECT * FROM virtual_folders ORDER BY id"):
        n = pii if r["name"] == db.SENSITIVE else counts.get(r["id"], 0)
        out.append({"id": r["id"], "name": r["name"], "emoji": r["emoji"], "description": r["description"],
                    "kind": r["kind"], "created_at": r["created_at"], "file_count": n})
    return out


@app.post("/folders", status_code=201)
def create_folder(body: FolderBody):
    conn = db.get_conn()
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "name is empty")
    try:
        cur = conn.execute("INSERT INTO virtual_folders(name, emoji, description, kind) VALUES (?,?,?, 'custom')",
                           (name, body.emoji, (body.description or "").strip() or None))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()  # a failed INSERT leaves the implicit transaction (and write lock) open
        raise HTTPException(409, "a folder with this name already exists")
    job_id, state = jobs.start_reclassify(cur.lastrowid)
    return {"folder_id": cur.lastrowid, "job_id": job_id, "job": state}


# ---- search / reveal / export -------------------------------------------------------

@app.get("/search")
def search(q: str = Query(min_length=1, max_length=200)):
    return search_mod.search(db.get_conn(), q)


class PickBody(Body):
    initial: str | None = Field(default=None, max_length=1024)


@app.post("/pick-folder")
def pick_folder(body: PickBody):
    """Open the native Windows folder dialog. Returns {"path": str} or {"path": null} if cancelled.
    Browsers never reveal a folder's full path, so the local backend asks Windows instead."""
    try:
        return {"path": picker.pick_folder(body.initial)}
    except picker.PickerBusy:
        raise HTTPException(409, "a folder dialog is already open")


@app.get("/quick-folders")
def quick_folders():
    """The user's Documents, Desktop, Downloads and Pictures folders that exist."""
    return {"folders": picker.quick_folders()}


@app.post("/reveal")
def reveal(body: RevealBody):
    row = db.get_conn().execute("SELECT path FROM files WHERE id=?", (body.file_id,)).fetchone()
    if not row:
        raise HTTPException(404, "file not found")
    path = Path(row["path"])
    if not path.is_file():
        raise HTTPException(410, "file no longer exists on disk")
    # List of args, no shell. explorer exits 1 on success, so never check=True.
    # "/select," and the path are separate args (see phase-1.md deviation).
    subprocess.run(["explorer", "/select,", str(path)], check=False)
    return {"revealed": True}


@app.post("/open")
def open_file(body: RevealBody):
    """Open an indexed file in the app Windows has chosen for its type (a double click in Explorer).
    ShadowTree itself never writes to the file. Only the supported data types (text, PDF, picture, WAV)
    are opened, and the path always comes from the index, never from the request."""
    row = db.get_conn().execute("SELECT path FROM files WHERE id=?", (body.file_id,)).fetchone()
    if not row:
        raise HTTPException(404, "file not found")
    path = Path(row["path"])
    if path.suffix.lower() not in SUPPORTED_EXTS:
        raise HTTPException(415, "this kind of file is not opened from here")
    if not path.is_file():
        raise HTTPException(410, "file no longer exists on disk")
    startfile = getattr(os, "startfile", None)          # Windows only
    if startfile is None:
        raise HTTPException(501, "opening files is only supported on Windows")
    startfile(str(path))
    return {"opened": True}


@app.get("/export/snapshot")
def export_snapshot(relative_paths: bool = True, include_excerpt: bool = False):
    conn = db.get_conn()
    root = None
    if relative_paths:
        r = conn.execute("SELECT value FROM app_meta WHERE key='scan_root'").fetchone()
        root = r["value"] if r else None
    folders = list_folders()
    rows = conn.execute("SELECT * FROM files ORDER BY id").fetchall()
    cards = db.file_cards(conn, rows, full=include_excerpt)
    for c in cards:
        if relative_paths:
            try:
                c["path"] = Path(os.path.relpath(c["path"], root)).as_posix() if root else c["name"]
            except ValueError:
                c["path"] = c["name"]
            if c["path"].startswith(".."):
                c["path"] = c["name"]
        c.pop("sha256", None)
    links = [dict(r) for r in conn.execute("SELECT file_id, folder_id, score FROM file_folder_links")]
    return {"folders": folders, "files": cards, "links": links, "relative_paths": relative_paths}
