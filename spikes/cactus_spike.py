"""Phase 0 spike: prove Cactus runs on this Windows machine.

Runs one real call per capability on tiny generated inputs:
  1. Mirage image description      cactus.Mirage().describe(path)
  2. Whistle audio transcription   cactus.transcribe(path)
  3. Needle 3 structured extract   cactus.extract(text, schema) and Cactus(tools=[...]).complete(text)

Usage (from the repo root):
  backend\\.venv\\Scripts\\python.exe spikes\\cactus_spike.py

Model caches and generated inputs go to backend/data/ (gitignored).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend" / "data"
SPIKE_DIR = DATA / "spike"
SPIKE_DIR.mkdir(parents=True, exist_ok=True)

# Local only: no telemetry, and keep every cache inside backend/data/.
os.environ["CACTUS_TELEMETRY"] = "0"
os.environ["DO_NOT_TRACK"] = "1"
os.environ.setdefault("XDG_CACHE_HOME", str(DATA / "cache"))
os.environ.setdefault("HF_HOME", str(DATA / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")


def make_image(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (640, 400), (245, 246, 250))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
        small = ImageFont.truetype("arial.ttf", 20)
    except OSError:
        font = small = ImageFont.load_default()
    d.rectangle([0, 0, 640, 56], fill=(40, 60, 120))
    d.text((20, 12), "Monthly Budget", fill="white", font=font)
    d.rectangle([30, 90, 610, 150], outline=(40, 60, 120), width=3)
    d.text((48, 105), "Groceries   $120.50", fill="black", font=small)
    d.rectangle([30, 170, 610, 230], outline=(40, 60, 120), width=3)
    d.text((48, 185), "Electricity  $64.00", fill="black", font=small)
    d.ellipse([500, 280, 600, 380], fill=(220, 80, 60))
    img.save(path)


def make_wav(path: Path) -> str:
    """16 kHz mono 16-bit speech via Windows System.Speech (no extra deps)."""
    sentence = "Please pay the electricity invoice of sixty four dollars before Friday."
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, "
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
        "[System.Speech.AudioFormat.AudioChannel]::Mono); "
        f"$s.SetOutputToWaveFile('{path}', $f); "
        f"$s.Speak('{sentence}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    return sentence


def timed(label: str, fn):
    t0 = time.perf_counter()
    try:
        out = fn()
        ok = True
    except Exception as exc:  # report, keep going so every capability is tried
        out = f"{type(exc).__name__}: {exc}"
        ok = False
    dt = time.perf_counter() - t0
    print(f"[{'OK' if ok else 'FAIL'}] {label}: {dt:.2f}s")
    return out, dt, ok


def show(obj) -> None:
    text = json.dumps(obj, indent=2, default=str, ensure_ascii=False)
    print(text[:3000] + ("\n...(truncated)" if len(text) > 3000 else ""))


def main() -> int:
    results = {}
    t0 = time.perf_counter()
    import cactus
    print(f"cactus {cactus.__version__} imported in {time.perf_counter() - t0:.2f}s")
    print(f"python {sys.version.split()[0]} on {sys.platform}")

    img = SPIKE_DIR / "spike image.png"   # space in name on purpose
    wav = SPIKE_DIR / "spike speech.wav"
    make_image(img)
    spoken = make_wav(wav)
    print(f"inputs: {img} ({img.stat().st_size} B), {wav} ({wav.stat().st_size} B)")

    # 1. Mirage image description
    print("\n== 1. Mirage image description ==")
    mirage, dt_load, ok = timed("Mirage() construct (first = download + load)", cactus.Mirage)
    results["mirage_load_s"] = dt_load
    if ok:
        out, dt, ok = timed("Mirage.describe(path)", lambda: mirage.describe(str(img)))
        results["mirage_describe_s"] = dt
        if ok:
            print("top-level keys:", list(out.keys()))
            compact = {k: v for k, v in out.items() if k != "objects"}
            compact["objects"] = [
                {k: o.get(k) for k in ("id", "name", "score", "position", "description")}
                for o in out.get("objects", [])[:5]
            ]
            show(compact)
        else:
            show(out)
        # 'caption' is NOT a valid section; valid ones are listed in docs/api_notes.md
        out2, dt2, ok2 = timed(
            "Mirage.describe(path, sections=['scene','regions','text'])",
            lambda: mirage.describe(str(img), sections=["scene", "regions", "text"]),
        )
        results["mirage_sections_s"] = dt2
        show(out2)
    else:
        show(mirage)

    # 2. Whistle transcription
    print("\n== 2. Whistle transcription ==")
    print(f"spoken: {spoken!r}")
    out, dt, ok = timed("cactus.transcribe(path) (first = download + load)",
                        lambda: cactus.transcribe(str(wav), language="en"))
    results["whistle_first_s"] = dt
    show(out)
    out, dt, ok = timed("cactus.transcribe(path) (warm)",
                        lambda: cactus.transcribe(str(wav), language="en"))
    results["whistle_warm_s"] = dt
    if ok:
        print("text:", out.get("text"))

    # 3. Needle 3 structured extraction
    print("\n== 3. Needle 3 structured extraction ==")
    doc = ("Invoice INV-2041 from Northwind Supplies. Billed to billing@example.com, "
           "phone +1 555-0142. Items: 3 ergonomic chairs at $180 each, 1 standing desk "
           "at $420. Total due $960 by 15 December 2026.")
    schema = {
        "name": "file_card",
        "description": "Describe a document for a file browser card.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "short title of the document"},
                "summary": {"type": "string", "description": "one sentence summary"},
                "keywords": {"type": "array", "items": {"type": "string"},
                             "description": "3 to 6 topic keywords"},
            },
            "required": ["title", "summary", "keywords"],
        },
    }
    out, dt, ok = timed("cactus.extract(text, schema, strict=False) (first = download + load)",
                        lambda: cactus.extract(doc, schema, strict=False))
    results["needle_first_s"] = dt
    show(out)
    out, dt, ok = timed("cactus.extract(text, schema, strict=False) (warm)",
                        lambda: cactus.extract(doc, schema, strict=False))
    results["needle_warm_s"] = dt

    def via_agent():
        with cactus.Cactus(tools=[schema], stateless=True) as agent:
            return agent.complete(doc)

    out, dt, ok = timed("cactus.Cactus(tools=[schema]).complete(text)", via_agent)
    show(out)

    journal = ("Dear diary, today I walked by the lake with my dog and felt calm for the "
               "first time this week. I want to start painting again.")
    out, dt, ok = timed("cactus.extract(journal, schema) -> may be None (refusal)",
                        lambda: cactus.extract(journal, schema, strict=False))
    show(out)

    # Cache sizes
    print("\n== model / engine cache ==")
    cache = Path(os.environ["XDG_CACHE_HOME"]) / "cactus"
    for f in sorted(cache.rglob("*")):
        if f.is_file():
            print(f"{f.stat().st_size / 1e6:8.2f} MB  {f.relative_to(DATA)}")
    print("\ntimings:", json.dumps({k: round(v, 2) for k, v in results.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
