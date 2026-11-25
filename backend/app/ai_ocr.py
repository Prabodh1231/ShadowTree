"""OCR seam (PP-OCRv5 mobile via rapidocr). Step 4 fills it in.

Until then `ocr_image` raises NotReady, so callers keep their no-OCR path.
Tests monkeypatch `ocr_image` by name (see tests/conftest.py).
"""
from __future__ import annotations

from .ai_classify import NotReady


def ocr_image(data: bytes) -> list[str]:
    """Text lines read from encoded image bytes (PNG/JPEG), top to bottom. Step 4 replaces this."""
    raise NotReady("OCR is not ready (PP-OCRv5 arrives in Step 4)")
