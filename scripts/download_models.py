"""Download every backend model once into backend/data/ (idempotent).

  backend\\.venv\\Scripts\\python.exe scripts\\download_models.py

This is the ONLY script that goes online (apply_env(allow_download=True)). The backend
itself always runs with HF_HUB_OFFLINE=1. Cactus models are fetched through the verified
constructors; GLiClass through huggingface_hub.snapshot_download, with the onnx/ folder
excluded (2.4 GB we do not use).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import GLICLASS_MODEL_ID, apply_env, get_settings  # noqa: E402
from app.ai_cactus import NEEDLE_SCHEMA  # noqa: E402  (does not import cactus)


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

    def gliclass():
        from huggingface_hub import snapshot_download
        snapshot_download(GLICLASS_MODEL_ID, ignore_patterns=["onnx/*", "onnx/**"])
    ok &= step(f"GLiClass {GLICLASS_MODEL_ID} (no onnx/)", gliclass)

    print(f"\nsizes: cactus cache {dir_mb(data / 'cache' / 'cactus'):.0f} MB, "
          f"hugging face cache {dir_mb(data / 'hf'):.0f} MB")
    print("done." if ok else "some downloads failed; see above.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
