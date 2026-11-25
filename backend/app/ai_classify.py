"""Folder classification and search rerank seam (Steps 2 and 3 fill it in).

Step 1 removed GLiClass and torch. `classify` raises `NotReady` until DeBERTa (Step 3) is
wired: the scanner catches that and puts the file in Unsorted. `rerank` is FlashRank (Step 2)
and raises `NotReady` only when its model folder is missing; search then falls back to cosine
order. The names below are the seam the tests monkeypatch.
"""
from __future__ import annotations

import math

from .ai_cactus import MODEL_LOCK, ModelTimeout  # noqa: F401  (one lock for every model call)
from .config import FLASHRANK_MODEL, apply_env, get_settings, model_dir

MAX_LABELS = 25

_state: dict = {"pipe": None, "error": None}


class Busy(Exception):
    """The model lock was not free within the wait time."""


class NotReady(RuntimeError):
    """The model for this step is not wired in yet (or not downloaded)."""


def is_loaded() -> bool:
    return _state["pipe"] is not None


def load_error() -> str | None:
    return _state["error"]


def close() -> None:
    _state["pipe"] = None
    _rk["ranker"] = _rk["error"] = None


def classify(text: str, labels: list[str]) -> list[float]:
    """One score (0..1) per label. Step 3 replaces this with DeBERTa NLI."""
    raise NotReady("the folder classifier is not ready (DeBERTa arrives in Step 3)")


_rk: dict = {"ranker": None, "error": None}


def _ranker():
    """Build the FlashRank Ranker once. Call with MODEL_LOCK held. Never downloads: the
    model folder must already exist (Ranker itself would fetch a zip if it did not)."""
    if _rk["ranker"] is not None:
        return _rk["ranker"]
    if _rk["error"]:
        raise NotReady(_rk["error"])
    d = model_dir("flashrank")
    if not (d / FLASHRANK_MODEL).is_dir():
        raise NotReady("FlashRank is not downloaded: run scripts/download_models.py")  # not cached: may appear later
    apply_env()
    try:
        from flashrank import Ranker
        _rk["ranker"] = Ranker(model_name=FLASHRANK_MODEL, cache_dir=str(d), log_level="WARNING")
    except Exception as exc:
        _rk["error"] = f"FlashRank failed to load: {type(exc).__name__}: {exc}"
        raise NotReady(_rk["error"]) from exc
    return _rk["ranker"]


def rerank(query: str, passages: list[str], wait: float | None = None) -> list[float]:
    """One raw relevance logit per passage, in input order (higher = more relevant).
    FlashRank returns sigmoid(logit) as float32; the logit is recovered as log(s / (1 - s)),
    which keeps the order and does not squash everything below 0.001 to zero."""
    if wait is None:
        wait = get_settings().search_lock_wait_s
    if not MODEL_LOCK.acquire(timeout=wait):
        raise Busy("models are busy")
    try:
        rk = _ranker()  # raises NotReady first when the folder is missing, before flashrank is imported
        from flashrank import RerankRequest
        res = rk.rerank(RerankRequest(query=query, passages=[{"id": i, "text": p} for i, p in enumerate(passages)]))
    finally:
        MODEL_LOCK.release()
    out = [0.0] * len(passages)
    for r in res:
        s = min(max(float(r["score"]), 1e-30), 1.0 - 1e-7)
        out[r["id"]] = math.log(s / (1.0 - s))
    return out


def unique_labels(items: list[tuple[int, str, str | None]]) -> list[tuple[int, str]]:
    """(folder_id, name, description) -> (folder_id, unique label). Label = description or name."""
    seen: set[str] = set()
    out = []
    for fid, name, desc in items:
        base = (desc or "").strip() or name
        label, n = base, 2
        while label.lower() in seen:
            label = f"{base} ({n})"
            n += 1
        seen.add(label.lower())
        out.append((fid, label))
    return out


def classifier_text(title: str, summary: str, keywords: list[str], excerpt: str) -> str:
    return f"{title}. {summary} Keywords: {', '.join(keywords)}. {(excerpt or '')[:500]}".strip()


# ---- presence checks (disk only, never load a model) --------------------------------

def model_files_present() -> dict:
    """{"<model>": bool} for the non-Cactus models."""
    return {
        "deberta": all((model_dir("deberta") / f).is_file()
                       for f in ("onnx/model_quantized.onnx", "tokenizer.json", "config.json")),
        "potion": all((model_dir("potion-base-8M") / f).is_file()
                      for f in ("config.json", "model.safetensors", "tokenizer.json")),
        "flashrank": (model_dir("flashrank") / "ms-marco-TinyBERT-L-2-v2").is_dir(),
        "ocr": all((model_dir("ocr") / f).is_file()
                   for f in ("ch_PP-OCRv5_det_mobile.onnx", "ch_PP-OCRv5_rec_mobile.onnx")),
    }


def cactus_files_present() -> dict:
    """{"<model>": bool}. A Cactus model counts as present only with its weights AND the engine DLL."""
    cache = get_settings().data_dir / "cache" / "cactus"
    engine = any((cache / "engine").glob("*/*/libcactus.dll")) if (cache / "engine").is_dir() else False
    base = cache / "models"
    return {m: engine and (base / m).is_dir() and any((base / m).rglob("*.cact"))
            for m in ("needle3", "whistle", "mirage")}
