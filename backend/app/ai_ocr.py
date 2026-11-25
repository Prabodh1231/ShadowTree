"""OCR: PP-OCRv5 mobile (det + multilingual rec) through rapidocr, on onnxruntime.
Verified calls only (docs/api_notes.md, "ShadowTree model stack").

Loaded once, lazily, from backend/data/models/ocr, under the shared model lock. Explicit model
paths, so rapidocr never downloads. A missing folder or a load failure raises NotReady.
Tests monkeypatch `ocr_image` by name (see tests/conftest.py).
"""
from __future__ import annotations

from .ai_cactus import MODEL_LOCK
from .ai_classify import NotReady


class NotDownloaded(NotReady):
    """The OCR model files are not on disk yet (before scripts/download_models.py)."""
from .config import apply_env, get_settings, model_dir

DET = "ch_PP-OCRv5_det_mobile.onnx"
REC = "ch_PP-OCRv5_rec_mobile.onnx"   # multilingual rec: read "0x8007..." right where the English one did not
DICT = "ppocrv5_dict.txt"
_state: dict = {"engine": None, "error": None}


def _load():
    """Call with MODEL_LOCK held."""
    if _state["engine"] is not None:
        return _state["engine"]
    if _state["error"]:
        raise NotReady(_state["error"])
    d = model_dir("ocr")
    if not all((d / f).is_file() for f in (DET, REC, DICT)):
        raise NotDownloaded("OCR models are not downloaded: run scripts/download_models.py")  # may appear later
    apply_env()
    try:
        from rapidocr import ModelType, OCRVersion, RapidOCR
        params = {
            "Det.model_path": str(d / DET), "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.MOBILE,
            "Rec.model_path": str(d / REC), "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE,
            "Global.log_level": "warning",
            "Global.use_cls": False,  # no angle classifier: its model is not ours and could be fetched; pages are upright
            "EngineConfig.onnxruntime.intra_op_num_threads": get_settings().onnx_threads,
        }
        params["Rec.rec_keys_path"] = str(d / DICT)
        _state["engine"] = RapidOCR(params=params)
    except Exception as exc:
        _state["error"] = f"OCR failed to load: {type(exc).__name__}: {exc}"
        raise NotReady(_state["error"]) from exc
    return _state["engine"]


def is_loaded() -> bool:
    return _state["engine"] is not None


def close() -> None:
    _state["engine"] = None
    _state["error"] = None


def ocr_image(data) -> list[str]:
    """Text lines, top to bottom, from encoded image bytes (PNG/JPEG) or a BGR uint8 ndarray.
    [] when no text is found."""
    with MODEL_LOCK:
        out = _load()(data)
    return [t.strip() for t in (getattr(out, "txts", None) or ()) if t and t.strip()]
