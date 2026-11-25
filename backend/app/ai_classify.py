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

NLI_BATCH = 16
MAX_TOKENS = 384

_nli: dict = {"session": None, "tok": None, "ent": 0, "inputs": [], "error": None}


class Busy(Exception):
    """The model lock was not free within the wait time."""


class NotReady(RuntimeError):
    """The model for this step is not wired in yet (or not downloaded)."""


def is_loaded() -> bool:
    return _nli["session"] is not None


def load_error() -> str | None:
    return _nli["error"] or _rk["error"]


def close() -> None:
    _nli.update(session=None, tok=None, error=None)
    _rk["ranker"] = _rk["error"] = None


def classify(text: str, labels: list[str], wait: float | None = None) -> list[float]:
    """Entailment probability (0..1) of each hypothesis in `labels` given the premise `text`.
    `labels` are full hypothesis strings (see `hypothesis`). DeBERTa NLI via onnxruntime;
    pairs run in batches, the model lock is taken per batch."""
    out: list[float] = []
    for i in range(0, len(labels), NLI_BATCH):
        part = labels[i:i + NLI_BATCH]
        if wait is None:
            MODEL_LOCK.acquire()
        elif not MODEL_LOCK.acquire(timeout=wait):
            raise Busy("models are busy")
        try:
            out += _nli_scores(text, part)
        finally:
            MODEL_LOCK.release()
    return out


def hypothesis(name: str, description: str | None) -> str:
    d = (description or "").strip()
    return f"This text is about {name}: {d}." if d else f"This text is about {name}."


def _nli_load():
    """Call with MODEL_LOCK held. Builds the onnxruntime session and tokenizer once."""
    if _nli["session"] is not None:
        return _nli
    if _nli["error"]:
        raise NotReady(_nli["error"])
    d = model_dir("deberta")
    needed = [d / "onnx" / "model_quantized.onnx", d / "tokenizer.json", d / "config.json"]
    if not all(p.is_file() for p in needed):
        raise NotReady("DeBERTa is not downloaded: run scripts/download_models.py")  # may appear later
    apply_env()
    try:
        import json as _json
        import onnxruntime as ort
        from tokenizers import Tokenizer
        id2label = _json.loads((d / "config.json").read_bytes())["id2label"]
        ent = [int(k) for k, v in id2label.items() if str(v).lower() == "entailment"]
        if len(ent) != 1:
            raise ValueError(f"no single 'entailment' label in config.json id2label: {id2label}")
        so = ort.SessionOptions()
        so.intra_op_num_threads = get_settings().onnx_threads
        so.enable_cpu_mem_arena = False  # keep RSS low: batches are small, allocation cost is negligible
        sess = ort.InferenceSession(str(needed[0]), so, providers=["CPUExecutionProvider"])
        tok = Tokenizer.from_file(str(needed[1]))
        tok.enable_truncation(max_length=MAX_TOKENS, strategy="only_first")  # cut the premise, never the hypothesis
        _nli.update(session=sess, tok=tok, ent=ent[0], inputs=[i.name for i in sess.get_inputs()])
    except Exception as exc:
        _nli["error"] = f"DeBERTa failed to load: {type(exc).__name__}: {exc}"
        raise NotReady(_nli["error"]) from exc
    return _nli


def _nli_scores(premise: str, hypotheses: list[str]) -> list[float]:
    """One session.run per pair, no padding. shortcut: the quantized graph quantizes activations
    per batch, so padded batches changed scores (meeting notes vs Work & Research: 0.57 batched,
    0.79 alone). Per-pair runs are deterministic and fast enough (about 30 ms each); upgrade to
    length-bucketed batches if many folders make this slow."""
    import numpy as np
    n = _nli_load()
    out = []
    for h in hypotheses:
        e = n["tok"].encode(premise, h)
        cols = {"input_ids": e.ids, "attention_mask": e.attention_mask, "token_type_ids": e.type_ids}
        feed = {k: np.array([cols[k]], dtype=np.int64) for k in n["inputs"] if k in cols}
        logits = n["session"].run(None, feed)[0].astype(np.float64)
        p = np.exp(logits - logits.max(axis=-1, keepdims=True))
        out.append(float((p / p.sum(axis=-1, keepdims=True))[0, n["ent"]]))
    return out


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
    """(folder_id, name, description) -> (folder_id, hypothesis). Folder names are unique, so are the hypotheses."""
    return [(fid, hypothesis(name, desc)) for fid, name, desc in items]


def classifier_text(title: str, summary: str, keywords: list[str], excerpt: str) -> str:
    return f"{title}. {summary} Keywords: {', '.join(keywords)}. {(excerpt or '')[:600]}".strip()


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
                   for f in ("ch_PP-OCRv5_det_mobile.onnx", "ch_PP-OCRv5_rec_mobile.onnx", "ppocrv5_dict.txt")),
    }


def cactus_files_present() -> dict:
    """{"<model>": bool}. A Cactus model counts as present only with its weights AND the engine DLL."""
    cache = get_settings().data_dir / "cache" / "cactus"
    engine = any((cache / "engine").glob("*/*/libcactus.dll")) if (cache / "engine").is_dir() else False
    base = cache / "models"
    return {m: engine and (base / m).is_dir() and any((base / m).rglob("*.cact"))
            for m in ("needle3", "whistle", "mirage")}
