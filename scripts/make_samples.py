"""Make the ShadowTree sample folder: 8 messy files with FAKE data only.

Usage (PowerShell):
  backend\\.venv\\Scripts\\python.exe scripts\\make_samples.py [target folder]

Creates <target folder>\\sample_messy_folder\\ (default target: the repo root, which is
gitignored). Needs fpdf2 and Pillow (backend\\requirements.txt). The voice memo uses
Windows System.Speech; if that is missing the WAV is skipped with a message.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

NAME = "sample_messy_folder"

RECEIPT = """Corner Cafe receipt
Date: 2026-11-02
Customer: Alex Sample, alex.sample@example.com, phone 555-0123
Card ending 4242
2 x flat white  $7.00
1 x almond croissant  $3.50
Total paid: $10.50. Thank you for your payment.
"""

BANK = """Bank transfer note
Date: 2026-11-03
From account: Alex Sample, checking ending 0001
To: Harbor Property Management, account ending 0002
Amount: $950.00 transferred for November rent.
Reference: RENT-NOV. Payment sent, balance now $2,310.40.
"""

MEETING = """# Team meeting notes

Weekly sync, project Harbor.

- Sam owns the API migration and will report on Friday.
- Priya reviews the release checklist.
- Next meeting: Tuesday, 10:00.
"""

OUTLINE = """# Research outline: local-first search

1. Question: can small on-device models rank personal documents?
2. Method: compare keyword search with a zero-shot classifier.
3. Data: 40 sample notes, receipts and PDFs.
4. Risks: slow models on low-memory laptops.
"""

JOURNAL = """Dear diary, today I walked by the lake with my dog and felt calm.
I thought about the move, and I am a little nervous but also hopeful.
Tomorrow I will call my sister (555-0187) and tell her the news.
"""

# The path comes in as $args[0], never inside the quoted script text.
PS = (
    "Add-Type -AssemblyName System.Speech;"
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, "
    "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono);"
    "$s.SetOutputToWaveFile($args[0], $f);"
    "$s.Speak('Remind me to pay the electricity bill on Friday.');"
    "$s.Dispose()"
)


def make_pdf(path: Path) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Invoice 2041", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=12)
    for line in (
        "From: Northwind Supplies, 12 Example Street",
        "Bill to: Alex Sample",
        "Contact: billing@example.com   Phone: +1 555-0142",
        "Date: 2026-11-10",
        "",
        "3 x ergonomic chair @ $180.00 = $540.00",
        "1 x standing desk @ $420.00 = $420.00",
        "",
        "Total due: $960.00 by 15 December 2026",
    ):
        pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def make_png(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (640, 360), (235, 235, 240))
    d = ImageDraw.Draw(im)
    try:
        big = ImageFont.truetype("arial.ttf", 26)
        small = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        big = small = ImageFont.load_default()
    d.rectangle([60, 50, 580, 310], fill="white", outline=(120, 120, 120), width=2)
    d.rectangle([60, 50, 580, 92], fill=(190, 40, 40))
    d.text((76, 58), "Error", fill="white", font=big)
    d.text((80, 120), "Payment failed", fill=(20, 20, 20), font=big)
    d.text((80, 165), "Could not save your invoice.", fill=(20, 20, 20), font=small)
    d.text((80, 195), "Error code 0x80070005: access denied.", fill=(20, 20, 20), font=small)
    d.rectangle([420, 250, 540, 290], fill=(40, 70, 160))
    d.text((452, 258), "Retry", fill="white", font=small)
    im.save(path)


def make_wav(path: Path) -> bool:
    try:
        with tempfile.TemporaryDirectory() as td:
            ps1 = Path(td) / "speak.ps1"
            ps1.write_text(PS, encoding="utf-8")
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1), str(path)],
                check=True, timeout=60, capture_output=True,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"voice memo.wav skipped: {exc}")
        return False
    return path.is_file() and path.stat().st_size > 1000


def main() -> None:
    if len(sys.argv) > 2:
        sys.exit("usage: make_samples.py [target folder]")
    target = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(__file__).resolve().parent.parent
    root = (target / NAME).resolve()
    root.mkdir(parents=True, exist_ok=True)
    make_pdf(root / "invoice-2041.pdf")
    (root / "coffee receipt.txt").write_text(RECEIPT, encoding="utf-8")
    (root / "bank transfer note.txt").write_text(BANK, encoding="utf-8")
    (root / "meeting notes.md").write_text(MEETING, encoding="utf-8")
    (root / "research outline.md").write_text(OUTLINE, encoding="utf-8")
    (root / "journal.txt").write_text(JOURNAL, encoding="utf-8")
    make_png(root / "Screenshot 2026-11-20.png")
    make_wav(root / "voice memo.wav")
    for p in sorted(root.iterdir()):
        print(f"{p.name}  {p.stat().st_size} bytes")


if __name__ == "__main__":
    main()
