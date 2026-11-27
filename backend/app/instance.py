"""One backend per data folder.

Two backends on the same SQLite index would each run their own scan jobs and load every model
twice. The backend takes an exclusive lock on `<data dir>/backend.lock` at startup and holds it
until it stops. Windows releases the lock when the process dies, so a crashed backend never
blocks the next start.
"""
from __future__ import annotations

import os
from pathlib import Path


class AlreadyRunning(RuntimeError):
    """Another backend holds the lock on this data folder."""


_held: dict = {"fh": None}


def acquire(data_dir: Path) -> None:
    if _held["fh"] is not None:
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    fh = open(data_dir / "backend.lock", "a+b")   # app data only, never the scanned folder
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        fh.close()
        raise AlreadyRunning(
            f"Another ShadowTree backend is already running on {data_dir}. Close it (or the other "
            "ShadowTree window) and start again.") from exc
    _held["fh"] = fh


def release() -> None:
    fh = _held["fh"]
    if fh is None:
        return
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    fh.close()
    _held["fh"] = None
