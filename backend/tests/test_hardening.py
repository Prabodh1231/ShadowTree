"""Hardening fixes from the code review: PDFium lock, API token, server-side PII baseline,
scan cancel, capped errors, preview cache budget, lighter list payloads, clearing the index."""
from __future__ import annotations

import sys
import threading
import types

from app import extractors

_REAL_RENDER = extractors.render_pdf_pages  # captured before the conftest stub applies


def _fake_pdfium(seen: dict):
    class Bmp:
        def to_pil(self):
            from PIL import Image
            return Image.new("RGB", (4, 3))

    class Page:
        def get_size(self):
            return (100.0, 100.0)

        def render(self, scale):
            seen.setdefault("locked_in_render", []).append(extractors.PDFIUM_LOCK.locked())
            return Bmp()

        def close(self):
            seen.setdefault("locked_in_close", []).append(extractors.PDFIUM_LOCK.locked())

    class Doc:
        def __init__(self, src):
            seen["locked_in_open"] = extractors.PDFIUM_LOCK.locked()

        def __len__(self):
            return 2

        def __getitem__(self, i):
            return Page()

        def close(self):
            seen["locked_in_doc_close"] = extractors.PDFIUM_LOCK.locked()

    return types.SimpleNamespace(PdfDocument=Doc)


def test_every_pdfium_call_holds_the_lock(monkeypatch):
    """PDFium is not thread safe: open, render and close all happen under PDFIUM_LOCK,
    and the lock is free again afterwards."""
    seen: dict = {}
    monkeypatch.setitem(sys.modules, "pypdfium2", _fake_pdfium(seen))
    imgs = _REAL_RENDER(b"%PDF", pages=2)
    assert len(imgs) == 2
    assert seen["locked_in_open"] and seen["locked_in_doc_close"]
    assert all(seen["locked_in_render"]) and all(seen["locked_in_close"])
    assert not extractors.PDFIUM_LOCK.locked()


def test_preview_and_ocr_renders_never_overlap(monkeypatch):
    """The scan thread (OCR) and preview requests call the same function, so at most one
    thread is ever inside the (fake) PDFium at a time."""
    inside, worst = [0], [0]
    gate = threading.Lock()

    class Doc:
        def __init__(self, src):
            with gate:
                inside[0] += 1
                worst[0] = max(worst[0], inside[0])

        def __len__(self):
            return 0

        def close(self):
            with gate:
                inside[0] -= 1

    monkeypatch.setitem(sys.modules, "pypdfium2", types.SimpleNamespace(PdfDocument=Doc))

    def work():
        for _ in range(200):
            _REAL_RENDER(b"%PDF", pages=1)

    ts = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert worst[0] == 1


def test_render_preview_refuses_a_file_that_grew_past_the_limit(tmp_path):
    from PIL import Image
    p = tmp_path / "big.png"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(p)
    assert extractors.render_preview(p, "image", 64, limit=10) is None
    assert extractors.render_preview(p, "image", 64, limit=10_000_000) is not None
