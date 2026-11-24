"""GLiClass wrapper: folder classification and search rerank. Verified calls only
(docs/api_notes.md). `torch` and `gliclass` are imported lazily, after apply_env().

The load happens once, lazily, on first use, under the shared model lock. A load
failure is cached so it is not retried (and re-allocated) for every file.
"""
from __future__ import annotations

from pathlib import Path

from .ai_cactus import MODEL_LOCK, ModelTimeout  # one lock for every model call
from .config import GLICLASS_MODEL_ID, apply_env, get_settings

MAX_LABELS = 25
RERANK_PROMPT = "Does the document match the search query?"

_state: dict = {"pipe": None, "error": None, "dtype": None}


class Busy(Exception):
    """The model lock was not free within the wait time."""


def is_loaded() -> bool:
    return _state["pipe"] is not None


def load_error() -> str | None:
    return _state["error"]


def used_dtype() -> str | None:
    return _state["dtype"]


def _load():
    """Call with MODEL_LOCK held."""
    if _state["pipe"] is not None:
        return _state["pipe"]
    if _state["error"]:
        raise RuntimeError(f"GLiClass unavailable: {_state['error']}")
    cfg = get_settings()
    apply_env()
    try:
        import torch
        from gliclass import GLiClassModel, ZeroShotClassificationPipeline
        torch.set_num_threads(cfg.torch_threads)
        dtype = getattr(torch, cfg.gliclass_dtype)
        model = GLiClassModel.from_pretrained(GLICLASS_MODEL_ID, dtype=dtype).eval()
        pipe = ZeroShotClassificationPipeline(
            model, GLICLASS_MODEL_ID, max_classes=MAX_LABELS, max_length=1024,
            classification_type="multi-label", device="cpu", progress_bar=False)
    except BaseException as exc:  # incl. MemoryError, missing files in offline mode
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        _state["error"] = f"{type(exc).__name__}: {exc}"
        raise RuntimeError(f"GLiClass failed to load: {exc}") from exc
    _state["pipe"], _state["dtype"] = pipe, cfg.gliclass_dtype
    return pipe


def close() -> None:
    _state["pipe"] = None


def classify(text: str, labels: list[str]) -> list[float]:
    """Score `text` against `labels` (unique strings). Returns one score per label,
    in order. Labels are sent in batches of at most 25; the lock is taken per batch."""
    scores: dict[str, float] = {}
    for i in range(0, len(labels), MAX_LABELS):
        batch = labels[i:i + MAX_LABELS]
        with MODEL_LOCK:
            pipe = _load()
            res = pipe([text], batch, threshold=0.0, batch_size=1)
        for p in res[0]:
            scores[p["label"]] = float(p["score"])
    return [scores.get(l, 0.0) for l in labels]


def rerank(query: str, passages: list[str], wait: float | None = None) -> list[float]:
    """Raw GLiClass score per passage for the query as the only label."""
    if wait is None:
        wait = get_settings().search_lock_wait_s
    if not MODEL_LOCK.acquire(timeout=wait):
        raise Busy("models are busy")
    try:
        pipe = _load()
        res = pipe(passages, [query], prompt=RERANK_PROMPT, threshold=0.0, batch_size=4)
    finally:
        MODEL_LOCK.release()
    return [float(r[0]["score"]) if r else 0.0 for r in res]


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

def gliclass_files_present() -> dict:
    d = get_settings().data_dir / "hf" / "hub" / ("models--" + GLICLASS_MODEL_ID.replace("/", "--")) / "snapshots"
    return {GLICLASS_MODEL_ID: d.is_dir() and any(d.glob("*/model.safetensors"))}


def cactus_files_present() -> dict:
    """{"<model>": bool}. A Cactus model counts as present only with its weights AND the engine DLL."""
    cache = get_settings().data_dir / "cache" / "cactus"
    engine = any((cache / "engine").glob("*/*/libcactus.dll")) if (cache / "engine").is_dir() else False
    base = cache / "models"
    return {m: engine and (base / m).is_dir() and any((base / m).rglob("*.cact"))
            for m in ("needle3", "whistle", "mirage")}