"""Step 4: OCR before Mirage for images, OCR for thin PDFs, fallbacks, re-read of old rows.
No model: ai_ocr.ocr_image and extractors.render_pdf_pages are stubs (conftest)."""
import hashlib
import sys
import types

import numpy as np
import pytest
from conftest import run_scan

from app import ai_cactus, ai_classify, ai_embed, ai_ocr, db, extractors

_REAL_RENDER = extractors.render_pdf_pages  # captured before the conftest stub applies


def _fingerprint(root):
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns,
                                       hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir")
            for p in sorted(root.rglob("*"))}


def _thin_pdf(path):
    # a valid one-page PDF with no text layer (what a scanner makes, minus the image)
    path.write_bytes(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                     b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                     b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
                     b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n"
                     b"0000000101 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n164\n%%EOF\n")


def test_image_ocr_runs_before_mirage_and_leads_the_text(client, sample_root, calls, monkeypatch):
    order = []
    monkeypatch.setattr(ai_ocr, "ocr_image", lambda data: order.append("ocr") or ["Payment failed", "Retry"])
    real = ai_cactus.describe_image
    monkeypatch.setattr(ai_cactus, "describe_image", lambda p: order.append("mirage") or real(p))
    run_scan(client, sample_root)
    assert order == ["ocr", "mirage"]
    card = client.get(f"/files/{next(c['id'] for c in client.get('/files').json() if c['name'] == 'shot.png')}").json()
    ex = card["text_excerpt"]
    assert ex.startswith("Text in the image:\nPayment failed\nRetry\n\nImage description:\n")
    assert "Monthly Budget" in ex                                     # Mirage text kept after it
    assert "ocr:ok" in card["ai_error"]


def test_ocr_text_feeds_classify_and_embed(client, sample_root, monkeypatch):
    monkeypatch.setattr(ai_ocr, "ocr_image", lambda data: ["INVOICE 77 overdue zebra"])
    seen_cls, seen_emb = [], []
    real_c, real_e = ai_classify.classify, ai_embed.embed
    monkeypatch.setattr(ai_classify, "classify", lambda t, labels: seen_cls.append(t) or real_c(t, labels))
    monkeypatch.setattr(ai_embed, "embed", lambda texts, wait=None: seen_emb.extend(texts) or real_e(texts))
    run_scan(client, sample_root)
    assert any("INVOICE 77 overdue zebra" in t for t in seen_cls)
    assert any("INVOICE 77 overdue zebra" in t for t in seen_emb)
    cards = {c["name"]: c for c in client.get("/files").json()}
    assert "Finance & Receipts" in [f["name"] for f in cards["shot.png"]["folders"]]   # stub: "invoice" in text
    assert "Screenshots & Media" in [f["name"] for f in cards["shot.png"]["folders"]]
    assert client.get("/search", params={"q": "zebra"}).json()["results"][0]["name"] == "shot.png"


def test_ocr_error_still_indexes_the_image(client, sample_root, monkeypatch):
    def boom(data):
        raise RuntimeError("onnx died")
    monkeypatch.setattr(ai_ocr, "ocr_image", boom)
    st = run_scan(client, sample_root)
    assert st["state"] == "done"
    shot = next(c for c in client.get("/files").json() if c["name"] == "shot.png")
    assert "ocr: RuntimeError: onnx died" in shot["ai_error"] and shot["ai_status"] == "fallback"
    assert shot["summary"] and "Screenshots & Media" in [f["name"] for f in shot["folders"]]


def test_thin_pdf_is_rendered_from_bytes_and_ocrd(client, sample_root, monkeypatch):
    _thin_pdf(sample_root / "scan.pdf")
    got = {}

    def render(data, pages=3, dpi=200, max_pixels=0):
        got.update(data=data, pages=pages, dpi=dpi)
        return [np.zeros((10, 10, 3), np.uint8), np.zeros((10, 10, 3), np.uint8)]
    monkeypatch.setattr(extractors, "render_pdf_pages", render)
    monkeypatch.setattr(ai_ocr, "ocr_image", lambda img: ["Scanned invoice page"])
    run_scan(client, sample_root)
    assert got["data"] == (sample_root / "scan.pdf").read_bytes() and got["pages"] == 3 and got["dpi"] == 200
    card = next(c for c in client.get("/files").json() if c["name"] == "scan.pdf")
    full = client.get(f"/files/{card['id']}").json()
    assert full["text_excerpt"].count("Scanned invoice page") == 2 and "ocr:ok" in card["ai_error"]


def test_text_pdf_is_not_ocrd(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(extractors, "render_pdf_pages", lambda *a, **k: called.append(1) or [])
    monkeypatch.setattr(extractors, "read_pdf", lambda p, n: "A long text layer " * 10)
    monkeypatch.setattr(ai_cactus, "structured", lambda t: None)
    f = tmp_path / "t.pdf"
    f.write_bytes(b"%PDF")
    card = ai_cactus.build_card(f, "pdf", f.name)
    assert not called and "ocr:" not in card["ai_error"]


def test_render_pdf_pages_uses_bytes_and_caps_pixels(monkeypatch):
    """The real function against a fake pypdfium2: opened from a BytesIO, at most 3 pages, pixel cap."""
    seen = {}

    class Bmp:
        def __init__(self, scale):
            self.scale = scale

        def to_pil(self):
            from PIL import Image
            return Image.new("RGB", (4, 3))

    class Page:
        def get_size(self):
            return (2384.0, 3370.0)   # A0 in points

        def render(self, scale):
            seen.setdefault("scales", []).append(scale)
            return Bmp(scale)

        def close(self):
            pass

    class Doc:
        def __init__(self, src):
            seen["src"] = type(src).__name__

        def __len__(self):
            return 5

        def __getitem__(self, i):
            return Page()

        def close(self):
            seen["closed"] = True

    monkeypatch.setitem(sys.modules, "pypdfium2", types.SimpleNamespace(PdfDocument=Doc))
    real = _REAL_RENDER
    imgs = real(b"%PDF-bytes", pages=3, dpi=200, max_pixels=12_000_000)
    assert seen["src"] == "BytesIO" and seen["closed"] and len(imgs) == 3
    s = seen["scales"][0]
    assert 2384 * 3370 * s * s <= 12_000_000 * 1.001 and s < 200 / 72
    assert imgs[0].shape == (3, 4, 3)
    sys.modules.pop("pypdfium2", None)


def test_old_image_and_thin_pdf_rows_are_reread_once(client, sample_root, calls):
    run_scan(client, sample_root)
    conn = db.get_conn()
    conn.execute("UPDATE files SET ext_ver=NULL")      # pretend they were indexed before OCR
    conn.commit()
    before = calls.describe
    st = run_scan(client, sample_root)
    assert calls.describe == before + 1                  # the image is read again (Mirage runs again)
    assert st["stats"]["changed"] == 1 and st["stats"]["skipped"] == 3  # only the image; text files not re-read
    st = run_scan(client, sample_root)
    assert calls.describe == before + 1 and st["stats"]["skipped"] == 4  # stamped: not again


def test_nothing_written_to_the_scanned_root(client, sample_root):
    _thin_pdf(sample_root / "scan.pdf")
    before = _fingerprint(sample_root)
    run_scan(client, sample_root)
    assert _fingerprint(sample_root) == before
