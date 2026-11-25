## Inspiration

Every Downloads folder looks the same: `scan0042.pdf`, `Screenshot 2026-11-20.png`, `voice memo.wav`. You can't tell what is inside without opening each one, and tidying by hand takes hours.

The tools that sort files well live in the cloud, so they want your invoices, notes and ID scans uploaded. The tools that stay local mostly rename or move your files, and one wrong move can break a project or lose something. We wanted both: smart sorting, with no risk to the real files and no data leaving the PC.

## What it does

**ShadowTree is a virtual file system for the mess in your folders. Your real files are never touched.**

You give it a folder and press **Index (Read-Only)**. ShadowTree reads each file, uses AI that runs on your own PC to give it a title, a summary and tags, and shows the files in clean virtual folders. Nothing is moved, renamed, written or deleted on disk.

- **Understands more than text.** Text files, PDFs, screenshots (image description and text in the picture) and voice memos (speech to text) all get a title and summary.
- **Privacy built in.** Files with personal data such as emails, phone numbers and names go to a "Sensitive (PII)" folder. A **Redacted** view hides the values.
- **Your own folders.** Type a name and a short description, such as "Money". ShadowTree suggests an emoji and fills the folder by meaning, not by file name.
- **Plain-words search.** Searching `my diary` finds the journal, and `invoice` finds the invoice first, even in files whose names say nothing about it.
- **Reveal on Disk.** Jumps to the real file in File Explorer.
- **Works when AI fails.** Every file has an `ai_status` (`ok`, `fallback`, `error`). If a model fails or returns nothing, the file still gets a title from its name, a summary from its first text and frequency-based keywords.

## How we built it

ShadowTree has two halves that talk over loopback only (`127.0.0.1`):

- **Backend (FastAPI and SQLite, Python 3.12).** A read-only scanner opens files with read-only APIs. The index lives in `backend\data\`, never in your folder. The on-device models:
  - **Cactus** *Needle* (titles, summaries, keywords), *Whistle* (speech to text) and *Mirage* (image description and OCR).
  - **DeBERTa** (an NLI model on ONNX Runtime, no PyTorch) sorts files into folders by asking: does this text match this folder?
  - **potion** (Minish Lab) and **FlashRank** find and re-order search results. **RapidOCR** (PP-OCRv5) reads text in images and scanned PDFs.
- **Desktop app (Tauri).** A native window starts the backend, stops it when you close the window, and takes folders by drag and drop.
- **Frontend (Vite, plain JavaScript).** The **Desert Ant Labs** models *Redact*, *Gist* and *Emo* run in the browser through **LiteRT.js**. They find personal data, suggest topics and pick folder emoji.

We started with a spike phase that ran every model API once and wrote down what really works, then built the backend, the UI and a privacy pass on top.

File contents, text and summaries never leave the machine. The only outbound requests are the one-time model downloads and the Desert Ant license check (a random install ID, the domain, and the model and SDK version, never any file content). Both are listed in the README.

## Challenges we ran into

- **Needle is extractive.** It copies spans from the file and doesn't write summaries. On some files it returned nothing, and its confidence on an invoice was very low. We merge results field by field, and keywords must be grounded: at least 90% of their words must appear in the file, otherwise the fallback fills in. The fallback design became a core feature.
- **Model APIs didn't match the plan.** Mirage returns structured JSON (scene, objects, regions, OCR lines), not a caption, so we build the description from those parts. We recorded each deviation in `docs/api_notes.md`.
- **Privacy while the AI is working.** Titles and keywords can leak the personal data we are trying to hide. The UI hides a file's title and keywords until the privacy pass has checked it, and masks PII in tags and in the titles of PII files.
- **Several models on one PC.** We replaced the heavy folder-sorting model (GLiClass with PyTorch) with small ONNX models. The backend now needs about 625 MB of RAM (working set), down from 2.3 GB, with one worker and one background scan job.
- **Making a slow scan feel alive.** Cards appear as each file finishes (the UI refetches every 2 seconds) instead of after the whole scan.
- **Honest limits.** The folder sorter is careful: files it is unsure about get a dashed "Best guess" folder, and on one real folder 63 of 134 files still stayed in Unsorted. Search ranks by meaning with small local models, so it is approximate: a vague query such as "money I spent" now shows only weak matches under "No strong matches. Closest:", the app is Windows only, and the Desert Ant license check can't be turned off. We documented these instead of hiding them.

## Accomplishments that we're proud of

- A hand check on the sample folder: 8 files indexed with no errors in about 8.5 seconds, **zero changes to file hashes and modification times**, and `invoice` and `my diary` putting the right file first (warm search takes 4 ms on the sample folder).
- Everything runs on the user's PC, with no cloud AI and no analytics, and the exact list of network requests is in the README.
- Several AI stacks (Cactus, DeBERTa, potion and FlashRank, RapidOCR, Desert Ant) working together, each with a fallback, so one failing model never loses a file.
- 98 backend tests passing, with the models mocked.

## What we learned

- A non-destructive design, a view on top of the files and not a change to them, makes people willing to try an AI organizer on real folders.
- Small on-device models are rough on their own. The product works because of the checks around them: fallbacks, grounding and an honest `ai_status`.
- Verify third-party APIs with a spike before building, and write the deviations down.
- Smaller models were enough once we put checks around them.

## What's next (not built)

- Voice: Silero VAD and Moonshine for audio.
- Desert Ant v6 upgrade and the Eye image model.
- Better search ranking, and macOS and Linux support.
