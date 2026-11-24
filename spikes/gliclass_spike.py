"""Phase 0 spike: prove GLiClass (knowledgator/gliclass-v4-edge) runs on CPU on Windows.

Runs one real call per capability:
  1. multi-label zero-shot folder classification (labels = folder descriptions)
  2. search reranking (query as the single label, threshold=0.0)

Usage (from the repo root):
  backend\\.venv\\Scripts\\python.exe spikes\\gliclass_spike.py
  $env:GLICLASS_DTYPE="bfloat16"; backend\\.venv\\Scripts\\python.exe spikes\\gliclass_spike.py

The Hugging Face cache goes to backend/data/hf (gitignored).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend" / "data"
DATA.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(DATA / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

MODEL_ID = "knowledgator/gliclass-v4-edge"


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def rss() -> str:
    """Working set / peak working set of this process in MB (Windows only)."""
    try:
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        k32.GetCurrentProcess.restype = wt.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC), wt.DWORD]
        psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        return f"rss {pmc.WorkingSetSize / 1e6:.0f} MB (peak {pmc.PeakWorkingSetSize / 1e6:.0f} MB)"
    except Exception:
        return "rss n/a"


def main() -> int:
    t0 = time.perf_counter()
    import torch
    import gliclass
    from gliclass import GLiClassModel, ZeroShotClassificationPipeline
    print(f"gliclass {gliclass.__version__}, torch {torch.__version__}, "
          f"import {time.perf_counter() - t0:.2f}s, {rss()}")

    dtype_name = os.environ.get("GLICLASS_DTYPE", "float32")
    dtype = getattr(torch, dtype_name)
    torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))

    t0 = time.perf_counter()
    model = GLiClassModel.from_pretrained(MODEL_ID, dtype=dtype).eval()
    t_model = time.perf_counter() - t0
    t0 = time.perf_counter()
    pipe = ZeroShotClassificationPipeline(
        model, MODEL_ID, classification_type="multi-label",
        max_length=1024, device="cpu", progress_bar=False,
    )
    t_pipe = time.perf_counter() - t0
    print(f"model load ({dtype_name}, first run includes download): {t_model:.2f}s; "
          f"pipeline+tokenizer: {t_pipe:.2f}s; architecture={model.config.architecture_type}; {rss()}")

    folders = {
        "Finance & Receipts": "invoices, receipts, bills, payments and money spent",
        "Work & Research": "work documents, meeting notes, projects and research",
        "Personal & Notes": "personal journal, diary, feelings and private notes",
        "Screenshots & Media": "screenshots, images, photos, audio recordings and media",
    }
    labels = list(folders.values())
    texts = [
        "Invoice INV-2041 from Northwind Supplies. 3 ergonomic chairs at $180 each. Total due $960.",
        "Meeting notes - Q3 roadmap sync. Sam owns the API migration. Risks: hiring delays.",
        "Dear diary, today I walked by the lake with my dog and felt calm for the first time this week.",
        "Screenshot of a budget app window with a blue title bar and text 'Monthly Budget'.",
    ]

    print("\n== 1. multi-label classification (threshold=0.5) ==")
    t0 = time.perf_counter()
    out = pipe(texts, labels, threshold=0.5, batch_size=4)
    dt = time.perf_counter() - t0
    print(f"{len(texts)} texts x {len(labels)} labels in {dt:.2f}s ({dt / len(texts) * 1000:.0f} ms/text); {rss()}")
    print("raw shape: list[len(texts)] of list[{label, score, initial_score?}] (only labels >= threshold)")
    print("raw[0] =", json.dumps(out[0], indent=None))
    name_by_label = {v: k for k, v in folders.items()}
    for text, preds in zip(texts, out):
        shown = ", ".join(f"{name_by_label[p['label']]} {p['score']:.2f}" for p in preds) or "(none -> Unsorted)"
        print(f"- {text[:48]!r:52} -> {shown}")

    print("\n== 1b. all scores (threshold=0.0) ==")
    out_all = pipe(texts[:1], labels, threshold=0.0)
    print(json.dumps(out_all[0], indent=None))

    print("\n== 2. search rerank (query as the label, threshold=0.0) ==")
    query = "money I spent"
    t0 = time.perf_counter()
    scores = pipe(texts, [query], prompt="Does the document match the search query?", threshold=0.0)
    dt = time.perf_counter() - t0
    ranked = sorted(zip(texts, scores), key=lambda p: -p[1][0]["score"])
    print(f"query={query!r}: {len(texts)} docs in {dt:.2f}s; {rss()}")
    for text, s in ranked:
        print(f"  {s[0]['score'] * 100:5.1f}%  {text[:60]}")

    hub = Path(os.environ["HF_HOME"]) / "hub" / ("models--" + MODEL_ID.replace("/", "--"))
    total = sum(f.stat().st_size for f in hub.rglob("*") if f.is_file()) if hub.exists() else 0
    print(f"\nHF cache: {hub} = {total / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
