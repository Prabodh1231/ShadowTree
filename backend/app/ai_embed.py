"""Text embeddings: potion-base-8M through model2vec (docs/api_notes.md, "ShadowTree model stack").

Loaded once, lazily, from the local folder backend/data/models/potion-base-8M, under the
shared model lock. A missing folder or a load failure raises NotReady (cached, not retried
for every file). Callers fall back: no vector stored, BM25 + recency search.
Tests monkeypatch `embed` by name (see tests/conftest.py).
"""
from __future__ import annotations

import json

import numpy as np

from .ai_classify import Busy, NotReady
from .ai_cactus import MODEL_LOCK
from .config import apply_env, get_settings, model_dir

DIM = 256
PASSAGE_CHARS = 300
_state: dict = {"model": None, "error": None}


def passage_text(title: str, summary: str, keywords: list[str] | str, excerpt: str) -> str:
    """The one text used for both the stored vector and the FlashRank passage:
    title + summary + keywords + the first 300 characters of the text."""
    if isinstance(keywords, str):
        keywords = json.loads(keywords or "[]")
    return f"{title or ''}. {summary or ''} Keywords: {', '.join(keywords)}. {(excerpt or '')[:PASSAGE_CHARS]}".strip()


def _load():
    """Call with MODEL_LOCK held."""
    if _state["model"] is not None:
        return _state["model"]
    if _state["error"]:
        raise NotReady(_state["error"])
    d = model_dir("potion-base-8M")
    if not (d / "model.safetensors").is_file():
        raise NotReady("potion is not downloaded: run scripts/download_models.py")  # not cached: may appear later
    apply_env()
    try:
        from model2vec import StaticModel
        _state["model"] = StaticModel.from_pretrained(d)
    except Exception as exc:
        _state["error"] = f"potion failed to load: {type(exc).__name__}: {exc}"
        raise NotReady(_state["error"]) from exc
    return _state["model"]


def close() -> None:
    _state["model"] = None


def embed(texts: list[str], wait: float | None = None) -> np.ndarray:
    """(n, 256) float32, each row unit length (so cosine is a dot product).
    `wait` is how long to wait for the model lock (None: block)."""
    if wait is None:
        MODEL_LOCK.acquire()
    elif not MODEL_LOCK.acquire(timeout=wait):
        raise Busy("models are busy")
    try:
        v = np.asarray(_load().encode(list(texts)), dtype=np.float32)
    finally:
        MODEL_LOCK.release()
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.maximum(n, 1e-9)


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)
