# ShadowTree: lightweight models + Tauri (prompt for Kiro)

**Deadline: submissions close 26 Nov 2026, 03:30 IST.** Work in the order below. Commit after every step, and make sure the app works at every commit. If time runs out, everything above the cut line must be finished and working. Owner decisions are final: **remove GLiClass completely (no comparison run), replace it with DeBERTa.**

Non-negotiables still apply (`.kiro/steering/non-negotiables.md`): read-only on user files, no invented APIs (inspect each new package before using it), a fallback for every AI step, local only.

## Step 0: rename to **ShadowTree** (one word)
The current text says "Shadow Tree" (two words) in about 11 files: app title, sidebar, folder dialog, FastAPI title, README, Devpost story, demo script, steering. Change it to **ShadowTree** everywhere users see it. Keep the internal identifiers so nothing breaks: `VEILFS_*` env vars, `veilfs-*` localStorage keys, `veilfs.db`, the npm package name.

The uncommitted folder-picker work is also in the tree (`backend/app/picker.py`, `/pick-folder`, `/quick-folders`, the Choose folder button, quick picks, drag-and-drop to picker, and `backend/tests/test_picker.py`). It's reviewed and working, so commit it first, as its own commit.

## Step 1: new model stack, without torch
- **Remove** `gliclass`, `torch`, `transformers` (and anything only they needed) from `requirements.txt`, the code, the tests, `/health`, `download_models.py`, and the docs.
- **Add** `onnxruntime`, `tokenizers`, `model2vec`, `flashrank`, `rapidocr`, `pypdfium2`. Pin them, and check `pip check` is clean.
- `scripts/download_models.py` downloads every model once into `backend/data/` (set FlashRank's cache dir there too). After that the backend runs offline (`HF_HUB_OFFLINE=1`).

| Job | Model | File |
|---|---|---|
| Folder sorting | `MoritzLaurer/deberta-v3-xsmall-zeroshot-v1.1-all-33` (MIT) | `onnx/model_quantized.onnx` (87 MB) + `tokenizer.json` (verify it exists; if not, build one from the repo's tokenizer files once and record how) |
| Search recall + new-folder pre-filter | `minishlab/potion-base-8M` via `model2vec` | |
| Search rerank | `ms-marco-TinyBERT-L-2-v2` via `flashrank` | |
| OCR | PP-OCRv5 mobile via `rapidocr` | |

Write the verified APIs into `docs/api_notes.md` (a new section), as in Phase 0.

## Step 2: search (potion + FlashRank)
- At index time, embed `title + summary + keywords + first 300 chars of text` with potion. Store the vector as a float32 BLOB in a new `files.vec` column (migrate existing DBs; re-embed rows without a vector on startup or on the next scan).
- `/search`: embed the query, take the cosine top 50 merged with the FTS hits, rerank with FlashRank (query vs the same passage text), then compute `match = rerank score × 100`. Keep the name/title boost, the `{results, weak}` shape and the cut-off. **Re-tune the cut-off** on the sample folder, because the scores are on a new scale.
- Target: under 1 s warm on the sample folder.

## Step 3: folders (DeBERTa NLI, replaces GLiClass)
- Load the ONNX model with `onnxruntime` and `tokenizers`. Read the entailment label index from the model's `config.json` (`id2label`); these models have two classes. The score is `softmax(logits)[entailment]`.
- Text pair: premise = `title + summary + keywords + first ~600 chars of text`, truncated to 384 tokens. Hypothesis = `"This text is about {folder name}: {folder description}."` (just `"This text is about {name}."` if there's no description).
- **At indexing:** score each file against every topic folder. It joins every folder with score ≥ 0.5 (`CLASSIFY_THRESHOLD`). **Screenshots & Media is decided by file type** (image or audio), as well as the topic folders. If no folder matches, the file goes to Unsorted. Batch the pairs.
- **On a new folder:** embed `name + description` with potion. Keep files with cosine ≥ 0.30 (configurable), score only those with DeBERTa, and write **only the new folder's links** (the L4 rule stays; a file that gains a link leaves Unsorted).
- Load models once, lazily. Backend RSS with all models loaded must stay **under 1 GB**.
- Acceptance on `sample_messy_folder`:
  - receipt, invoice and bank note → Finance & Receipts
  - meeting notes and research outline → Work & Research
  - journal → Personal & Notes
  - screenshot and voice memo → Screenshots & Media
  - a new folder "Bills to pay" / "invoices, bills and payments that are due" picks up the invoice, and ideally the voice memo
  - Record the actual scores in the review note.
- Update the mocked tests so they cover the new classifier. All tests must pass.

## Step 4: OCR (PP-OCRv5 mobile)
- **Images:** run OCR first, then Mirage. The OCR lines become the verbatim text (search and folders use it), and Mirage adds the visual description.
- **PDFs:** if `pypdf` gives fewer than 50 characters, render the first 3 pages with `pypdfium2` (about 200 dpi, in memory, never written to disk) and OCR them.
- OCR runs read-only, with a fallback on error, and records `ocr` in the provenance.

## Step 5: Tauri desktop app (on this PC only, no installer)
- Use Tauri v2 in `frontend/src-tauri/`, with window title **ShadowTree**, 1440×900. Run it with `npm run tauri dev`, and build with `npm run tauri build` (the build must work, but the installer isn't the goal).
- **Backend lifecycle:** on startup, spawn `backend\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1`. Find the repo root from the executable path, or from a `SHADOWTREE_REPO` env var. Wait for `/health`, and show the UI's loading state meanwhile. Kill the backend process tree when the window closes; the venv `python.exe` is a launcher, so kill the whole tree. If port 8000 is already serving ShadowTree, reuse it.
- **Native drag and drop:** use the window's drag-drop event to take the real path. If it's a folder, start the scan; if it's a file, scan its parent folder.
- **Folder picker:** use `@tauri-apps/plugin-dialog` `open({ directory: true })`. In a normal browser, keep the current `/pick-folder` fallback (detect Tauri at runtime).
- Add the Tauri origins (`http://tauri.localhost`, `tauri://localhost`) to `ALLOWED_ORIGINS`.
- The CSP must allow WASM (`'wasm-unsafe-eval'`), `connect-src` to `http://127.0.0.1:8000`, `https://events.desertant.com` and the HF fallback hosts. Then check that Redact, Gist and Emo still load in the window.
- The browser version (`npm run dev`) must keep working.

## Step 6: docs
- **README:**
  - new architecture diagram (Tauri → frontend + Python backend; no GLiClass)
  - run commands (`npm run tauri dev` as the main way, the browser way as the alternative)
  - new sizes and RAM figures
  - a **models table** (model, lab, license, size, job)
  - updated Network & privacy section with the new download hosts
  - credits: remove Knowledgator; add Moritz Laurer (DeBERTa), Minish Lab (potion), FlashRank / ms-marco, RapidOCR / PaddleOCR. **Check each license on its model card.**
- Update `docs/devpost_story.md` and `docs/demo_script.md` to match.

Write `docs/review/shadowtree.md`: what was done per step, the commands with their output, the classification scores for the sample folder, search results for "money I spent" and "invoice", RSS memory, and known issues. **Then stop for review.** The reviewer re-records the demo video after that.

---
**Cut line: do not start these before the deadline.** Silero VAD + Moonshine (audio), Desert Ant v6 upgrade + Eye. List them under "Next steps" in the README and Devpost story.
