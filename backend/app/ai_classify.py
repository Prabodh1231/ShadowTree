"""Folder classification and search rerank seam (Steps 2 and 3 fill it in).

Step 1 removed GLiClass and torch. Until DeBERTa (Step 3) and FlashRank (Step 2) are wired,
`classify` and `rerank` raise `NotReady`. The scanner catches that and puts the file in
Unsorted, and search stays BM25-only. The names below are the seam the tests monkeypatch.
"""
from __future__ import annotations

from .ai_cactus import MODEL_LOCK, ModelTimeout  # noqa: F401  (one lock for every model call)
from .config import get_settings, model_dir

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


def classify(text: str, labels: list[str]) -> list[float]:
    """One score (0..1) per label. Step 3 replaces this with DeBERTa NLI."""
    raise NotReady("the folder classifier is not ready (DeBERTa arrives in Step 3)")


def rerank(query: str, passages: list[str], wait: float | None = None) -> list[float]:
    """One relevance score per passage. Step 2 replaces this with FlashRank."""
    raise NotReady("the reranker is not ready (FlashRank arrives in Step 2)")


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
