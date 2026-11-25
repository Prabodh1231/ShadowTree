"""Text embedding seam (potion-base-8M via model2vec). Step 2 fills it in.

Until then `embed` raises NotReady, so callers fall back (BM25-only search, no pre-filter).
Tests monkeypatch `embed` by name (see tests/conftest.py).
"""
from __future__ import annotations

import numpy as np

from .ai_classify import NotReady


def embed(texts: list[str]) -> np.ndarray:
    """(n, 256) float32 array, one row per text. Step 2 replaces this."""
    raise NotReady("embeddings are not ready (potion arrives in Step 2)")
