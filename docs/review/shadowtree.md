# ShadowTree: review note (torch-free stack, search, OCR, Tauri app)

Date: 25 Nov 2026. All commits are local on `main`. Nothing is pushed. Owner plan: `docs/review/shadowtree-plan.md`. Numbers come from the step notes in `reports/shadowtree/` (not tracked, `reports/` is gitignored).

## Review fixes (owner feedback, 25 Nov)

Two fixes from the owner's review, checked again by a separate chat. Commits are local, not pushed.

### Fix 1: best-guess folder (`a984a9c`, `470375f`)

Rule, in order:
1. A topic folder with a score of 0.5 or more links as before.
2. If none reaches 0.5 and the file is not an image or audio file, the single best topic folder links when its score is at least `SOFT_FLOOR` (env, default 0.15). The real score is stored.
3. Below the floor, the file goes to Unsorted.
4. Images and audio stay sorted by file type (Screenshots & Media).
5. New-folder jobs keep the strict 0.5 rule.
6. In the UI, a topic chip under 0.5 is dashed and muted, with the tooltip "Best guess".

Tests: `tests/test_soft_floor.py` (best 0.3 gives one soft link with score 0.3; best 0.14 gives Unsorted; a strong match gets one link; a new-folder job does not link a 0.3 file). Backend suite: 102 passed.

Sample folder (real models, scratch DB outside the repo): 9 links, Unsorted 0, best-guess links 0.

| File | Links |
|---|---|
| bank transfer note.txt | Finance & Receipts 0.911 |
| coffee receipt.txt | Finance & Receipts 0.985 |
| invoice-2041.pdf | Finance & Receipts 0.974 |
| journal.txt | Personal & Notes 0.895 |
| meeting notes.md | Work & Research 0.575 |
| research outline.md | Work & Research 0.591 |
| Screenshot 2026-11-20.png | Screenshots & Media 1.0 |
| voice memo.wav | Screenshots & Media 1.0, Finance & Receipts 0.918 |

Real folder (one test, read-only, scratch DB, counts only): Unsorted went from 112 of 142 files before to 63 of 134 after. 49 files got a best-guess link. The scan took 547 s with 0 errors. The folder changed a little between the two runs.

### Fix 2: a high match needs real reranker agreement (`64ad26f`, `8d605f5`, `c59ee5e`)

Cause, with numbers from the old run:
- BM25 is min-max scaled, so a lone full-text hit is always 1.0. For "tax documents" only the research outline contains "documents". With z -10.84 (noise) and cosine 0.267, the old noise branch gave 0.7 * min(0.267 / 0.35, 1) + 0.3 * 1.0 = 83%.
- For "invoice" the screenshot had z 0.09 (weak but real) and cosine 0.345. The old sigmoid((z + 4) / 2) gave it 70%, next to the invoice at 100%.
- For "money I spent" every z was between -11.1 and -10.8 (noise). The old branch used cosine alone, so the bank note (0.301) led and the receipt (0.106) was 4th.

Old formula:
`
z >= -6:  0.6 * sigmoid((z + 4) / 2) + 0.3 * min(cos / 0.6, 1) + 0.1 * bm25_norm
else:     0.7 * min(cos / 0.35, 1) + 0.3 * bm25_norm
`
New formula (`backend/app/search.py`):
`
z >= -6:  0.7 * sigmoid((z - 1) / 0.7) + 0.15 * min(cos / 0.6, 1) + 0.15 * bm25_norm
z < -6:   20 * (0.5 * min(cos / 0.35, 1) + 0.5 * clamp((z + 12) / 1.2, 0, 1))   (capped at 20, under the cut-off of 25)
no reranker: 0.7 * min(cos / 0.35, 1) + 0.3 * bm25_norm
`
The name boost (+20) and the cut-off of 25 are unchanged.

Re-run by this chat (`backend\.venv\Scripts\python scripts\search_check.py`, real models, its own samples and scratch DB):

~~~
scan: done {'new': 8, 'changed': 0, 'skipped': 0, 'removed': 0, 'skipped_too_large': 0, 'skipped_cloud_only': 0, 'skipped_hidden_or_link': 0}

== 'tax documents'  rerank=True
  weak    17%  z=-10.84 cos= 0.267 bm25=1.00 boost= 0  research outline.md
  weak    10%  z=-11.44 cos= 0.195 bm25=0.00 boost= 0  bank transfer note.txt
  weak    10%  z=-11.58 cos= 0.213 bm25=0.00 boost= 0  meeting notes.md
  weak     8%  z=-11.51 cos= 0.121 bm25=0.00 boost= 0  invoice-2041.pdf
  weak     7%  z=-11.50 cos= 0.092 bm25=0.00 boost= 0  Screenshot 2026-11-20.png
  weak     6%  z=-11.50 cos= 0.066 bm25=0.00 boost= 0  coffee receipt.txt
  results: [] weak: ['research outline.md', 'bank transfer note.txt', 'meeting notes.md']

== 'volcano penguin'  rerank=True
  weak     5%  z=-11.53 cos= 0.055 bm25=0.00 boost= 0  Screenshot 2026-11-20.png
  weak     4%  z=-11.49 cos= 0.008 bm25=0.00 boost= 0  journal.txt
  weak     4%  z=-11.49 cos=-0.029 bm25=0.00 boost= 0  invoice-2041.pdf
  weak     4%  z=-11.50 cos=-0.017 bm25=0.00 boost= 0  meeting notes.md
  weak     4%  z=-11.54 cos=-0.018 bm25=0.00 boost= 0  voice memo.wav
  weak     4%  z=-11.56 cos=-0.029 bm25=0.00 boost= 0  coffee receipt.txt
  results: [] weak: ['Screenshot 2026-11-20.png', 'journal.txt', 'invoice-2041.pdf']

== 'invoice'  rerank=True
  STRONG 100%  z=  1.83 cos= 0.461 bm25=1.00 boost=20  invoice-2041.pdf
  weak    24%  z=  0.09 cos= 0.345 bm25=0.00 boost= 0  Screenshot 2026-11-20.png
  weak    12%  z=-11.57 cos= 0.282 bm25=0.00 boost= 0  coffee receipt.txt
  weak    10%  z=-11.58 cos= 0.213 bm25=0.00 boost= 0  voice memo.wav
  weak     9%  z=-11.53 cos= 0.187 bm25=0.00 boost= 0  meeting notes.md
  weak     9%  z=-11.58 cos= 0.210 bm25=0.00 boost= 0  bank transfer note.txt
  results: ['invoice-2041.pdf'] weak: []

== 'money I spent'  rerank=True
  weak    17%  z=-11.02 cos= 0.301 bm25=0.00 boost= 0  bank transfer note.txt
  weak    13%  z=-10.81 cos= 0.106 bm25=0.00 boost= 0  coffee receipt.txt
  weak    13%  z=-11.09 cos= 0.195 bm25=0.00 boost= 0  voice memo.wav
  weak    11%  z=-11.01 cos= 0.093 bm25=0.00 boost= 0  invoice-2041.pdf
  weak    11%  z=-11.09 cos= 0.109 bm25=0.00 boost= 0  Screenshot 2026-11-20.png
  weak     6%  z=-11.49 cos= 0.048 bm25=0.00 boost= 0  journal.txt
  results: [] weak: ['bank transfer note.txt', 'coffee receipt.txt', 'voice memo.wav']

== 'pay the bill'  rerank=True
  STRONG  97%  z=  3.23 cos= 0.675 bm25=1.00 boost= 0  voice memo.wav
  weak    23%  z= -4.33 cos= 0.373 bm25=0.93 boost= 0  invoice-2041.pdf
  weak    18%  z=-10.99 cos= 0.340 bm25=0.00 boost= 0  bank transfer note.txt
  weak    16%  z= -9.89 cos= 0.225 bm25=0.00 boost= 0  coffee receipt.txt
  weak    15%  z=-11.05 cos= 0.242 bm25=0.00 boost= 0  Screenshot 2026-11-20.png
  weak     7%  z=-11.57 cos= 0.136 bm25=0.00 boost= 0  meeting notes.md
  results: ['voice memo.wav'] weak: []

== 'my diary'  rerank=True
  STRONG  98%  z=  3.47 cos= 0.598 bm25=1.00 boost= 0  journal.txt
  weak    10%  z=-11.50 cos= 0.203 bm25=0.00 boost= 0  meeting notes.md
  weak    10%  z=-11.50 cos= 0.218 bm25=0.00 boost= 0  voice memo.wav
  weak     7%  z=-11.48 cos= 0.097 bm25=0.00 boost= 0  research outline.md
  weak     7%  z=-11.53 cos= 0.103 bm25=0.00 boost= 0  invoice-2041.pdf
  weak     7%  z=-11.53 cos= 0.117 bm25=0.00 boost= 0  coffee receipt.txt
  results: ['journal.txt'] weak: []

== 'coffee'  rerank=True
  STRONG  39%  z= -8.43 cos= 0.327 bm25=1.00 boost=20  coffee receipt.txt
  weak     6%  z=-11.56 cos= 0.083 bm25=0.00 boost= 0  journal.txt
  weak     6%  z=-11.58 cos= 0.080 bm25=0.00 boost= 0  research outline.md
  weak     6%  z=-11.59 cos= 0.106 bm25=0.00 boost= 0  invoice-2041.pdf
  weak     5%  z=-11.55 cos= 0.043 bm25=0.00 boost= 0  voice memo.wav
  weak     5%  z=-11.56 cos= 0.048 bm25=0.00 boost= 0  meeting notes.md
  results: ['coffee receipt.txt'] weak: []

== 'error message'  rerank=True
  STRONG  29%  z= -3.30 cos= 0.556 bm25=1.00 boost= 0  Screenshot 2026-11-20.png
  weak    10%  z=-11.44 cos= 0.188 bm25=0.00 boost= 0  meeting notes.md
  weak    10%  z=-11.48 cos= 0.186 bm25=0.00 boost= 0  coffee receipt.txt
  weak     9%  z=-11.45 cos= 0.150 bm25=0.00 boost= 0  bank transfer note.txt
  weak     9%  z=-11.46 cos= 0.164 bm25=0.00 boost= 0  invoice-2041.pdf
  weak     8%  z=-11.35 cos= 0.087 bm25=0.00 boost= 0  journal.txt
  results: ['Screenshot 2026-11-20.png'] weak: []

== 'meeting'  rerank=True
  STRONG  45%  z= -3.35 cos= 0.390 bm25=1.00 boost=20  meeting notes.md
  weak    13%  z=-10.42 cos= 0.104 bm25=0.00 boost= 0  voice memo.wav
  weak     9%  z=-11.09 cos= 0.064 bm25=0.00 boost= 0  bank transfer note.txt
  weak     8%  z=-11.45 cos= 0.127 bm25=0.00 boost= 0  invoice-2041.pdf
  weak     7%  z=-11.48 cos= 0.094 bm25=0.00 boost= 0  coffee receipt.txt
  weak     6%  z=-11.45 cos= 0.041 bm25=0.00 boost= 0  journal.txt
  results: ['meeting notes.md'] weak: []
~~~

Owner's cases, all as expected: "tax documents" and "volcano penguin" give results [] (weak only). "invoice" gives only the invoice as strong. "money I spent" has no strong match, and the coffee receipt is 2nd (weak). "pay the bill" gives the voice memo, "my diary" the journal, "coffee" the coffee receipt, "error message" the screenshot, "meeting" the meeting notes.

### Small things
- `ai_classify.py` module docstring no longer says classify waits for DeBERTa (`827d20e`).
- README: scan-speed note (about 3-4 s per file on a real folder; 375 s and 547 s for about 135 files), and the two limits rewritten.

### Commands (trimmed)
~~~
cd backend; .\.venv\Scripts\python -m pytest -q          102 passed in 9.94s
backend\.venv\Scripts\python scripts\search_check.py     9 queries, output above
cd frontend; npm run build                               built in 1.10s
~~~

### Known issues after these fixes
- "money I spent" has only weak matches. The receipt is second.
- "error message" finds the screenshot at 29%, near the cut-off of 25.
- "pay the bill": the invoice dropped to weak (23%).
- "coffee" is carried by the name boost (39% with +20).
- The formula was tuned on 8 sample files.
- The dashed "Best guess" chip was not checked visually (CSS variables only).
- A fresh full scan of the real folder was not repeated by this chat.
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

## Search results (before Fix 2, kept for history)

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

- **The sorter is strict.** Before Fix 1, a copy of a real 164-PDF folder sent 124 files to Unsorted. With the soft floor, 63 of 134 files stayed in Unsorted in one real test. The sample folder is fine.
- **Work & Research margin is thin** on the samples: 0.575 and 0.591 against 0.5.
- **"money I spent"** now shows only weak matches (see Review fixes above).
- **Needle returns nothing for some files** (3 of 8 in the live check). The fallback title and summary are used, and sorting is not affected.
- **OCR** dropped one space on a test scanned bill ("30November"). Only the first 3 pages of a scanned PDF are read. Old images and thin PDFs are read again once after an upgrade, which runs Mirage and Needle on them. Screenshots indexed before the OCR text fix keep Mirage's text copy until re-indexed.
- **Not tested by hand:** a real drag from Explorer, the native folder picker with real clicks, window focus on a second start, a hung model after the CSP fix (the same "not available" path was tested with `?ai=off`), and the Desert Ant license call to `events.desertant.com` under the new CSP (not seen in the last run, not blocked).
- **WebView2** contacts Microsoft hosts by itself. That is the Windows runtime, not app code.
- **Existing DBs:** vectors are filled in the background on first start, so the first searches on a large old DB may be partial.
- `npm run dev` in a normal browser was run again in the fresh-clone check (scan, Sensitive = 5).

## Final checks

**Release window re-check** (rebuilt exe, `a1d6074` to `d3f6798`, independent chat): 8 of 8 checks pass, 0 MUST-FIX. No `EvalError` or console error across about 1,400 page samples. Sensitive (PII) = 5 and the emoji for "Bills to pay" is suggested. No raw name, email or phone appeared on any card, search result or the Redacted drawer at any time. With `?ai=off`, all 8 cards show the file name and "Privacy check not available". The page called only `tauri.localhost`, `ipc.localhost` and `127.0.0.1:8000`, with no Hugging Face. The 8 sample files had identical sha256, size and modification time before and after. `events.desertant.com` was not seen in the last two runs. It is not blocked. Six NICE items remain, for example `?ai=off` shows "Checking privacy..." for about 3 s first.

**Fresh-clone run** (clone of `main` at `761fabe`, every README command run as written, in README order): every command worked, 0 MUST-FIX. `pip install` 120 s, `download_models.py` 262 s, `npm run fetch-models` 37 s, `pytest -q` gave `98 passed`, `npm run build` passed. Browser way: backend `/health` ok, `npm run dev` ready, scan of the 8 samples in 12 s with no errors, Sensitive = 5. `npm run tauri dev`: window up after about 3 minutes (Rust compile 2 min 51 s), backend started by the window, the 8 files and Sensitive 5 shown, no console errors. Not run: `npm run tauri build`. Eleven NICE items were fixed in the README (typos, prerequisites, times, Vite address, Ctrl+C).

**Vite watcher fix** (`9990cc4`): Vite now ignores `frontend/src-tauri`, so `npm run tauri dev` prints no `EBUSY` file-watcher lines (0 in the re-run).
## Left out (cut line)

Not started, as the plan said: Silero VAD + Moonshine (audio), Desert Ant v6 upgrade + Eye. Both are listed under "Next steps (not built)" in the README and the Devpost story.

## Reports kept locally (not tracked)

`reports/shadowtree/`: `step0.md`, `step1.md`, `step2.md`, `step3.md`, `step4.md`, `step5-tauri.md`, `plan-review.md`, `check-backend-code.md`, `live-check.md`, `backend-nice-fixes.md`, `tauri-live-fixes.md`.
