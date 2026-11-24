"""One background job thread: scan or link-new-folders, with a status snapshot.

POST /scan is rejected while a job runs. A "link new folder" request that arrives while a
job runs is queued and runs right after it (several queued folders share one job).
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import db, scanner


class JobRunning(Exception):
    pass


_lock = threading.Lock()
_idle = threading.Event()
_idle.set()
_status: dict = {"state": "idle", "job_id": None, "kind": None, "processed": 0, "total": 0,
                 "current_file": None, "errors": [], "stats": None, "queued_job_id": None}
_next_id = 0
_pending: list[int] | None = None   # folder ids waiting for the next reclassify job


def status() -> dict:
    with _lock:
        s = dict(_status)
        s["errors"] = list(_status["errors"])
        return s


def is_running() -> bool:
    return not _idle.is_set()


def wait_idle(timeout: float = 60.0) -> bool:
    return _idle.wait(timeout)


def _progress(**kw) -> None:
    with _lock:
        _status.update(kw)


def _new_job(kind: str) -> int:
    global _next_id
    _next_id += 1
    _status.update(state="running", job_id=_next_id, kind=kind, processed=0, total=0,
                   current_file=None, errors=[], stats=None)
    return _next_id


def _run(kind: str, arg) -> None:
    global _pending
    try:
        while True:
            errors: list[str] = _status["errors"]
            try:
                if kind == "scan":
                    stats = scanner.scan(arg, _progress, errors)
                else:
                    stats = scanner.link_new_folders(arg, _progress, errors)
                _progress(state="done", stats=stats, current_file=None)
            except Exception as exc:
                errors.append(f"job failed: {type(exc).__name__}: {exc}")
                _progress(state="error", current_file=None)
            with _lock:
                nxt, _pending = _pending, None
                if nxt is None:
                    _status["queued_job_id"] = None
                    break
                _new_job("reclassify")
                _status["queued_job_id"] = None
            kind, arg = "reclassify", nxt
    finally:
        db.close_thread_conns()
        _idle.set()


def _start(kind: str, arg) -> int:
    _idle.clear()
    jid = _new_job(kind)
    threading.Thread(target=_run, args=(kind, arg), name="veilfs-job", daemon=True).start()
    return jid


def start_scan(root: Path) -> int:
    with _lock:
        if is_running():
            raise JobRunning("a job is already running")
        return _start("scan", root)


def start_reclassify(folder_id: int) -> tuple[int, str]:
    """Link the new folder `folder_id` now, or queue it after the running job.
    Returns (job_id, "started" | "queued")."""
    global _next_id, _pending
    with _lock:
        if not is_running():
            return _start("reclassify", [folder_id]), "started"
        if _pending is None:
            _pending = [folder_id]
            _status["queued_job_id"] = _next_id + 1  # id it will get when it starts
        elif folder_id not in _pending:
            _pending.append(folder_id)
        return _status["queued_job_id"], "queued"
