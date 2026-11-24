# Phase 1: FastAPI backend

Status: built, 29 pytest tests pass (all models mocked), real offline end-to-end run passed.

## What was built

| File | Job |
|---|---|
| `backend/app/config.py` | `get_settings()` (read at call time, env-overridable), `apply_env(allow_download=False)` |
| `backend/app/db.py` | SQLite schema, seeds, one connection per thread, FTS5 sync helpers, API card view |
| `backend/app/extractors.py` | Read-only text/PDF/image/WAV readers, fallback title, summary and keywords |
| `backend/app/ai_cactus.py` | Mirage, Whistle, Needle wrappers, model lock, `build_card()` per-field merge |
| `backend/app/ai_classify.py` | GLiClass load-once wrapper, classify, rerank, disk presence checks |
| `backend/app/scanner.py` | Read-only walk, change detection, classification links, reclassify-all |
| `backend/app/jobs.py` | One background job thread, status, queued reclassify |
| `backend/app/search.py` | FTS5 prefilter, GLiClass rerank, `match` formula |
| `backend/app/main.py` | Endpoints, CORS, TrustedHost, Origin check, lifespan |
| `scripts/download_models.py` | Idempotent model download (the only script that goes online) |
| `backend/tests/` | 29 tests |
| `spikes/needle_single_field.py` | Optional Needle experiment (not imported by the app) |

Commits: `1c2580a` deps/config/db, `0ca6a0f` extractors + AI wrappers, `96375bd` scanner + jobs,
`f64a274` API + search, `90d2c47` download script, `045b4ef` tests, `3b1c855` fixes from the real run + experiment.
(Search was committed with the endpoints, not as its own commit, because `main.py` imports it.)

## Run command (from `backend\`)

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

No `--reload` (a second process would load a second 2.3 GB model). Tests: `.\.venv\Scripts\python.exe -m pytest -q`
(needs `pip install -r requirements-dev.txt`).
Download models once: `backend\.venv\Scripts\python.exe scripts\download_models.py`
(output: Mirage, Whistle, Needle, GLiClass all `[ok]`; cactus cache 76 MB, HF cache 965 MB, onnx/ excluded).

## ai_status

| Value | Meaning |
|---|---|
| `ok` | At least the title or the summary came from Needle, Mirage or Whistle, and no model call raised. |
| `fallback` | A model was empty, invalid, missing, raised or timed out; fallbacks filled the fields. Also: encrypted or text-less PDF, odd WAV. |
| `error` | The file could not be read or parsed (unreadable file, broken PDF, broken image). Still indexed from the name and metadata. |

Per-field provenance is stored at the end of `ai_error`, for example `title:model,summary:whistle,keywords:model+freq`.
A GLiClass failure links the file to Unsorted and appends `[classify: ...]` to `ai_error`; `ai_status` is not changed.
The soft timeout is measured, not enforced: Cactus calls cannot be interrupted from Python, so a call that returns after
`MODEL_TIMEOUT_S` (60 s) is treated as failed and its result discarded. A call that hangs forever is not stopped.

## Search formula

```
score     = raw GLiClass score, query as the only label, prompt "Does the document match the search query?", threshold 0.0
bm25_norm = 0..1 across FTS hits (bm25 flipped, 1 = best); 0 for non-FTS candidates
match     = round(100 * (0.7 * score / max(top_score, 0.15) + 0.3 * bm25_norm)), clamped 0..100
```

Added after the real run: if no candidate is an FTS hit, weights are 1.0 / 0.0 (otherwise the best semantic hit
could never show more than 70). If GLiClass is missing, failing or busy for more than 5 s, results are FTS hits only with
`match = round(100 * bm25_norm)` and `rerank: false`. If FTS gives fewer than 5 hits, the 200 most recent files are added.
The MATCH string quotes every token and is bound as a parameter (`INV-2041` and a lone quote do not error).

## Real offline run

Folder: `%TEMP%\veilfs e2e\Bob's messy files` (space and apostrophe; outside the repo), 6 files: .txt, .md (in `sub dir`),
.png (Pillow), 16 kHz .wav (System.Speech), .pdf (hand-built, no new deps). Own DB: `%TEMP%\veilfs e2e\e2e.db`.
Free memory before the run: 3.62 GB, so `GLICLASS_DTYPE=float32` (rule: bfloat16 only under 3.5 GB). Free memory after: about 1.2 GB.

```
/health (before scan): cactus.loaded=false, files_present all true; gliclass.loaded=false, files_present=true
scan: done, new=6 changed=0 skipped=0 removed=0, errors=[]
rescan: new=0 changed=0 skipped=6 removed=0
```

| File | ai_status | Title | Summary (trimmed) | Folders |
|---|---|---|---|---|
| budget screenshot.png | ok | Budget screenshot | screenshot image. regions: title bar. ... Monthly Budget, Groceries $120.50, Electricity $64.00 | Screenshots & Media 0.77 |
| invoice.txt | ok | INV-2041 | 3 ergonomic chairs at $180 each, 1 standing desk at $420 | Finance & Receipts 0.95 |
| journal.txt | fallback | Journal | Dear diary, today I walked by the lake ... | Personal & Notes 0.99 |
| rental agreement.pdf | fallback | Rental agreement | Rental agreement. The tenant pays 900 dollars rent ... | Finance & Receipts 0.85 |
| voice memo.wav | ok | Voice memo | Please pay the electricity invoice of $64 before Friday. | Finance & Receipts 0.84 |
| meeting notes.md | ok | Q3 roadmap sync | Sam owns the API migration and the search redesign ships in October | Work & Research 0.96 |

Search "money I spent" (rerank true): rental agreement.pdf score 0.295 match 100; invoice.txt 0.247 / 84;
budget screenshot.png 0.205 / 69; voice memo.wav 0.138 / 47; journal.txt 0.031 / 10; meeting notes.md 0.012 / 4.

Read-only check (SHA-256 of every file, size, mtime ticks and listing, before vs after scan, rescan, search, reveal): 0 differences.
The server was stopped afterwards.

`/reveal` check (once, by hand, folder with a space and apostrophe): `["explorer", "/select,", path]` as separate list items opened the
folder with the file selected (read back through Shell.Application: `selected=[invoice]`). The single quoted `"/select,<path>"` argument
from the spec opened nothing selectable in the same check.

## Deviations from the spec

1. `docs/spec.md` still says "no cloud AI APIs and no telemetry". The steering file supersedes it: no user content leaves the machine; the only outbound requests are model downloads and the Desert Ant license check.
2. `/reveal` passes `/select,` and the path as two args (see above), and does not use `check=True`.
3. `/search` `match` is a blend, not `score * 100` (feedback note 4); both `score` and `match` are returned.
4. Needle is called as one held `Cactus(tools=[schema], auto_date=False, stateless=True)` with `complete()`, not `cactus.extract()` (api_notes).
5. Image summary keeps the OCR lines; images keep the filename title because Needle copied junk ("Bar") from the description.
6. An extra `app_meta` table stores the last scan root, so `/export/snapshot` can write paths relative to it (default `relative_paths=true`, no `text_excerpt` unless `include_excerpt=true`).
7. `soxr` installed cleanly (wheel) and is pinned, so non-16 kHz WAVs are handed to Whistle; WAVs that Whistle or the header reader reject take the fallback with an `ai_error`. Not exercised with a real 44.1 kHz file.
8. `requirements-dev.txt` added; `httpx` is a dev dependency (the runtime pins only had `httpx2`).
9. `POST /folders` returns 201 with `{folder_id, job_id, job: "started"|"queued"}`.

## Needle single-field experiment (15 min, feedback note 2)

Six inputs. `None` results: combined schema 3, title-only tool 5, keywords-only tool 6. Single-field tools are worse.
Not adopted. Script: `spikes/needle_single_field.py`.

## Known issues

- Needle returns nothing for journal, PDF and short memo text, so those files get `fallback` status (titles come from the filename). This is the model, not a bug.
- Search relevance for "money I spent" is weak: the rental PDF ranks above the invoice. Raw scores are low and close (0.25 to 0.30). Non-matching files still get a match value (47 for the memo on "Northwind") because non-FTS candidates are reranked too. The UI may want a minimum match cut-off.
- GLiClass float32 took the machine from 3.6 GB to 1.2 GB free. Use `GLICLASS_DTYPE=bfloat16` (1.4 GB, about 8x slower) on a tighter machine.
- The soft timeout cannot stop a hung Cactus call.
- Windows hidden-file skipping was only tested by a unit test setting the hidden attribute; junction skipping is untested.
- Tests do not exercise real PDFs with text or 44.1 kHz WAVs (the real run covered a text PDF and a 16 kHz WAV).
- Pytest count was run once after the last commit: 29 passed.

## Carried forward

- Phase 2: "Powered by Desert Ant Labs" credit linked to https://desertant.com in the sidebar footer; self-host the browser models (`scripts/fetch-browser-models.mjs`, `modelBaseUrl`).
- Phase 3: demo build without Desert Ant (precomputed `client_meta` in `snapshot.json`); sample generator must pass paths as arguments, not interpolate them into PowerShell strings.
- README "Network & privacy" must also list the Cactus engine download and the HF CDN host.
