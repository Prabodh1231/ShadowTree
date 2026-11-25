> **Note (2026-11-25):** The model stack changed after this spec was written. GLiClass, PyTorch and transformers are gone. Folder sorting uses DeBERTa (ONNX), search uses potion and FlashRank, OCR uses RapidOCR, and the app runs in a Tauri window. See [docs/review/shadowtree-plan.md](review/shadowtree-plan.md). The text below is the original spec.

# Build prompt for Kiro

> Paste everything below the line into Kiro (Spec mode). Working title is **VeilFS**, so rename it freely.

---

## Role and working agreement

You are building **VeilFS**, a local, **non-destructive** Virtual File System web app for Windows. It indexes a messy folder, uses on-device AI to describe and classify each file, and shows the results as *virtual* folders. **The real files on disk are never moved, renamed, written, or deleted.**

This is a hackathon entry. It will be judged on **Presentation, Working, and GitHub repo**. A reliable demo matters more than extra features. If something can't be made to work reliably, add a fallback. Don't leave it half-working.

Work in **phases**. At the end of every phase:
1. Make sure everything in that phase runs.
2. Write `docs/review/phase-N.md` containing what was built, every deviation from this spec and why, the exact commands you ran with their (trimmed) output, and known issues.
3. Commit (`git init` first if needed). Use one commit per task, with clear messages.
4. **Stop and wait for review approval before starting the next phase.** An external reviewer will read the review note and the git diff.

Before Phase 1, create a steering file `.kiro/steering/non-negotiables.md` that contains the "Non-negotiables" section below. That way every task follows it.

## Non-negotiables

- **Read-only on user data.** Scanned files are opened only with `open(path, "rb")` or equivalent read-only APIs. Nothing is ever written inside the scanned root: no DB, cache, thumbnails, or temp files there. App data lives in `backend/data/`.
- **No invented APIs.** Every call to `cactus`, `gliclass`, `@desert-ant-labs/*`, and `@litertjs/core` must match what Phase 0 verified in `docs/api_notes.md`. If a method from this spec doesn't exist, use the real equivalent and record the deviation. Never guess.
- **Every AI step has a fallback.** If a model errors, times out, or returns empty, the file is still indexed. The fallbacks are a title from the filename, a summary from the first ~300 chars of text or basic metadata, and keywords from simple frequency analysis. Record `ai_status` per file (`ok | fallback | error`) and show it subtly in the UI.
- **Local only.** The backend binds to `127.0.0.1`. CORS allows only the Vite dev origin and the built frontend origin. There are no cloud AI APIs. File content never leaves the machine; the only outbound requests are first-run model downloads and the Desert Ant license check (install ID, domain, model and SDK version, platform; no content), both disclosed in the README.
- **No secrets or personal data in the repo.** Sample data uses obviously fake values (`@example.com` emails, `555-01xx` phone numbers).
- **Windows first.** Commands in the README are PowerShell. Paths go through `pathlib`. Handle spaces in paths.

## Stack

- **Backend:** Python 3.11+, FastAPI, Uvicorn, SQLite (stdlib `sqlite3`, FTS5), `pypdf`, Pillow.
- **AI (backend):**
  - **Cactus Compute** (`pip install -U cactus-compute`, `import cactus`) for image description, audio transcription, and structured extraction of `{title, summary, keywords}` from text.
  - **Knowledgator GLiClass** (`pip install gliclass`), model `knowledgator/gliclass-v4-edge`, on CPU, for multi-label zero-shot folder classification and search reranking.
- **Frontend:** Vite + vanilla JS (no framework), modern CSS.
- **AI (browser):** `@desert-ant-labs/redact`, `@desert-ant-labs/gist`, `@desert-ant-labs/emo`, `@litertjs/core`. Use the **browser builds only**. Do NOT import any `/native` entry.

---

## Phase 0: API spike (no app code yet)

Goal: prove that each AI stack installs and runs **on this Windows machine**, and record the real APIs.

Tasks:
1. Create `backend/.venv`, then install `cactus-compute`, `gliclass`, and their deps. Record the exact versions in `backend/requirements.txt` (pinned).
2. Inspect the installed packages: use `help()`, `inspect.signature`, the package source, and their README or examples. Write `docs/api_notes.md` with the **real** import paths, constructors, method signatures, return shapes, model download locations and sizes, and first-load time for:
   - Cactus image description (the spec assumes something like `cactus.Mirage().describe(path)`, so verify it)
   - Cactus audio transcription (spec assumes `cactus.transcribe(path)["text"]`, so verify it)
   - Cactus tool-calling or structured extraction (spec assumes `cactus.Cactus(tools=[...])`, "Needle 3", so verify it)
   - GLiClass pipeline construction and multi-label output format with `knowledgator/gliclass-v4-edge`
3. Write `spikes/cactus_spike.py` and `spikes/gliclass_spike.py`. Each runs one real call per capability on a tiny generated input and prints the result plus timing.
4. In `frontend/`, scaffold Vite. Install the Desert Ant packages plus `@litertjs/core`, and write `spikes/browser-spike.html` (served by Vite). It must load Redact, Gist, and Emo in the browser and run one call each. Resolve any WASM or model-asset loading issues now (Vite `optimizeDeps.exclude`, `assetsInclude`, copying WASM to `public/`, COOP/COEP headers if required). Document the exact config needed in `docs/api_notes.md`.
5. If any stack **does not work on Windows**, say so clearly in `docs/review/phase-0.md`, describe the fallback you propose, and stop.

Done when: all spikes run, `docs/api_notes.md` is complete, and each capability is marked ✅ works / ⚠️ works with caveats / ❌ broken.

---

## Phase 1: Backend

### Layout
```
backend/
  app/
    main.py          # FastAPI app, CORS, routes
    db.py            # schema, migrations, connection helper
    scanner.py       # read-only walk, hashing, change detection
    extractors.py    # text/pdf/image/audio -> raw text or description
    ai_cactus.py     # Cactus wrappers + fallbacks
    ai_classify.py   # GLiClass wrapper, thresholds, rerank
    jobs.py          # background scan/reclassify jobs + status
    config.py        # paths, thresholds, limits (env-overridable)
  data/              # veilfs.db, model cache (gitignored)
  tests/
```

### Database (SQLite)
- `files`: `id`, `path` (unique, absolute), `name`, `ext`, `kind` (`text|pdf|image|audio`), `size`, `mtime`, `sha256`, `title`, `summary`, `keywords` (JSON), `text_excerpt` (first ~2000 chars of extracted text/description/transcript), `ai_status`, `ai_error`, `client_meta` (JSON, default `{}`), `indexed_at`
- `virtual_folders`: `id`, `name` (unique), `emoji`, `description` (used as the classifier label text), `kind` (`default|custom|smart`), `created_at`
- `file_folder_links`: `file_id`, `folder_id`, `score` REAL, PK(`file_id`,`folder_id`), FKs with `ON DELETE CASCADE`
- `files_fts`: an FTS5 virtual table over `name, title, summary, keywords, text_excerpt`, kept in sync by the code
- Seed default folders, each with a short descriptive label: **Finance & Receipts**, **Work & Research**, **Personal & Notes**, **Screenshots & Media**. Also seed **Unsorted** (kind `smart`) for files below the threshold everywhere. **Sensitive (PII)** is a smart folder computed from `client_meta.has_pii`.

### Scanner
- Walk the given root recursively. Skip hidden and system dirs, `node_modules`, `.git`, and anything over 25 MB (configurable).
- Supported types: `.txt .md .pdf .png .jpg .jpeg .wav`.
- Change detection: if `(path, size, mtime)` is unchanged, skip without hashing. Otherwise compute the SHA-256 and re-index only if the hash changed.
- Remove DB rows for files that no longer exist under the root. Remove rows only, never touch disk.
- Extraction: text/md are decoded UTF-8 with `errors="replace"`, PDF uses `pypdf` (first N pages), image uses Cactus description, audio uses Cactus transcription.
- Structured extraction: truncate input to ~1500 chars, call Cactus tool-calling for `{title, summary, keywords}`, validate the shape, and fall back on empty or invalid output.

### Classification
- Labels are the folder `description`s (fall back to the name). Run multi-label. Link every folder where `score >= CLASSIFY_THRESHOLD` (default 0.5, configurable). If none passes, link to **Unsorted**.
- Classifier input is `title + summary + keywords` (+ a short excerpt).
- Load the model once and reuse it.

### Endpoints
| Method | Path | Behaviour |
|---|---|---|
| GET | `/health` | Status, plus whether each AI stack loaded |
| POST | `/scan` | Body `{root}`. Validates the path exists and is a dir, starts a **background job**, returns `{job_id}`. Rejects if a job is running. |
| GET | `/scan/status` | `{state, processed, total, current_file, errors}` |
| GET | `/files` | Optional `folder_id`, `q`. Returns file cards with folder links and scores |
| GET | `/files/{id}` | Full record incl. `text_excerpt` (for browser-side Redact/Gist) |
| GET | `/folders` | All folders with file counts |
| POST | `/folders` | Body `{name, description?, emoji?}`. Creates a custom folder, then starts a background **reclassify-all** job and returns immediately |
| GET | `/search?q=` | FTS5 BM25 prefilter (top ~50). If FTS returns too few results, fall back to all files. Rerank with GLiClass using the query as the label. Return results with a `match` percentage |
| POST | `/reveal` | Body `{file_id}` **only, never a raw path**. Looks up the path in the DB, checks the file still exists, and runs `subprocess.run(["explorer", f"/select,{path}"])` with a list of args, no shell |
| PATCH | `/files/{id}/client-meta` | Body `{has_pii, pii_types[], topics[], redacted_excerpt?}`. Validates with Pydantic and merges into `client_meta` |
| GET | `/export/snapshot` | JSON of folders, files, and links, used for demo mode (Phase 3) |

### Tests (pytest)
- **Read-only guarantee test:** copy a fixture folder to a temp dir, record `(sha256, size, mtime)` and the dir listing for every entry, run a full scan plus reclassify, and assert that nothing changed and no new files appeared.
- Rescan skips unchanged files (count AI calls with a mock).
- `/reveal` rejects unknown ids and never accepts paths.
- Classification falls back to Unsorted when below the threshold.
- AI fallback path: monkeypatch Cactus to raise, and assert the file is indexed with `ai_status="fallback"`.

---

## Phase 2: Frontend

### Layout
- **Left sidebar:** All Files, Sensitive (PII), Unsorted, the default and custom virtual folders (emoji + name + count), and a "New Virtual Folder" input with an optional description.
- **Top bar:** folder path input, an **Index (Read-Only)** button, a scan progress bar driven by `/scan/status`, and a natural-language search bar.
- **Main pane:** a grid of file cards. Each card shows the kind icon, AI title, summary, keyword and topic tags, folder chips with match %, PII badge, original path (monospace, with a copy button), a **Reveal on Disk** button, and a subtle `ai_status` indicator.
- **Detail drawer:** opens when you click a card. It shows the full summary and the excerpt, with a **Redacted / Original** toggle that defaults to Redacted.
- Add empty, loading, and error states everywhere, plus a persistent "🔒 Read-only: your files are never modified" indicator.

### Browser AI (Desert Ant, browser builds only)
- Lazy-load models after the first paint, ideally in a Web Worker so the UI stays responsive.
- **Emo:** when creating a folder, suggest an emoji from the name and description. The user can override it.
- **Redact:** run on each file's `text_excerpt` (from `GET /files/{id}`), **not just the summary**. Produce `has_pii`, `pii_types`, and a redacted excerpt.
- **Gist:** topic tags from the excerpt and summary.
- PATCH the results to `/files/{id}/client-meta`, and skip files whose `client_meta` already matches the current `sha256`.
- If a Desert Ant model fails to load, the app still works and shows a small "Privacy scan unavailable" note.

### Design
Clean, modern, light and dark mode. The UI must not look like a generic template. It needs to look good in a demo video at 1080p.

---

## Phase 3: Sample data, demo mode, verification

1. `scripts/make_samples.py` generates `sample_messy_folder/` containing 6–8 safe dummy files:
   - a fake invoice PDF with `billing@example.com`, `+1 555-0142`, and line items (use `fpdf2`)
   - a receipt `.txt` with fake PII
   - meeting notes `.md` and a research outline `.md`
   - a personal journal-style `.txt`
   - a generated "screenshot" PNG (Pillow, UI-like shapes plus text)
   - a short **16 kHz mono WAV with real speech** (generate it with Windows `System.Speech` via PowerShell or `pyttsx3`, then resample to 16 kHz. Fall back to a tone only if TTS is unavailable and note that in the review)
2. `scripts/smoke_test.py` runs end-to-end against a running backend: it scans the sample folder, waits for completion, and asserts that every file is indexed, the invoice lands in Finance & Receipts, a new custom folder triggers reclassification, search returns Finance & Receipts files as the top 3 for "money I spent" (a receipt ranking first is fine) and the invoice file first for "invoice", and `/reveal` works for a valid id. It also runs the read-only check (hashes and mtimes before and after).
3. **Demo mode:** `npm run build:demo` builds a static frontend that loads `public/demo/snapshot.json` (exported from `/export/snapshot` after scanning the samples) instead of the API. Reveal is disabled with a tooltip. Search uses simple client-side matching. Make it deployable to GitHub Pages, so judges can click around without installing anything.

---

## Phase 4: README and submission assets

`README.md` contains:
- One-paragraph pitch, the problem, who it's for, and what makes it different (non-destructive + fully on-device)
- An architecture diagram (Mermaid): browser (Vite + Desert Ant) ↔ FastAPI (Cactus + GLiClass) ↔ SQLite, with disk read-only
- **Exact PowerShell run commands** from a fresh clone: venv, pip install, sample generation, backend start, frontend start, tests, smoke test, demo build
- Model download sizes and first-run expectations
- Screenshots (`docs/screenshots/`)
- A **Credits & third-party** section: Cactus Compute, Knowledgator GLiClass, Desert Ant Labs, LiteRT.js, and the other libs with their licenses. It must say clearly what was built for this hackathon.
- Known limitations and future work

Also write `docs/demo_script.md`, a 2–3 minute video script: messy folder in Explorer → Index → files appear in virtual folders → PII flagged and redacted → create a custom folder (emoji auto-assigned, reclassification) → natural-language search → Reveal on Disk → show the original folder is unchanged.

---

## Repo hygiene
- `.gitignore`: `.venv/`, `node_modules/`, `backend/data/`, model caches, `dist/`, `.env`
- Pin backend deps, commit `package-lock.json`
- No code or files left in the repo root beyond the README, license, and config
- MIT license (unless told otherwise)
