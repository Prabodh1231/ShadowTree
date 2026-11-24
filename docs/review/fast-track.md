# Fast track to submission

The owner is short on time. **Skip the rest of Phase 3 and finish in one final phase.** Do the steps in this order, and commit after each one. If time runs out, everything already committed must still be in a working state.

## Step 1: two privacy fixes from Phase 2 (must do, small)

1. **Keyword tags leak PII.** On files with `client_meta.has_pii`, hide any keyword (and redact the title) that contains a Redact `original` value, or that Redact changes. Apply this on cards, search results and the drawer. With the browser AI off, hide all keywords on PII files.
2. **Ground the keywords.** Apply the 90% grounding rule to each model keyword. Drop keywords longer than 4 words or 30 characters, then top up from frequency keywords. (Example of what to stop: "Bread $2.80 miljard".)

Run `pytest -q` and `npm run build`. Both must pass.

## Step 2: sample folder (the only Phase 3 part we keep)

`scripts/make_samples.py <target folder>` creates `sample_messy_folder/` (gitignored) and passes paths as arguments, never interpolating them into PowerShell strings. Contents:
- `invoice-2041.pdf` (fpdf2), with fake name, `billing@example.com`, `+1 555-0142`
- `coffee receipt.txt`, with fake PII
- `bank transfer note.txt` (a third clearly financial file)
- `meeting notes.md`, `research outline.md`
- `journal.txt`
- `Screenshot 2026-11-20.png` (Pillow, a UI-like error dialog with readable text)
- `voice memo.wav` (16 kHz speech via System.Speech, e.g. "Remind me to pay the electricity bill on Friday")

Check it by hand once: scan it, then check that every file is indexed and that "money I spent" puts a receipt or invoice first.

**Skip:** `smoke_test.py`, the GitHub Pages demo build, and `/export/snapshot` work.

## Step 3: polish that shows in the video (only if quick, max ~1 hour total)

- Show cards while a scan runs: refetch `/files` every 2 s, and replace the empty state with "Reading your files…".
- Topics: show at most 2, with score ≥ 0.5.

Skip the rest of the Phase 2 SHOULD-FIX list.

## Step 4: Phase 4 (README + submission assets)

Follow `docs/spec.md` Phase 4, with these changes:
- **README** contents:
  - the pitch, the problem, and who it's for
  - a Mermaid architecture diagram
  - **exact PowerShell commands from a fresh clone**: venv, pip install, `download_models.py`, `npm install`, `npm run fetch-models`, `make_samples.py`, backend start (foreground, Ctrl+C to stop), `npm run dev`, `pytest`
  - first-run sizes (about 1.1 GB backend, 114 MB browser) and the RAM note (2.3 GB, `GLICLASS_DTYPE=bfloat16` for low memory)
  - the existing Network & privacy section, and Credits & third-party with licenses
  - a "What was built for this hackathon" line
  - known limitations: Needle is extractive, search relevance is approximate, Windows only, Desert Ant license check
- **Screenshots:** retake 4–5 shots at 1920×1080 against `sample_messy_folder` into `docs/screenshots/`: grid, drawer (Redacted), search results, new folder with emoji, Sensitive (PII) folder. Embed them in the README.
- **`docs/demo_script.md`:** a 2–3 minute video script, with what to click and what to say for each step.
- Add an MIT `LICENSE` file.
- Make sure `git status` is clean and that no models, DBs, `dist/`, `.venv` or sample files are committed.

Write `docs/review/final.md`: what was done, what was skipped, and the commands run with their output. Then stop for the final review.
