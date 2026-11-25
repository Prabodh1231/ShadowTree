"""Download every backend model once into backend/data/ (idempotent).

  backend\\.venv\\Scripts\\python.exe scripts\\download_models.py

This is the ONLY script that goes online (apply_env(allow_download=True)). The backend
itself always runs with HF_HUB_OFFLINE=1. Hosts: huggingface.co (DeBERTa, potion, FlashRank
zip, Cactus weights) and modelscope.cn (PP-OCRv5, SHA256 checked). Files land in
backend/data/models/<name>; Cactus keeps its own cache under backend/data/cache.
"""
from __future__ import annotations

import hashlib
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import (DEBERTA_FILES, DEBERTA_REPO, FLASHRANK_MODEL, POTION_FILES, POTION_REPO,  # noqa: E402
                        apply_env, get_settings, model_dir)
from app.ai_cactus import NEEDLE_SCHEMA  # noqa: E402  (does not import cactus)

MS = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0"
# (file, url, sha256) from rapidocr 3.10.0 default_models.yaml (onnx, PP-OCRv5 mobile).
OCR_FILES = {
    "det": ("ch_PP-OCRv5_det_mobile.onnx", f"{MS}/onnx/PP-OCRv5/det/ch_PP-OCRv5_det_mobile.onnx",
            "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae"),
    "rec_ch": ("ch_PP-OCRv5_rec_mobile.onnx", f"{MS}/onnx/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile.onnx",
               "5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5"),
}
OCR_DICTS = {
    "ppocrv5_dict.txt": f"{MS}/paddle/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile/ppocrv5_dict.txt",
}


def dir_mb(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6 if p.exists() else 0.0


def step(label: str, fn) -> bool:
    t0 = time.perf_counter()
    try:
        fn()
        print(f"[ok]   {label}: {time.perf_counter() - t0:.1f}s")
        return True
    except Exception as exc:
        print(f"[FAIL] {label}: {type(exc).__name__}: {exc}")
        return False


def deberta():
    from huggingface_hub import hf_hub_download
    for f in DEBERTA_FILES:  # exactly these three files, never the 140 MB weights
        hf_hub_download(DEBERTA_REPO, f, local_dir=model_dir("deberta"))


def potion():
    from huggingface_hub import hf_hub_download
    from model2vec import StaticModel
    d = model_dir("potion-base-8M")
    for f in POTION_FILES:
        hf_hub_download(POTION_REPO, f, local_dir=d)
    StaticModel.from_pretrained(d)  # prove the local folder loads


def flashrank():
    from flashrank import Ranker
    d = model_dir("flashrank")
    d.mkdir(parents=True, exist_ok=True)
    Ranker(model_name=FLASHRANK_MODEL, cache_dir=str(d), log_level="WARNING")


def _fetch(url: str, dest: Path, sha256: str | None = None) -> None:
    if dest.exists() and (sha256 is None or hashlib.sha256(dest.read_bytes()).hexdigest() == sha256):
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as out:
        while chunk := r.read(1 << 20):
            out.write(chunk)
    if sha256 and hashlib.sha256(tmp.read_bytes()).hexdigest() != sha256:
        tmp.unlink()
        raise RuntimeError(f"SHA256 mismatch for {dest.name}")
    tmp.replace(dest)


def ocr():
    d = model_dir("ocr")
    for name, url, sha in OCR_FILES.values():
        _fetch(url, d / name, sha)
    for name, url in OCR_DICTS.items():
        _fetch(url, d / name)


def present() -> None:
    print("\npresent:")
    for name in ("deberta", "potion-base-8M", "flashrank", "ocr"):
        d = model_dir(name)
        files = [f for f in d.rglob("*") if f.is_file() and ".cache" not in f.parts and "__MACOSX" not in f.parts] if d.exists() else []
        print(f"  {name}: {dir_mb(d):.1f} MB, {len(files)} files")
        for f in sorted(files):
            print(f"     {f.relative_to(d)}  {f.stat().st_size / 1e6:.2f} MB")


def main() -> int:
    apply_env(allow_download=True)
    data = get_settings().data_dir
    print(f"data dir: {data}")
    import cactus

    ok = True
    ok &= step("Cactus Mirage (image description)", lambda: cactus.Mirage())
    ok &= step("Cactus Whistle (audio transcription)", lambda: cactus.Whistle())

    def needle():
        agent = cactus.Cactus(tools=[NEEDLE_SCHEMA], auto_date=False, stateless=True)
        agent.close()
    ok &= step("Cactus Needle 3 (structured extraction)", needle)

    ok &= step(f"DeBERTa {DEBERTA_REPO} (3 files)", deberta)
    ok &= step(f"potion {POTION_REPO}", potion)
    ok &= step(f"FlashRank {FLASHRANK_MODEL}", flashrank)
    ok &= step("PP-OCRv5 mobile (det, rec, dict)", ocr)

    present()
    print(f"cactus cache {dir_mb(data / 'cache' / 'cactus'):.0f} MB")
    print("done." if ok else "some downloads failed; see above.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
