"""Step 1: the torch-free seams. Until Steps 2 and 3 land, classify and rerank say 'not ready'."""
import pytest

from app import ai_classify, ai_embed, ai_ocr
from app.config import get_settings
from conftest import run_scan


_ORIG = {n: getattr(ai_classify, n) for n in ("classify", "rerank")}
_ORIG_E, _ORIG_O = ai_embed.embed, ai_ocr.ocr_image


def test_seams_raise_not_ready():
    with pytest.raises(ai_classify.NotReady):
        _ORIG["classify"]("t", ["a"])
    with pytest.raises(ai_classify.NotReady):
        _ORIG["rerank"]("q", ["p"])
    with pytest.raises(ai_classify.NotReady):
        _ORIG_E(["x"])
    with pytest.raises(ai_classify.NotReady):
        _ORIG_O(b"x")


def test_not_ready_classifier_sends_files_to_unsorted(client, sample_root, monkeypatch):
    monkeypatch.setattr(ai_classify, "classify", _ORIG["classify"])
    run_scan(client, sample_root)
    for card in client.get("/files").json():
        assert [f["name"] for f in card["folders"]] == ["Unsorted"]


def test_onnx_threads_default_and_override(monkeypatch):
    monkeypatch.delenv("ONNX_THREADS", raising=False)
    assert get_settings().onnx_threads >= 1
    monkeypatch.setenv("ONNX_THREADS", "3")
    assert get_settings().onnx_threads == 3
