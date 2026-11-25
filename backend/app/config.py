"""Paths, thresholds and limits. Everything is env-overridable and read at call time.

`get_settings()` is cheap and re-reads the environment on every call, so tests can
monkeypatch env vars. `apply_env()` must run before anything imports `cactus` or
`gliclass` (both are imported lazily, inside functions, for that reason).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent

ALLOWED_ORIGINS = [
    "http://127.0.0.1:5173", "http://localhost:5173",
    "http://127.0.0.1:4173", "http://localhost:4173",
    "http://tauri.localhost", "tauri://localhost",  # the Tauri desktop shell (Windows, other OS)
]
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

GLICLASS_MODEL_ID = "knowledgator/gliclass-v4-edge"
SUPPORTED_EXTS = {".txt": "text", ".md": "text", ".pdf": "pdf", ".png": "image",
                  ".jpg": "image", ".jpeg": "image", ".wav": "audio"}
SKIP_DIR_NAMES = {"node_modules", ".git"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    classify_threshold: float
    max_file_bytes: int
    pdf_max_pages: int
    gliclass_dtype: str
    torch_threads: int
    search_lock_wait_s: float      # how long /search waits for the model lock
    model_timeout_s: float         # soft timeout (measured, cannot interrupt)
    excerpt_chars: int
    allow_download: bool


def get_settings() -> Settings:
    data_dir = Path(os.environ.get("VEILFS_DATA_DIR") or BACKEND_DIR / "data").resolve()
    db_path = Path(os.environ.get("VEILFS_DB_PATH") or data_dir / "veilfs.db").resolve()
    return Settings(
        data_dir=data_dir,
        db_path=db_path,
        classify_threshold=_float("CLASSIFY_THRESHOLD", 0.5),
        max_file_bytes=_int("MAX_FILE_MB", 25) * 1024 * 1024,
        pdf_max_pages=_int("PDF_MAX_PAGES", 10),
        gliclass_dtype=os.environ.get("GLICLASS_DTYPE", "float32"),
        torch_threads=_int("TORCH_THREADS", max(1, (os.cpu_count() or 2) // 2)),
        search_lock_wait_s=_float("SEARCH_LOCK_WAIT_S", 5.0),
        model_timeout_s=_float("MODEL_TIMEOUT_S", 60.0),
        excerpt_chars=_int("EXCERPT_CHARS", 2000),
        allow_download=False,
    )


def apply_env(allow_download: bool = False) -> None:
    """Force the privacy and cache variables. Call before importing cactus or gliclass.

    Values are assigned (not setdefault) so a shell with HF_HUB_OFFLINE=0 cannot undo them.
    Only scripts/download_models.py passes allow_download=True.
    """
    data = get_settings().data_dir
    data.mkdir(parents=True, exist_ok=True)
    os.environ["CACTUS_TELEMETRY"] = "0"
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["XDG_CACHE_HOME"] = str(data / "cache")
    os.environ["HF_HOME"] = str(data / "hf")
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["HF_HUB_VERBOSITY"] = "error"
    os.environ["TRANSFORMERS_VERBOSITY"] = "error"
    if allow_download:
        os.environ.pop("HF_HUB_OFFLINE", None)
    else:
        os.environ["HF_HUB_OFFLINE"] = "1"


def is_inside(child: Path, parent: Path) -> bool:
    """True if child equals parent or lies under it (case-insensitive on Windows)."""
    c, p = os.path.normcase(str(child.resolve())), os.path.normcase(str(parent.resolve()))
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)
