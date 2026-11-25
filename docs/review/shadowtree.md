# ShadowTree: review note (torch-free stack, search, OCR, Tauri app)

Date: 25 Nov 2026. All commits are local on `main`. Nothing is pushed. Owner plan: `docs/review/shadowtree-plan.md`. Numbers come from the step notes in `reports/shadowtree/` (not tracked, `reports/` is gitignored).

## What was done, per step

| Step | What | Commits |
|---|---|---|
| 0 | Rename to ShadowTree (one word) in user-visible text. Folder picker work committed first, as its own commit. App marker added to `/health`, Tauri origins allowed. | `bd2d5b7`, `c658a56`, `791ebc5` |
| 1 | GLiClass, torch and transformers removed. Added onnxruntime, tokenizers, model2vec, flashrank, rapidocr, pypdfium2 (pinned). `scripts/download_models.py` fetches every model once into `backend/data/`. Steering file updated. | `5958cae`, `aee997e` |
| 2 | Search: potion vectors in `files.vec` (migrated, re-embedded in the background), FlashRank rerank, cut-off 25. | `852b7c8` |
| 3 | Folders: DeBERTa NLI, Screenshots & Media by file type, old rows re-linked, potion pre-filter for new folders, seed descriptions re-tuned. | `a0e5536` |
| 4 | OCR: PP-OCRv5 for images (before Mirage) and for PDFs with under 50 characters of text (pypdfium2, in memory). | `8eb6b76` |
| 5 | Tauri v2 desktop app: backend start or reuse, kill of the whole process tree on close, native folder picker and drag and drop. | `fc30f60`, `bfbf6e9` |
| Fixes | Backend code-check NICE items and OCR text fix. Desktop live-check fixes: CSP, privacy gate fails closed, self-hosted model probe. | `ff3ea9a`, `6cf724a`, `ea03111`, `a1d6074`, `a5153fb`, `b64dfff`, `d3f6798` |
| 6 | README, Devpost story, demo script, spec note, this note. | `9b66d43` and the commit of this file |

## Commands and output (trimmed)

Model download and checks (Step 1):

```
backend\.venv\Scripts\python.exe scripts\download_models.py     exit 0, re-run skips present files
backend\.venv\Scripts\python.exe -m pip check                   No broken requirements found.
backend\.venv\Scripts\python.exe -m pytest -q                   62 passed   (Step 1)
```

Test count per step: 62 (Step 1), 73 (Step 2), 85 (Step 3), 93 (Step 4), 98 (after the backend fixes).

Scan and memory (Steps 3 and 4, `spikes/step3_rss.ps1`, real uvicorn on port 8010, `HF_HUB_OFFLINE=1`):

```
scan state=done took 8.6 s errors=0
(a) steady: scan+searches+folder   WS 629 MB  PeakWS 632 MB  Private 1,219 MB
```

Last full test run after the fixes: `98 passed in 6.87s` (backend, models mocked).

Desktop (Step 5): `cd frontend; npm run tauri dev` (main way), `npm run tauri build` makes `frontend/src-tauri/target/release/shadowtree.exe` (144,295,424 bytes after the last rebuild, no installer; cold build 4 min 55 s).

## Folder scores, sample folder

DeBERTa entailment score per topic folder (Screenshots & Media is decided by file type, not scored). Fresh DB, real models, after OCR (Step 4):

| File | Finance & Receipts | Work & Research | Personal & Notes | Linked to |
|---|---|---|---|---|
| bank transfer note.txt | 0.911 | 0.003 | 0.001 | Finance & Receipts |
| coffee receipt.txt | 0.985 | 0.004 | 0.001 | Finance & Receipts |
| invoice-2041.pdf | 0.974 | 0.035 | 0.003 | Finance & Receipts |
| meeting notes.md | 0.007 | 0.575 | 0.003 | Work & Research |
| research outline.md | 0.155 | 0.591 | 0.031 | Work & Research |
| journal.txt | 0.006 | 0.004 | 0.895 | Personal & Notes |
| Screenshot 2026-11-20.png | 0.096 | 0.006 | 0.001 | Screenshots & Media |
| voice memo.wav | 0.918 | 0.003 | 0.002 | Screenshots & Media, Finance & Receipts |

The live check on the release window matched these (Finance 4, Work 2, Personal 1, Media 2, Unsorted 0).

New folder "Bills to pay" with description "invoices, bills and payments that are due" (potion pre-filter at cosine 0.30, then DeBERTa): the invoice (0.965) and the voice memo (0.896) join. Bank transfer note 0.303, others are filtered or low. Job time 0.08 s.

## Search results

Match percentage, 8 sample files, HTTP, real models (live check).

| Query | Results (match %) |
|---|---|
| invoice | invoice-2041.pdf 100, Screenshot 79 |
| money I spent | bank transfer note 86, voice memo 56, coffee receipt 30, Screenshot 30, invoice-2041.pdf 27 |
| pay the bill | voice memo 98, invoice-2041.pdf 56 |
| my diary | journal.txt 99 |
| volcano penguin | no results. Weak: Screenshot 18, bank note 7, journal 2 |

"money I spent" does **not** put the receipt or invoice first. The bank transfer note comes first (rent is money spent), and the receipt and invoice are listed after it. The potion cosine between that query and the receipt is only 0.11. No ordering hack was added. The demo script uses `invoice`, `pay the bill` and `my diary` instead.

Search speed, warm: median 4 to 8 ms on 8 files, 31 ms on a 164-file copy of an old DB. First search 142 to 246 ms (loads FlashRank).

Formula (from `backend/app/search.py`, `z` is the FlashRank logit):

```
confident (best z >= -6):  mix = 0.6 * sigmoid((z + 4) / 2) + 0.3 * min(cos / 0.6, 1) + 0.1 * bm25_norm
otherwise:                 mix = min(cos / 0.35, 1), with full-text hits bm25_norm joins at weight 0.3 (cosine 0.7)
match = round(100 * mix) + name boost (+20 when every query word is in the name or title)
```

Deviation from the plan (`match = score * 100`): FlashRank returns tiny scores, so that would show 0% for every meaning query. The cut-off is 25.

## Memory (backend RSS, working set)

| Point | Working set | Peak | Private bytes |
|---|---|---|---|
| Idle after `/health` | 58 MB | 58 MB | 653 MB |
| Right after a scan (Cactus, OCR, DeBERTa, potion loaded) | 596 MB | 603 MB | 1,183 MB |
| Steady after scan, 20 searches, new folder (all models) | 629 MB | 632 MB | 1,219 MB |
| Release window, same flow (live check) | 625 MB | 627 MB | 1,217 MB |

Under the 1 GB target. Private bytes are 1.2 GB, but 653 MB of that is reserved at idle before any model loads. GLiClass used 2.3 GB before. The WebView2 processes use about 1.2 GB more, outside the backend.

Scan of the 8 samples: about 7 s after Step 3, 8.5 s with OCR. Classify: about 25 ms per file and folder pair.

## Deviations from the plan

- **Release CSP has `'unsafe-eval'` in `script-src`.** The plan asked for `'self' 'wasm-unsafe-eval'`. Without `'unsafe-eval'`, Gist and Emo threw `EvalError` in the packaged window (no topics, no emoji, no privacy pass). The Desert Ant wasm glue builds code from a string (`swjs_call_new`), and the SDK has no option to avoid it. The limit: `script-src` has no `'unsafe-inline'` and no remote script hosts, so only code already loaded from the app itself can reach `eval`. File text is never inserted as HTML (no `innerHTML` and similar in `frontend/src`). Final value: `script-src 'self' 'wasm-unsafe-eval' 'unsafe-eval'`. Other directives: `default-src 'self'`, `worker-src 'self' blob:`, `connect-src` limited to `127.0.0.1:8000`, `events.desertant.com` and the Hugging Face fallback hosts. The dev CSP was set to the same value.
- **OCR models come from `modelscope.cn`** (SHA256 checked), not Hugging Face. The multilingual `ch` recognizer is used, because the English one read `0x80070005` as `Ox80070005`. Both hosts are listed in the README.
- **DeBERTa pairs run one at a time**, not in a padded batch, because the quantized graph shifts scores with padding (0.57 vs 0.79 for the same file).
- **Seed folder descriptions were shortened** so that the journal and research outline reach 0.5.
- **Privacy now fails closed.** A file whose privacy check is not done shows its name and "Privacy check not available", never raw text.

## Known issues

- **The sorter is strict.** On a copy of a real 164-PDF folder, 124 files went to Unsorted after the re-link (GLiClass had put 132 in Work & Research). The sample folder is fine.
- **Work & Research margin is thin** on the samples: 0.575 and 0.591 against 0.5.
- **"money I spent"** lists the bank transfer note first (see Search results).
- **Needle returns nothing for some files** (3 of 8 in the live check). The fallback title and summary are used, and sorting is not affected.
- **OCR** dropped one space on a test scanned bill ("30November"). Only the first 3 pages of a scanned PDF are read. Old images and thin PDFs are read again once after an upgrade, which runs Mirage and Needle on them. Screenshots indexed before the OCR text fix keep Mirage's text copy until re-indexed.
- **Not tested by hand:** a real drag from Explorer, the native folder picker with real clicks, window focus on a second start, a hung model after the CSP fix (the same "not available" path was tested with `?ai=off`), and the Desert Ant license call to `events.desertant.com` under the new CSP (not seen in the last run, not blocked).
- **WebView2** contacts Microsoft hosts by itself. That is the Windows runtime, not app code.
- **Existing DBs:** vectors are filled in the background on first start, so the first searches on a large old DB may be partial.
- `npm run dev` in a normal browser was exercised in the live check (search, Sensitive = 5) before the last fixes; after them only `npm run build` and the dev window were checked.

## Left out (cut line)

Not started, as the plan said: Silero VAD + Moonshine (audio), Desert Ant v6 upgrade + Eye. Both are listed under "Next steps (not built)" in the README and the Devpost story.

## Reports kept locally (not tracked)

`reports/shadowtree/`: `step0.md`, `step1.md`, `step2.md`, `step3.md`, `step4.md`, `step5-tauri.md`, `plan-review.md`, `check-backend-code.md`, `live-check.md`, `backend-nice-fixes.md`, `tauri-live-fixes.md`.
