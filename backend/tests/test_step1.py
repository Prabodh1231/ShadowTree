"""Step 1: the torch-free seams. Not-ready seams: classify (until Step 3), and rerank, embed, ocr when their model files are missing."""
import pytest

from app import ai_classify, ai_embed, ai_ocr
from app.config import get_settings
from conftest import run_scan


_ORIG = {n: getattr(ai_classify, n) for n in ("classify", "rerank")}
_ORIG_E, _ORIG_O = ai_embed.embed, ai_ocr.ocr_image


def test_seams_raise_not_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILFS_DATA_DIR", str(tmp_path))   # empty data dir: no model folders, nothing loads
    ai_classify.close()
    ai_embed.close()
    ai_ocr.close()
    with pytest.raises(ai_classify.NotReady):
        _ORIG["classify"]("t", ["a"])
    with pytest.raises(ai_classify.NotReady):
        _ORIG["rerank"]("q", ["p"])
    with pytest.raises(ai_classify.NotReady):
        _ORIG_E(["x"])
    with pytest.raises(ai_classify.NotReady):
        _ORIG_O(b"x")


def test_classifier_error_sends_text_files_to_unsorted(client, sample_root, monkeypatch):
    monkeypatch.setattr(ai_classify, "classify", _ORIG["classify"])
    run_scan(client, sample_root)
    for card in client.get("/files").json():
        want = ["Screenshots & Media"] if card["kind"] in ("image", "audio") else ["Unsorted"]
        assert [f["name"] for f in card["folders"]] == want


def test_onnx_threads_default_and_override(monkeypatch):
    monkeypatch.delenv("ONNX_THREADS", raising=False)
    assert get_settings().onnx_threads >= 1
    monkeypatch.setenv("ONNX_THREADS", "3")
    assert get_settings().onnx_threads == 3
