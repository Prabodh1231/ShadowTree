# Phase 1: FastAPI backend

Status: built, 29 pytest tests pass (all models mocked), real offline end-to-end run passed. The commands and trimmed
output behind both are in [Commands and output](#commands-and-output).

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

## Commands and output

All commands are PowerShell 5.1 and were run from `<repo>` unless noted. Output is trimmed and copied from
the run; where the raw output was not kept, the line says so.

**1. Install the new dependencies** (from `backend\`). Output tail not kept; `pip check` printed `No broken requirements found.`

```powershell
.\.venv\Scripts\python.exe -m pip install fastapi uvicorn pypdf pytest httpx soxr
# Successfully installed certifi-2026.11.20 fastapi-0.165.0 httpcore-1.0.9 httpx-0.28.1 iniconfig-2.3.1
#   opentelemetry-api-1.45.2 pluggy-1.7.0 pypdf-7.1.1 pytest-9.2.0 soxr-1.1.0 starlette-1.10.0 uvicorn-0.54.0
.\.venv\Scripts\python.exe -m pip check
# No broken requirements found.
```

**2. Download the models** (offline-safe, models were already cached, so it verified):

```powershell
backend\.venv\Scripts\python.exe scripts\download_models.py 2>$null | Select -Last 14
# data dir: <repo>\backend\data
# [ok]   Cactus Mirage (image description): 1.0s
# [ok]   Cactus Whistle (audio transcription): 0.3s
# [ok]   Cactus Needle 3 (structured extraction): 0.5s
# [ok]   GLiClass knowledgator/gliclass-v4-edge (no onnx/): 1.4s
# sizes: cactus cache 76 MB, hugging face cache 965 MB
# done.
```

(The shell showed `Exit Code: 1` for that line because of the `Select` pipe; the script's own text says `done.`.)

**3. Tests** (from `backend\`). The first full run stopped at one failing test (a test bug, `json.dumps` escapes backslashes);
a later run failed once on `test_post_folders_during_running_job` (a failed `INSERT` left a write lock open; fixed with
`conn.rollback()` in `main.py`). Final runs:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# .............................                                            [100%]
# 29 passed in 2.91s
.\.venv\Scripts\python.exe -m pytest -q          # after commit 3b1c855
# 29 passed in 2.22s
```

**4. Make the sample files** in `%TEMP%\veilfs e2e\Bob's messy files` (outside the repo). The text files were written with
`Set-Content`; the WAV with `System.Speech`; the PNG and the hand-built PDF with a small Python script `%TEMP%\mk.py`
(Pillow, no new deps) that received the folder as `sys.argv[1]`. No output was printed except the file list:

```powershell
$d="$env:TEMP\veilfs e2e\Bob's messy files"
Set-Content "$d\invoice.txt" "Invoice INV-2041 from Northwind Supplies. Billed to billing@example.com, phone +1 555-0142. ..."
$s.SetOutputToWaveFile("$d\voice memo.wav",$f); $s.Speak("Please pay the electricity invoice of sixty four dollars before Friday.")
& "<repo>\backend\.venv\Scripts\python.exe" "$env:TEMP\mk.py" $d
Get-ChildItem $d -Recurse | Select Name,Length
# budget screenshot.png 12838 | invoice.txt 194 | journal.txt 128 | rental agreement.pdf 613 | voice memo.wav 158286
# sub dir\meeting notes.md 152
```

**5. Record the "before" state** (SHA-256 of every file, plus size and mtime ticks for every entry). Result files are in
`%TEMP%\veilfs e2e\` (`before.csv`, `before.txt`); the full text was not pasted into this note.

```powershell
Get-ChildItem $d -Recurse -File | Get-FileHash | Select Hash,@{n='f';e={Split-Path $_.Path -Leaf}} | Export-Csv "$e\before.csv" -NoTypeInformation
Get-ChildItem $d -Recurse | % { "$($_.FullName.Substring($d.Length)) $($_.Length) $($_.LastWriteTimeUtc.Ticks)" } | Set-Content "$e\before.txt"
(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB     # free GB: 3.62  -> float32 (rule: bfloat16 only under 3.5)
```

**6. Start the server** with its own DB, from `backend\`'s working directory, hidden window, output to files:

```powershell
$env:VEILFS_DB_PATH="$e\e2e.db"; $env:GLICLASS_DTYPE="float32"     # $e = %TEMP%\veilfs e2e
Start-Process -FilePath ...\backend\.venv\Scripts\python.exe -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000","--workers","1" `
  -WorkingDirectory ...\backend -RedirectStandardOutput "$e\server.out" -RedirectStandardError "$e\server.err" -WindowStyle Hidden
```

The server was started twice: once for a first scan (which showed the image title and ranking problems), and again with a
fresh DB after commit 3b1c855's changes. The numbers below are from the second run unless noted. `server.out`/`server.err`
only held model-loading progress bars (not pasted).

**7. `/health` before any scan** (first run's output, same fields in the second):

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json -Depth 5
# "status": "ok"
# "cactus":   { "loaded": false, "files_present": { "needle3": true, "whistle": true, "mirage": true }, "hint": null }
# "gliclass": { "loaded": false, "files_present": true, "dtype": "float32", "load_error": null, "hint": null }
# "job": "idle"
```

After the scan: `{"status":"ok","cactus":{"loaded":true,...},"gliclass":{"loaded":true,...,"dtype":"float32","load_error":null},"job":"done"}`.

**8. Scan and status:**

```powershell
$b=@{root=$d}|ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/scan -Method Post -Body $b -ContentType "application/json"
# {"job_id":1}
Invoke-RestMethod http://127.0.0.1:8000/scan/status       # polled every 4 s until state != running
# scan: done {"new":6,"changed":0,"skipped":0,"removed":0} errors=0       (second run; first run: processed 6, total 6)
```

Rescan (same request): `{"new":0,"changed":0,"skipped":6,"removed":0}`.

**9. Files:** `Invoke-RestMethod http://127.0.0.1:8000/files`. The raw JSON was not kept; the per-file table above in "Real offline run"
is taken from that response (title, summary, keywords, ai_status, folders with score).

**10. Search** (`$q` was URL-escaped with `[uri]::EscapeDataString`). Raw JSON was not kept; the lines below are the
formatted output of the second run:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/search?q=money%20I%20spent"
# q=money I spent rerank=True
#   rental agreement.pdf score=0.295 match=100
#   invoice.txt score=0.247 match=84
#   budget screenshot.png score=0.205 match=69
#   voice memo.wav score=0.138 match=47
# q=Northwind rerank=True
#   invoice.txt score=0.548 match=100
```

First run (before the no-FTS-hit weighting): top hit was `budget screenshot.png score=0.418 match=70`, invoice `match=41`.

**11. Reveal.** `POST /reveal` with `{"file_id":2}` returned `{"revealed":true}`. The window was read back with
`Shell.Application` (`LocationURL`, `SelectedItems()`), then closed:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/reveal -Method Post -Body '{"file_id":2}' -ContentType "application/json"
# API reveal: {"revealed":true}
# file:///<temp>/veilfs%20e2e/Bob's%20messy%20files selected=[invoice]
Start-Process explorer -ArgumentList "`"/select,$f`""      # the spec's single-argument form
# (no window under the temp folder was found afterwards)
```

An earlier attempt with `$id = (... | ? name -eq ...).id` failed in PowerShell (the array unrolled into `[1,2,3,4,5,6]`, so the API
answered 422); that is a script problem, not an API one.

**12. Snapshot.** `/export/snapshot` was **not** called in the real run. It is covered only by the mocked test
`test_snapshot_uses_relative_paths` (relative paths, no `text_excerpt`, no absolute path in the output).

**13. Read-only check** (after the server was stopped with `Stop-Process` on the uvicorn processes):

```powershell
Get-ChildItem $d -Recurse -File | Get-FileHash | ... | Export-Csv "$e\after.csv"
Get-ChildItem $d -Recurse | % { ... } | Set-Content "$e\after.txt"
"hash diff: " + (Compare-Object (Get-Content $e\before.csv) (Get-Content $e\after.csv) | Measure-Object).Count
"listing/size/mtime diff: " + (Compare-Object (Get-Content $e\before.txt) (Get-Content $e\after.txt) | Measure-Object).Count
# hash diff: 0
# listing/size/mtime diff: 0
```

The DB (`e2e.db`, `-wal`, `-shm`) and logs sit in `%TEMP%\veilfs e2e\`, next to the scanned folder, not inside it.

**14. Needle single-field experiment** (output captured to `%TEMP%\needle_exp.txt`):

```powershell
backend\.venv\Scripts\python.exe spikes\needle_single_field.py 2>$null | Out-String -Width 220 | Set-Content "$env:TEMP\needle_exp.txt"
# None counts of 6: combined=3, title-only=5, keywords-only=6
```

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
10. Extra Origin check: any request with an `Origin` header outside the allowed list gets 403 (CORS alone only hides responses), plus `TrustedHostMiddleware` for `127.0.0.1` and `localhost` (bad `Host` gets 400). Not in the spec.
11. `/scan/status` returns more than `{state, processed, total, current_file, errors}`: also `job_id`, `kind`, `stats` and `queued_job_id`.
12. Two settings instead of one data path: `VEILFS_DATA_DIR` (model caches) and `VEILFS_DB_PATH` (the database), so tests and the real run use their own DB.
13. The scanner skips every reparse point, junction and symlink (and hidden or system items), not only hidden/system dirs as the spec says.
14. Size limits not in the spec: `/files?q=` and `/search?q=` at most 200 characters (422 above), `PATCH client-meta` `pii_types` and `topics` at most 40 items of at most 80 characters each, `redacted_excerpt` at most 5000, folder `name` 1-60, `description` 300, `emoji` 16, scan `root` 1024. Bodies reject extra fields (422).

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
- Pytest count was run once after the last code commit: 29 passed (see [Commands and output](#commands-and-output)).

Open items from the code reviews. They stay open on purpose; the owner decides on them. Code was not changed in this fix.

- N2: a `/scan` request that is rejected with 409 still overwrites `app_meta.scan_root` (`main.py`, the write comes before `jobs.start_scan`). Snapshot relative paths then use the wrong root until the next scan.
- N3: if a folder cannot be listed (or a file cannot be stat-ed) during a scan, its rows are treated as missing and deleted from the DB. Disk is untouched and a rescan restores them, but the index shrinks silently.
- N5: only an `ImportError` from Whistle is cached; any other load error (`RuntimeError`) is retried for every audio file.
- N6: `/search` reranks up to 50 FTS hits plus up to 200 recent files in one GLiClass call while holding the model lock. That can take tens of seconds, blocks a running scan, and can push `/search` into the BM25 fallback.
- N7 (half fixed): the `/reveal` argument form (`/select,` and the path as separate args) was checked once by hand on a path with a space and an apostrophe, but `test_api.py` only asserts `args[0][0] == "explorer"`, not the second and third items.
- N8: each request thread keeps its own SQLite connection open (WAL handles) until the process ends. Bounded by the thread pool size.
- N9: files with the reparse-point attribute are skipped silently, including OneDrive cloud placeholders; there is no `errors` entry and no skip count.
- N10: `/health` has a dead clause (`"whistle" in loaded` is already covered), and `cactus_files_present` does not check the Cactus engine DLL, so `files_present` can be true while the first run still needs the engine download.
- N11: the `_ONLY_NUM_DATE` regex in `extractors.py` contains a stray literal `?` (probably a mangled currency sign), so a line made only of digits and `?` is dropped as "number only".
- N12: test gaps: no test for text PDF extraction, the 25 MB boundary (only `MAX_FILE_MB=0`), summary sentence choice, the 6-keyword cap, or a custom folder pushing labels past 25 per call.

From the live check with real models (`docs/review/phase-1-verification.md`):

- L1: search relevance is weak in the live run too: "money I spent" gave receipt 100, screenshot 74, invoice 68 (invoice third); "invoice" ranked a voice memo (73) above the invoice PDF (70). There is no minimum cut-off, so unrelated files show 25-42. A relevance issue, not a crash (`search.py`).
- L2: Needle junk can be accepted as `summary:model` (meeting notes: "Sam owns the API migration digitale migration"). Rejecting summaries with tokens not in the source is not done (`ai_cactus.py`).
- L3: with models missing, `ai_error` is long and multi-line (the full Hugging Face error, about 700 characters per file). Status is `fallback` and nothing crashes (`ai_cactus.py`, `scanner.py`).
- L4: adding a folder re-scores every file against the new label set, so existing links can disappear (adding "Audio Memos" dropped both voice memos out of Finance & Receipts). Probably expected; needs a README line (`scanner.py`, reclassify-all).
- L5: some files have `ai_status=ok` together with `ai_error="needle returned nothing"`, and the provenance suffix is not always shown (`ai_cactus.py`, `build_card`).
- L6: `/health` `files_present` is a dict for Cactus and a bool for GLiClass (`main.py:79`).
- L7: on Windows, asyncio opens a socket bound to `0.0.0.0` (an internal socketpair that connects only to 127.0.0.1). It is not a service, but `Get-NetTCPConnection` shows it.
- L8: the venv `python.exe` is a launcher, so the PID returned by `Start-Process` is not the server PID. Stopping only the launcher can leave the server running; the README stop instructions should say so.

## Carried forward

- Phase 2: "Powered by Desert Ant Labs" credit linked to https://desertant.com in the sidebar footer; self-host the browser models (`scripts/fetch-browser-models.mjs`, `modelBaseUrl`).
- Phase 3: demo build without Desert Ant (precomputed `client_meta` in `snapshot.json`); sample generator must pass paths as arguments, not interpolate them into PowerShell strings.
- README "Network & privacy" must also list the Cactus engine download and the HF CDN host.
